#!/usr/bin/env python3
"""
seed_sharded.py — shard-aware seeder for ElectroHub.

Why this file exists
--------------------
seed_all.py builds ONE DB_URL from DB_HOST/DB_PORT and writes every row
through it. That URL points at postgres_shard0, so 100% of the data lands
on shard0 and shard1 stays empty. The consistent hash ring in
app/core/consistent_hash.py is therefore never exercised: every read that
routes by user_id happens to find its data because there is only one place
data ever went.

This script routes every row through the REAL ring (ConsistentHashRing via
ShardManager) so that:
    * shard0/shard1 each hold ~50% of the users,
    * a user's own rows always live on the shard the ring assigns them,
    * verify_shards.py can prove it, and the rebalance maths is observable.

Routing rules
-------------
    user                 -> shard(user_id)
    listing + its images -> shard(seller_id)          (co-located with owner)
    interaction          -> shard(actor user_id)
    saved item           -> shard(actor user_id)
    activity row         -> shard(actor user_id)
    message              -> shard(sender_id), plus a replica on
                            shard(receiver_id) when they differ (see below)

Cross-shard messages: the design decision
-----------------------------------------
A conversation has two owners on possibly two different shards. Three
options, and why we picked the third:

  1. Store on the sender's shard only.
     Sending is one write, but "my inbox" then needs a fan-out query to
     every shard on every page load, and unread counts can never be a
     local index lookup. Inbox is the hottest read path in a marketplace,
     so this trades the cheap operation for the expensive one.

  2. Store on a dedicated non-sharded messages DB.
     Clean, but it reintroduces the single hot database the sharding was
     meant to remove, and it is a service this compose file does not have.

  3. DUAL-WRITE: the message row is written to the sender's shard AND the
     receiver's shard, carrying the SAME message_id in both copies.
     This is what we implement. Reads become shard-local: "my inbox" and
     "my sent items" are both answered by the reader's own shard with no
     fan-out at all. The cost is 2x write amplification on messages and
     eventual-consistency risk if one of the two writes fails — for a
     marketplace, where a message is read far more often than it is
     written, that is the right side of the trade.

     Duplicate safety: the two copies share a primary key, so any fan-out
     read that DOES span shards (an admin export, a global search) must
     dedupe on message_id, not on row identity. That is only possible
     because we allocate the id once — from the sender's shard sequence —
     and insert the receiver's copy with that id EXPLICITLY rather than
     letting the receiver shard mint a second one. verify_shards.py asserts
     that every duplicated message_id has byte-identical content on both
     shards, which is what makes "dedupe on message_id" safe.

Globally unique ids across shards
---------------------------------
The schema uses SERIAL/BIGSERIAL, and each shard has its own independent
sequence — so left alone, item_id 42 exists on BOTH shards and means two
different listings. Any cross-shard join or fan-out read would silently
mix them up. Fix: give each shard a disjoint slice of the id space by
interleaving the sequences.

    shard0: INCREMENT BY 2 RESTART WITH 1   -> 1, 3, 5, 7, ...
    shard1: INCREMENT BY 2 RESTART WITH 2   -> 2, 4, 6, 8, ...

Generalised: shard k of N gets INCREMENT BY N RESTART WITH k+1, i.e. every
id it ever mints is congruent to (k+1) mod N. This holds for rows the
application inserts later too, not just for seeded rows — the property
lives in the sequence, not in this script. (The one deliberate exception is
a dual-written message replica: it is inserted with the sender shard's id,
so its id is congruent to the SENDER's shard. That is the point — the
replica is the same row, not a new one.)

Cross-shard foreign keys
------------------------
A foreign key can only be enforced inside one Postgres instance. Under
user-based sharding several FKs in 01_schema.sql are structurally
un-enforceable:

    item_interactions.item_id  -> a user on shard0 can view a listing whose
    item_saved.item_id            seller lives on shard1, so the parent row
    user_activity.item_id         is simply not in this database.

    marketplace_messages.sender_id / .receiver_id / .item_id
                               -> by definition one of the two parties in a
                                  cross-shard conversation is remote.

So this script DROPS exactly those six constraints (idempotently) and
keeps the ones that are always shard-local:

    marketplace_items.seller_id -> kept: a listing is always co-located
                                   with its seller.
    item_images.item_id         -> kept: images follow their item.
    item_interactions.user_id   -> kept: routed by the actor, so the actor
    item_saved.user_id             is always local.
    user_activity.user_id

Referential integrity for the dropped ones moves to the application layer.
That is the normal price of sharding, not a bug — but it is a real loss, so
it is done loudly (the script prints what it dropped) rather than silently.

Usage
-----
From the host (both shards published on localhost:5432 / :5433):

    cd backend
    python3 seed_sharded.py --truncate

Inside a container on the compose network:

    DB_SHARD0_URL=postgresql://postgres:password@postgres_shard0:5432/electrohub \
    DB_SHARD1_URL=postgresql://postgres:password@postgres_shard1:5432/electrohub \
    python3 seed_sharded.py --truncate

Scale flags (defaults are large enough for the distribution stats to mean
something — a 100-user sample cannot tell an even split from luck):

    --users         5000
    --listings      25000
    --interactions  150000
    --saves         30000
    --messages      20000
    --activity      60000

Other flags:
    --truncate      wipe all seven tables on every shard first
    --seed N        RNG seed (default 1337) so runs are reproducible
    --batch-size N  rows per INSERT round trip (default 5000)
    --keep-fks      do NOT drop the cross-shard FKs (will fail on any
                    cross-shard row; useful only to demonstrate why)
"""

import argparse
import hashlib
import os
import random
import sys
import time
from datetime import datetime, timedelta

# Run from backend/ or from the repo root — either way `app` must import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from faker import Faker                                    # noqa: E402
from psycopg2.extras import execute_values                 # noqa: E402

from app.core.shard_db import ShardManager                  # noqa: E402

fake = Faker("en_US")


def h(pw: str) -> str:
    """Same hash seed_all.py uses, so demo logins keep working."""
    return hashlib.sha256(pw.encode()).hexdigest()


# ── Electronics-focused category catalogue (carried over from seed_all) ── #
CATEGORIES = {
    "Phones & Tablets": {
        "products": [
            "iPhone 15 Pro", "iPhone 14", "Samsung Galaxy S24 Ultra",
            "Samsung Galaxy A54", "Google Pixel 8 Pro", "Google Pixel 7a",
            "iPad Pro M2", "iPad Air", "Samsung Galaxy Tab S9",
            "OnePlus 12", "Xiaomi 14 Pro", "Nothing Phone 2",
        ],
        "images": [
            "https://images.unsplash.com/photo-1592750475338-74b7b21085ab?w=400",
            "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=400",
            "https://images.unsplash.com/photo-1585386959984-a4155224a1ad?w=400",
            "https://images.unsplash.com/photo-1580910051074-3eb694886505?w=400",
        ],
        "price": (150, 1600),
    },
    "Computers & Laptops": {
        "products": [
            "MacBook Pro M3", "MacBook Air M2", "Dell XPS 15",
            "Lenovo ThinkPad X1 Carbon", "HP Spectre x360", "ASUS ROG Zephyrus",
            "Microsoft Surface Pro 9", "iMac 24-inch M3", "Mac Mini M2",
            "Razer Blade 16", "LG UltraFine 27-inch Monitor", "Samsung Odyssey G7",
        ],
        "images": [
            "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=400",
            "https://images.unsplash.com/photo-1541807084-5c52b6b3adef?w=400",
            "https://images.unsplash.com/photo-1593642632315-676ce68b786b?w=400",
            "https://images.unsplash.com/photo-1525547719571-a2d4ac8945e2?w=400",
        ],
        "price": (300, 3000),
    },
    "Audio & Sound": {
        "products": [
            "Sony WH-1000XM5", "AirPods Pro 2nd Gen", "Bose QuietComfort 45",
            "Sony WF-1000XM5", "Jabra Evolve2 85", "Sennheiser HD 650",
            "Sonos Era 300", "Bose SoundLink Max", "JBL Charge 5",
            "Apple HomePod mini", "Sonos Move 2", "Bang & Olufsen Beosound A1",
        ],
        "images": [
            "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=400",
            "https://images.unsplash.com/photo-1545127398-14699f92334b?w=400",
            "https://images.unsplash.com/photo-1606220838315-056192d5e927?w=400",
            "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=400",
        ],
        "price": (25, 700),
    },
    "Gaming": {
        "products": [
            "PlayStation 5", "Xbox Series X", "Nintendo Switch OLED",
            "Steam Deck", "PS5 DualSense Controller", "Xbox Elite Controller",
            "Razer DeathAdder V3", "Corsair K70 Keyboard", "LG OLED Gaming TV 55\"",
            "Meta Quest 3", "HyperX Cloud III Headset", "Elgato 4K60 Pro Capture Card",
        ],
        "images": [
            "https://images.unsplash.com/photo-1606144042614-b2417e99c4e3?w=400",
            "https://images.unsplash.com/photo-1593305841991-05c297ba4575?w=400",
            "https://images.unsplash.com/photo-1612287220310-f6e73d13e64a?w=400",
            "https://images.unsplash.com/photo-1536240478700-b869ad10e128?w=400",
        ],
        "price": (30, 1800),
    },
    "Smart Home": {
        "products": [
            "Amazon Echo Show 10", "Google Nest Hub Max", "Apple TV 4K",
            "Philips Hue Starter Kit", "Ring Video Doorbell Pro 2",
            "Nest Learning Thermostat", "Eufy RoboVac X9 Pro", "iRobot Roomba j7+",
            "Arlo Pro 5S Camera", "Amazon Echo Dot 5th Gen", "TP-Link Kasa Smart Plug",
            "Nanoleaf Shapes Panels",
        ],
        "images": [
            "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
            "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400",
            "https://images.unsplash.com/photo-1585771724684-38269d6639fd?w=400",
            "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=400",
        ],
        "price": (20, 900),
    },
    "Cameras & Drones": {
        "products": [
            "Sony A7 IV", "Canon EOS R6 Mark II", "Nikon Z6 III",
            "Fujifilm X-T5", "DJI Mini 4 Pro", "DJI Air 3",
            "GoPro Hero 12 Black", "Sony ZV-E10", "Canon EOS M50 Mark II",
            "DJI Osmo Pocket 3", "Insta360 X4", "Sony RX100 VII",
        ],
        "images": [
            "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=400",
            "https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=400",
            "https://images.unsplash.com/photo-1606986628253-81e4e26e5b13?w=400",
            "https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=400",
        ],
        "price": (120, 2800),
    },
}

CATEGORY_NAMES = list(CATEGORIES.keys())

LOCATIONS = [
    ("Denver", "CO", 80202), ("Boulder", "CO", 80301),
    ("New York", "NY", 10001), ("Los Angeles", "CA", 90001),
    ("Chicago", "IL", 60601), ("Austin", "TX", 78701),
    ("Seattle", "WA", 98101), ("Miami", "FL", 33101),
    ("Boston", "MA", 2101), ("San Francisco", "CA", 94102),
]

CONDITIONS = ["brand new", "like new", "excellent", "good", "fair"]

# Condition drives price: "fair" should not cost the same as "brand new".
CONDITION_MULTIPLIER = {
    "brand new": 1.00, "like new": 0.85,
    "excellent": 0.72, "good": 0.58, "fair": 0.40,
}

ALL_TABLES = [
    "user_accounts", "marketplace_items", "item_images",
    "item_interactions", "marketplace_messages", "item_saved",
    "user_activity",
]

# Sequences we interleave so ids are globally unique across shards, with the
# (table, column) each one backs — we need the column to find the current high
# water mark when reseeding without --truncate.
SEQUENCES = [
    ("user_accounts_account_id_seq", "user_accounts", "account_id"),
    ("marketplace_items_item_id_seq", "marketplace_items", "item_id"),
    ("item_images_image_id_seq", "item_images", "image_id"),
    ("item_interactions_interaction_id_seq", "item_interactions",
     "interaction_id"),
    ("marketplace_messages_message_id_seq", "marketplace_messages",
     "message_id"),
    ("item_saved_save_id_seq", "item_saved", "save_id"),
    ("user_activity_activity_id_seq", "user_activity", "activity_id"),
]

# (table, constraint) pairs that can point at a row on another shard.
CROSS_SHARD_FKS = [
    ("item_interactions", "item_interactions_item_id_fkey"),
    ("item_saved", "item_saved_item_id_fkey"),
    ("user_activity", "user_activity_item_id_fkey"),
    ("marketplace_messages", "marketplace_messages_sender_id_fkey"),
    ("marketplace_messages", "marketplace_messages_receiver_id_fkey"),
    ("marketplace_messages", "marketplace_messages_item_id_fkey"),
]

DEMO_USER_ID = "user_demo_001"
DEMO_EMAIL = "demo@electrohub.com"
DEMO_PASSWORD = "password123"


# ────────────────────────────────────────────────────────────────────────── #
#  Shard plumbing                                                            #
# ────────────────────────────────────────────────────────────────────────── #

class ShardWriter:
    """
    Thin bulk-write wrapper around one raw psycopg2 connection per shard.

    Why raw connections instead of ORM sessions: 300k+ rows through
    session.execute() one statement at a time is minutes of round trips.
    execute_values() collapses each batch into a single multi-row INSERT,
    which is the difference between ~20 minutes and well under a minute.
    We still get the connections FROM ShardManager, so shard identity and
    the ring stay the single source of truth.
    """

    def __init__(self, manager: ShardManager):
        self.manager = manager
        self.ring_names = sorted(manager.distribution().keys())

        # Ask ShardManager for its engines through its public fan-out API
        # rather than reaching into private attributes.
        sessions = manager.get_all_sessions()
        try:
            engines = {name: s.get_bind() for name, s in sessions.items()}
        finally:
            for s in sessions.values():
                s.close()

        self.engines = engines
        self.conns = {}
        for name in self.ring_names:
            raw = engines[name].raw_connection()
            # SQLAlchemy hands back a proxy; .driver_connection (2.x) or
            # .connection is the real psycopg2 connection underneath.
            self.conns[name] = getattr(raw, "driver_connection", None) or raw.connection
            self._raw_holders = getattr(self, "_raw_holders", {})
            self._raw_holders[name] = raw

    def shard_of(self, user_id: str) -> str:
        """The ring — not a modulo, not a guess — decides ownership."""
        return self.manager.get_shard_name(user_id)

    def dsn(self, name: str) -> str:
        """Connection string with the password masked, for the banner."""
        url = self.engines[name].url
        return f"{url.host}:{url.port}/{url.database} as {url.username}"

    def execute_all(self, sql: str, params=None) -> None:
        """Run one statement on every shard (DDL, TRUNCATE, sequence setup)."""
        for name in self.ring_names:
            with self.conns[name].cursor() as cur:
                cur.execute(sql, params)
            self.conns[name].commit()

    def insert(self, shard: str, sql: str, rows: list, page_size: int = 1000,
               fetch: bool = False):
        """One batched multi-row INSERT on a single shard."""
        if not rows:
            return [] if fetch else None
        with self.conns[shard].cursor() as cur:
            result = execute_values(cur, sql, rows, page_size=page_size,
                                    fetch=fetch)
        self.conns[shard].commit()
        return result

    def scalar(self, shard: str, sql: str):
        with self.conns[shard].cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        return row[0] if row else None

    def close(self):
        for name, raw in getattr(self, "_raw_holders", {}).items():
            try:
                raw.close()
            except Exception:
                pass


# ────────────────────────────────────────────────────────────────────────── #
#  Preparation steps                                                         #
# ────────────────────────────────────────────────────────────────────────── #

def preflight(w: ShardWriter) -> None:
    """
    Fail early and clearly if a shard is unreachable or unmigrated.
    A half-seeded cluster is worse than one that refused to start.
    """
    print("\n🔗  Shard map (resolved from env, password hidden):")
    for name in w.ring_names:
        print(f"     {name:<8} → {w.dsn(name)}")

    print("\n🎯  Virtual-node ownership on the ring:")
    dist = w.manager.distribution()
    total = sum(dist.values())
    for name in sorted(dist):
        print(f"     {name:<8} {dist[name]:>5} vnodes  ({dist[name]/total:6.2%})")

    for name in w.ring_names:
        missing = [
            t for t in ALL_TABLES
            if not w.scalar(name, f"SELECT to_regclass('public.{t}') IS NOT NULL")
        ]
        if missing:
            raise SystemExit(
                f"\n❌  {name} is missing tables: {', '.join(missing)}\n"
                f"    Run database/01_schema.sql (and 02_indexes.sql) on it first."
            )
    print("\n✅  All shards reachable and migrated.")


def truncate_all(w: ShardWriter) -> None:
    """
    Wipe every shard. CASCADE because the FKs we keep are ON DELETE CASCADE;
    RESTART IDENTITY so the sequence interleaving below starts from a known
    point instead of continuing from a previous run's high-water mark.
    """
    print("\n🧹  Truncating all tables on every shard...")
    w.execute_all(f"TRUNCATE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE")
    print("   ✅ clean")


def drop_cross_shard_fks(w: ShardWriter) -> None:
    """
    Drop only the FKs that can point across a shard boundary. See the module
    docstring for the full argument; the short version is that Postgres
    cannot enforce a constraint whose parent row lives in a different
    Postgres instance, so keeping these would make ~half of all interaction
    and message rows unwritable.
    """
    print("\n🔓  Dropping structurally un-enforceable cross-shard FKs:")
    for table, constraint in CROSS_SHARD_FKS:
        w.execute_all(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        print(f"     dropped  {table}.{constraint}")
    print("     kept     marketplace_items.seller_id, item_images.item_id,")
    print("              *.user_id  (always shard-local by construction)")
    print("     ⚠  integrity for the dropped ones is now the app's job.")


def interleave_sequences(w: ShardWriter) -> None:
    """
    Give each shard a disjoint slice of every id space.

    shard k of N starts at k+1 and steps by N, so it mints only ids
    ≡ (k+1) mod N. That makes item_id / message_id / activity_id globally
    unique WITHOUT a coordination service. It is a property of the sequence
    itself, so rows the application inserts after seeding inherit it too.
    """
    n = len(w.ring_names)
    print(f"\n🔢  Interleaving sequences across {n} shards "
          f"(shard k mints ids ≡ k+1 mod {n}):")
    for k, name in enumerate(w.ring_names):
        slot = (k + 1) % n
        for seq, table, column in SEQUENCES:
            # Without --truncate the table may already hold rows, so we must
            # RESTART *past* the existing high water mark or the next INSERT
            # collides on the primary key. Pick the smallest value greater
            # than max(id) that still sits in this shard's slot.
            high = w.scalar(name, f"SELECT COALESCE(MAX({column}), 0) "
                                  f"FROM {table}")
            nxt = max(high + 1, k + 1)
            while nxt % n != slot:
                nxt += 1
            with w.conns[name].cursor() as cur:
                cur.execute(f"ALTER SEQUENCE {seq} INCREMENT BY {n} "
                            f"RESTART WITH {nxt}")
        w.conns[name].commit()
        print(f"     {name:<8} mints ids ≡ {slot} (mod {n}): "
              f"{k+1}, {k+1+n}, {k+1+2*n}, ... (resumed past existing rows)")


# ────────────────────────────────────────────────────────────────────────── #
#  Seeding steps                                                             #
# ────────────────────────────────────────────────────────────────────────── #

USER_SQL = """
    INSERT INTO user_accounts
        (user_id, email, password_hash, name, phone, profile_picture,
         bio, city, state, zip_code, created_at, last_login,
         is_active, is_verified)
    VALUES %s
    ON CONFLICT (user_id) DO NOTHING
"""


def seed_users(w: ShardWriter, n_users: int, batch: int) -> dict:
    """
    Create n_users users and route each to shard(user_id).

    The demo user is created first and goes wherever the ring puts it — we
    deliberately do NOT pin it to shard0, because a demo account that only
    works when it happens to be on the default shard would hide exactly the
    routing bug this script exists to fix.
    """
    print(f"\n👥  Seeding {n_users:,} users (routed by ring)...")
    pw = h(DEMO_PASSWORD)
    now = datetime.now()

    demo_shard = w.shard_of(DEMO_USER_ID)
    print(f"     demo user {DEMO_USER_ID} → {demo_shard} "
          f"({DEMO_EMAIL} / {DEMO_PASSWORD})")

    users_by_shard = {name: [] for name in w.ring_names}
    pending = {name: [] for name in w.ring_names}
    written = 0

    def flush(shard):
        if pending[shard]:
            w.insert(shard, USER_SQL, pending[shard], page_size=batch)
            pending[shard] = []

    # index 0 is the demo user; 1..n-1 are generated accounts.
    for i in range(n_users):
        if i == 0:
            uid, email, name = DEMO_USER_ID, DEMO_EMAIL, "Demo User"
            bio = "Demo account for testing."
            city, state, zip_code = "Denver", "CO", 80202
            verified = True
        else:
            uid = f"user_{i:06d}"
            email = f"{uid}@example.com"
            name = fake.name()
            bio = fake.sentence() if random.random() > 0.5 else None
            city, state, zip_code = random.choice(LOCATIONS)
            verified = random.random() > 0.3

        shard = w.shard_of(uid)
        created = now - timedelta(days=random.randint(1, 720),
                                 minutes=random.randint(0, 1439))
        last_login = (created + timedelta(days=random.randint(0, 30))
                      if random.random() > 0.2 else None)

        users_by_shard[shard].append(uid)
        pending[shard].append((
            uid, email, pw, name, fake.phone_number()[:15],
            f"https://ui-avatars.com/api/?name={name.replace(' ', '+')}&size=200",
            bio, city, state, zip_code, created, last_login,
            True, verified,
        ))
        written += 1

        if len(pending[shard]) >= batch:
            flush(shard)
        if written % 25000 == 0:
            print(f"     {written:,}/{n_users:,} users...")

    for shard in w.ring_names:
        flush(shard)

    total = sum(len(v) for v in users_by_shard.values())
    print(f"   ✅ {total:,} users written")
    for name in w.ring_names:
        cnt = len(users_by_shard[name])
        print(f"        {name:<8} {cnt:>8,}  ({cnt/total:6.2%})")
    return users_by_shard


ITEM_SQL = """
    INSERT INTO marketplace_items
        (seller_id, title, description, category, price, city, state,
         zip_code, condition, views_count, saves_count,
         created_at, updated_at, is_active)
    VALUES %s
    RETURNING item_id, seller_id, category
"""

IMAGE_SQL = """
    INSERT INTO item_images (item_id, image_url, is_thumbnail, upload_order,
                             created_at)
    VALUES %s
"""


def seed_listings(w: ShardWriter, all_users: list, n_items: int,
                  batch: int) -> list:
    """
    Listings live on the seller's shard, so "show me my listings" and
    "delete my account, cascade my listings" both stay single-shard.

    Sellers are picked with a deliberate power-law skew (a small set of
    power sellers owns a disproportionate share of inventory). That is the
    realistic shape AND the interesting stress case: without virtual nodes a
    single hot seller can drag one physical shard permanently hot. With 150
    vnodes per shard the skew spreads out, which verify_shards.py measures.
    """
    print(f"\n📦  Seeding {n_items:,} listings + images (routed by seller)...")
    now = datetime.now()

    power_sellers = random.sample(all_users, max(1, len(all_users) // 20))

    pending = {name: [] for name in w.ring_names}
    items = []          # (item_id, seller_id, shard, category)
    made = 0

    def flush(shard):
        if not pending[shard]:
            return
        returned = w.insert(shard, ITEM_SQL, pending[shard],
                            page_size=batch, fetch=True)
        pending[shard] = []
        # RETURNING gives us item_id AND seller_id AND category, so we never
        # have to assume the rows came back in the order we sent them.
        img_rows = []
        for item_id, seller_id, category in returned:
            items.append((item_id, seller_id, shard, category))
            pool = CATEGORIES[category]["images"]
            k = min(random.randint(1, 3), len(pool))
            for order, url in enumerate(random.sample(pool, k)):
                img_rows.append((item_id, url, order == 0, order,
                                 now - timedelta(days=random.randint(0, 90))))
        # Images go to the same shard as their item — that FK is kept.
        w.insert(shard, IMAGE_SQL, img_rows, page_size=batch)

    for _ in range(n_items):
        # 40% of listings come from the 5% power sellers.
        seller = (random.choice(power_sellers) if random.random() < 0.40
                  else random.choice(all_users))
        category = random.choice(CATEGORY_NAMES)
        cat = CATEGORIES[category]
        product = random.choice(cat["products"])
        condition = random.choice(CONDITIONS)
        city, state, zip_code = random.choice(LOCATIONS)
        lo, hi = cat["price"]
        price = round(random.uniform(lo, hi) * CONDITION_MULTIPLIER[condition], 2)
        created = now - timedelta(days=random.randint(1, 180),
                                  minutes=random.randint(0, 1439))
        views = random.randint(0, 5000)

        shard = w.shard_of(seller)
        pending[shard].append((
            seller, f"{product} — {condition.title()}",
            fake.paragraph(nb_sentences=3), category, price,
            city, state, zip_code, condition,
            views, random.randint(0, max(1, views // 10)),
            created, created + timedelta(days=random.randint(0, 10)),
            random.random() > 0.08,
        ))
        made += 1
        if len(pending[shard]) >= batch:
            flush(shard)
        if made % 5000 == 0:
            print(f"     {made:,}/{n_items:,} listings...")

    for shard in w.ring_names:
        flush(shard)

    print(f"   ✅ {len(items):,} listings written")
    for name in w.ring_names:
        cnt = sum(1 for it in items if it[2] == name)
        print(f"        {name:<8} {cnt:>8,}  ({cnt/max(1,len(items)):6.2%})")
    return items


INTERACTION_SQL = """
    INSERT INTO item_interactions
        (user_id, item_id, event_type, event_time, session_id)
    VALUES %s
"""


def seed_interactions(w: ShardWriter, all_users: list, item_ids: list,
                      n: int, batch: int) -> int:
    """
    An interaction is an event the ACTOR owns, so it is routed by
    interaction.user_id — never by item_id. Consequence: roughly half of
    these rows reference an item that lives on the other shard. That is
    expected and is precisely why item_interactions.item_id cannot keep its
    foreign key.
    """
    print(f"\n👁   Seeding {n:,} interactions (routed by actor)...")
    now = datetime.now()
    pending = {name: [] for name in w.ring_names}
    done = 0

    for i in range(n):
        actor = random.choice(all_users)
        shard = w.shard_of(actor)
        pending[shard].append((
            actor, random.choice(item_ids),
            random.choices(["view", "save", "click", "message"],
                           weights=[0.70, 0.15, 0.12, 0.03])[0],
            now - timedelta(days=random.randint(0, 60),
                            minutes=random.randint(0, 1439)),
            f"sess_{random.randint(1, 999999):06d}",
        ))
        done += 1
        if len(pending[shard]) >= batch:
            w.insert(shard, INTERACTION_SQL, pending[shard], page_size=batch)
            pending[shard] = []
        if done % 25000 == 0:
            print(f"     {done:,}/{n:,} interactions...")

    for shard in w.ring_names:
        w.insert(shard, INTERACTION_SQL, pending[shard], page_size=batch)
    print(f"   ✅ {done:,} interactions written")
    return done


SAVED_SQL = """
    INSERT INTO item_saved (user_id, item_id, saved_at)
    VALUES %s
    ON CONFLICT (user_id, item_id) DO NOTHING
"""


def seed_saves(w: ShardWriter, all_users: list, item_ids: list,
               n: int, batch: int) -> int:
    """
    Wishlist rows are owned by the saver, so they route by user_id. We
    dedupe (user_id, item_id) in memory as well as relying on ON CONFLICT,
    because a batched multi-row INSERT with a duplicate INSIDE the same
    statement is not protected by ON CONFLICT the way separate statements
    would be.
    """
    print(f"\n❤️   Seeding ~{n:,} saved items (routed by saver)...")
    now = datetime.now()
    pending = {name: [] for name in w.ring_names}
    seen = set()
    done = 0
    attempts = 0

    while done < n and attempts < n * 4:
        attempts += 1
        user = random.choice(all_users)
        item = random.choice(item_ids)
        if (user, item) in seen:
            continue
        seen.add((user, item))
        shard = w.shard_of(user)
        pending[shard].append((
            user, item,
            now - timedelta(days=random.randint(0, 60),
                            minutes=random.randint(0, 1439)),
        ))
        done += 1
        if len(pending[shard]) >= batch:
            w.insert(shard, SAVED_SQL, pending[shard], page_size=batch)
            pending[shard] = []

    for shard in w.ring_names:
        w.insert(shard, SAVED_SQL, pending[shard], page_size=batch)
    print(f"   ✅ {done:,} saved items written")
    return done


MESSAGE_SQL = """
    INSERT INTO marketplace_messages
        (sender_id, receiver_id, item_id, message_text, sent_at, is_read)
    VALUES %s
    RETURNING message_id, sender_id, receiver_id, item_id,
              message_text, sent_at, is_read
"""

# The replica insert names message_id explicitly. That is the whole trick:
# the receiver's shard must NOT mint a new id, or a fan-out read would see
# the same message twice under two different primary keys and no amount of
# deduping could fix it.
MESSAGE_REPLICA_SQL = """
    INSERT INTO marketplace_messages
        (message_id, sender_id, receiver_id, item_id, message_text,
         sent_at, is_read)
    VALUES %s
    ON CONFLICT (message_id) DO NOTHING
"""

OPENERS = [
    "Hi! Is this still available?",
    "Would you take {price} for it?",
    "Does it come with the original box and charger?",
    "Any scratches or dents I should know about?",
    "Can I pick it up this weekend?",
    "How long have you owned it?",
    "Is the battery health still good?",
    "Would you ship it, or local pickup only?",
    "Is the price negotiable at all?",
    "What's the reason for selling?",
]


def seed_messages(w: ShardWriter, all_users: list, items: list,
                  n: int, batch: int) -> tuple:
    """
    Buyer → seller conversations, dual-written when the two parties live on
    different shards.

    Sequence per conversation:
      1. INSERT on shard(sender) ... RETURNING the whole row. The sender's
         shard is the id authority for that message.
      2. If shard(receiver) != shard(sender), INSERT the SAME row —
         message_id included — on shard(receiver).

    Both copies are therefore identical, and any fan-out read dedupes on
    message_id. We count how many were cross-shard so the log makes the
    write amplification visible instead of hiding it.
    """
    print(f"\n💬  Seeding {n:,} messages (dual-written across shards)...")
    now = datetime.now()
    users_set = set(all_users)
    pending = {name: [] for name in w.ring_names}
    replicas = {name: [] for name in w.ring_names}
    originals = 0
    cross = 0

    def flush_originals(shard):
        nonlocal cross
        if not pending[shard]:
            return
        returned = w.insert(shard, MESSAGE_SQL, pending[shard],
                            page_size=batch, fetch=True)
        pending[shard] = []
        for row in returned:
            receiver_shard = w.shard_of(row[2])
            if receiver_shard != shard:
                replicas[receiver_shard].append(tuple(row))
                cross += 1

    for i in range(n):
        item_id, seller_id, _item_shard, _cat = random.choice(items)
        buyer = random.choice(all_users)
        if buyer == seller_id:
            # A seller messaging themselves is not a conversation.
            continue
        # Half the traffic is the seller replying, which exercises both
        # directions of the dual-write.
        if random.random() < 0.45:
            sender, receiver = seller_id, buyer
            body = random.choice([
                "Yes, still available — happy to meet up.",
                "I could do a bit better on price if you can collect today.",
                "It's in great shape, I have the receipt.",
                "Sorry, it's already spoken for.",
                "I can ship it tomorrow if you'd like.",
            ])
        else:
            sender, receiver = buyer, seller_id
            body = random.choice(OPENERS).format(
                price=f"${random.randint(20, 900)}")
        if sender not in users_set or receiver not in users_set:
            continue

        shard = w.shard_of(sender)
        pending[shard].append((
            sender, receiver, item_id, body,
            now - timedelta(days=random.randint(0, 45),
                            minutes=random.randint(0, 1439)),
            random.random() > 0.4,
        ))
        originals += 1
        if len(pending[shard]) >= batch:
            flush_originals(shard)
        if originals % 5000 == 0:
            print(f"     {originals:,}/{n:,} messages...")

    for shard in w.ring_names:
        flush_originals(shard)
    for shard in w.ring_names:
        w.insert(shard, MESSAGE_REPLICA_SQL, replicas[shard], page_size=batch)

    print(f"   ✅ {originals:,} logical messages, {cross:,} of them "
          f"cross-shard → {originals + cross:,} physical rows "
          f"({(originals + cross) / max(1, originals):.2f}x amplification)")
    return originals, cross


ACTIVITY_SQL = """
    INSERT INTO user_activity
        (user_id, item_id, activity_type, action, activity_metadata,
         session_id, ip_address, user_agent, created_at)
    VALUES %s
"""

ACTIVITY_TYPES = ["login", "logout", "view_item", "search", "save_item",
                  "send_message", "create_listing", "update_profile"]


def seed_activity(w: ShardWriter, all_users: list, item_ids: list,
                  n: int, batch: int) -> int:
    """Audit log rows belong to the acting user, so they route by user_id."""
    print(f"\n📊  Seeding {n:,} activity rows (routed by actor)...")
    now = datetime.now()
    pending = {name: [] for name in w.ring_names}
    done = 0

    for _ in range(n):
        actor = random.choice(all_users)
        act = random.choice(ACTIVITY_TYPES)
        item_needed = act in ("view_item", "save_item", "send_message",
                              "create_listing")
        shard = w.shard_of(actor)
        pending[shard].append((
            actor,
            random.choice(item_ids) if item_needed else None,
            act, act.replace("_", " ").title(),
            f'{{"shard":"{shard}"}}',
            f"sess_{random.randint(1, 999999):06d}",
            fake.ipv4(), fake.user_agent()[:500],
            now - timedelta(days=random.randint(0, 90),
                            minutes=random.randint(0, 1439)),
        ))
        done += 1
        if len(pending[shard]) >= batch:
            w.insert(shard, ACTIVITY_SQL, pending[shard], page_size=batch)
            pending[shard] = []
        if done % 25000 == 0:
            print(f"     {done:,}/{n:,} activity rows...")

    for shard in w.ring_names:
        w.insert(shard, ACTIVITY_SQL, pending[shard], page_size=batch)
    print(f"   ✅ {done:,} activity rows written")
    return done


# ────────────────────────────────────────────────────────────────────────── #
#  Summary                                                                   #
# ────────────────────────────────────────────────────────────────────────── #

def summary(w: ShardWriter) -> None:
    print("\n" + "=" * 68)
    print("  PER-SHARD ROW COUNTS")
    print("=" * 68)
    header = f"  {'table':<22}" + "".join(f"{n:>12}" for n in w.ring_names) \
             + f"{'total':>12}{'split':>16}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for table in ALL_TABLES:
        counts = {n: w.scalar(n, f"SELECT COUNT(*) FROM {table}")
                  for n in w.ring_names}
        total = sum(counts.values())
        split = " / ".join(f"{(counts[n]/total if total else 0):.1%}"
                           for n in w.ring_names)
        print(f"  {table:<22}"
              + "".join(f"{counts[n]:>12,}" for n in w.ring_names)
              + f"{total:>12,}{split:>16}")
    print("=" * 68)
    print(f"  🔑 Login: {DEMO_EMAIL} / {DEMO_PASSWORD} "
          f"(lives on {w.shard_of(DEMO_USER_ID)})")
    print("  ▶  Now run:  python3 verify_shards.py")
    print("=" * 68)


# ────────────────────────────────────────────────────────────────────────── #
#  Entry point                                                               #
# ────────────────────────────────────────────────────────────────────────── #

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Shard-aware seeder for ElectroHub. Every row is routed "
                    "through the real ConsistentHashRing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Env fallbacks so the same defaults work from a compose `command:`.
    p.add_argument("--users", type=int,
                   default=int(os.getenv("SEED_USERS", 5000)))
    p.add_argument("--listings", type=int,
                   default=int(os.getenv("SEED_LISTINGS", 25000)))
    p.add_argument("--interactions", type=int,
                   default=int(os.getenv("SEED_INTERACTIONS", 150000)))
    p.add_argument("--saves", type=int,
                   default=int(os.getenv("SEED_SAVES", 30000)))
    p.add_argument("--messages", type=int,
                   default=int(os.getenv("SEED_MESSAGES", 20000)))
    p.add_argument("--activity", type=int,
                   default=int(os.getenv("SEED_ACTIVITY", 60000)))
    p.add_argument("--batch-size", type=int,
                   default=int(os.getenv("SEED_BATCH", 5000)))
    p.add_argument("--seed", type=int, default=int(os.getenv("SEED_RNG", 1337)),
                   help="RNG seed; same value ⇒ same dataset")
    p.add_argument("--truncate", action="store_true",
                   help="wipe all seven tables on every shard first")
    p.add_argument("--keep-fks", action="store_true",
                   help="do NOT drop cross-shard FKs (cross-shard rows will "
                        "then fail — only useful to demonstrate why)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    random.seed(args.seed)
    Faker.seed(args.seed)

    print("=" * 68)
    print("  ElectroHub SHARD-AWARE SEEDER")
    print("  routing: ConsistentHashRing(replicas=150) via ShardManager")
    print("=" * 68)

    w = ShardWriter(ShardManager())
    started = time.time()
    try:
        preflight(w)
        if args.truncate:
            truncate_all(w)
        if args.keep_fks:
            print("\n⚠  --keep-fks: cross-shard FKs left in place. Any row "
                  "that references the other shard WILL fail.")
        else:
            drop_cross_shard_fks(w)
        interleave_sequences(w)

        users_by_shard = seed_users(w, args.users, args.batch_size)
        all_users = [u for lst in users_by_shard.values() for u in lst]
        if not all_users:
            raise SystemExit("❌  no users created — nothing to seed")

        items = seed_listings(w, all_users, args.listings, args.batch_size)
        if not items:
            raise SystemExit("❌  no listings created — nothing to reference")
        item_ids = [it[0] for it in items]

        seed_interactions(w, all_users, item_ids, args.interactions,
                          args.batch_size)
        seed_saves(w, all_users, item_ids, args.saves, args.batch_size)
        seed_messages(w, all_users, items, args.messages, args.batch_size)
        seed_activity(w, all_users, item_ids, args.activity, args.batch_size)

        summary(w)
        print(f"\n⏱  finished in {time.time() - started:.1f}s")
    finally:
        w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
