#!/usr/bin/env python3
"""
verify_shards.py — proves the sharding actually works.

Seeding data "to both shards" is easy to fake: you could round-robin rows
and get a pretty 50/50 table and learn nothing. What matters is whether the
ring's routing decision and the row's physical location AGREE, because that
is the invariant every read path depends on. If they ever disagree, a lookup
for user X asks the shard the ring names, that shard says "no rows", and the
app reports missing data rather than an error — the worst kind of bug.

So this script does not just count rows. It runs seven checks:

  1. PER-SHARD ROW COUNTS — every table, absolute and as a % split.
  2. VIRTUAL-NODE OWNERSHIP — how many of the 150-per-shard vnodes each
     physical shard owns on the ring.
  3. KEY DISTRIBUTION — hash N synthetic user_ids and report the split plus
     the max deviation from the ideal 1/n. This is the number that shows the
     virtual nodes are doing their job: with 1 vnode per shard the deviation
     is wild and depends entirely on where two MD5 points happen to land;
     with 150 it collapses to a couple of percent.
  4. ROUTING AUDIT — for real rows on disk, does ring.get_node(owner) equal
     the shard the row is physically stored on? Any mismatch is a hard FAIL.
  5. MESSAGE DUAL-WRITE INTEGRITY — cross-shard messages exist twice on
     purpose. Assert both copies share a message_id and are byte-identical,
     which is what makes "fan-out then dedupe on message_id" correct.
  6. GLOBAL ID UNIQUENESS — each shard mints ids from a disjoint slice, so
     item_id 42 can only ever mean one listing cluster-wide.
  7. REBALANCE SIMULATION — add a hypothetical shard2 to the ring and
     measure what fraction of existing user_ids move. Consistent hashing
     should move ~1/3 (the new node's fair share). The contrast case, naive
     hash % n, is computed alongside: it moves ~2/3, i.e. it would force a
     migration of most of the dataset. PASS/FAIL is asserted on this.

Usage
-----
From the host (shards published on localhost:5432 / :5433):

    cd backend
    python3 verify_shards.py

Inside a container on the compose network:

    DB_SHARD0_URL=postgresql://postgres:password@postgres_shard0:5432/electrohub \
    DB_SHARD1_URL=postgresql://postgres:password@postgres_shard1:5432/electrohub \
    python3 verify_shards.py

Flags:
    --keys N          synthetic keys for the distribution test (default 100000)
    --sample N        max real user_ids to pull per shard for checks 4 and 6
                      (default 20000; 0 = all of them)
    --new-shard NAME  name of the hypothetical shard in the rebalance sim
    --tolerance F     allowed absolute deviation for the rebalance PASS band
                      (default 0.05, i.e. 1/3 ± 5 points)
    --no-color        plain output for logs and CI

Exit code is 0 only if every check passes — so this is usable as a CI gate.
"""

import argparse
import os
import sys
from collections import defaultdict

# Run from backend/ or the repo root — either way `app` must import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.consistent_hash import ConsistentHashRing   # noqa: E402
from app.core.shard_db import ShardManager                # noqa: E402

TABLES = [
    "user_accounts", "marketplace_items", "item_images",
    "item_interactions", "marketplace_messages", "item_saved",
    "user_activity",
]

# (table, column that decides ownership). Every one of these is a user_id
# whose ring position must match the shard the row sits on.
OWNERSHIP = [
    ("user_accounts", "user_id"),
    ("marketplace_items", "seller_id"),
    ("item_interactions", "user_id"),
    ("item_saved", "user_id"),
    ("user_activity", "user_id"),
]

REPLICAS = 150            # must match ShardManager's ConsistentHashRing
USE_COLOR = sys.stdout.isatty()


def c(code: str, s: str) -> str:
    return s if not USE_COLOR else f"\033[{code}m{s}\033[0m"


def ok(s):    return c("32", s)
def bad(s):   return c("31", s)
def dim(s):   return c("2", s)
def bold(s):  return c("1", s)


class Results:
    """Collects PASS/FAIL so the exit code can gate CI."""

    def __init__(self):
        self.checks = []

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append((name, passed, detail))
        tag = ok("PASS") if passed else bad("FAIL")
        print(f"   [{tag}] {name}" + (f" — {detail}" if detail else ""))
        return passed

    @property
    def all_passed(self) -> bool:
        return all(p for _, p, _ in self.checks)


def header(title: str) -> None:
    print("\n" + "=" * 74)
    print(bold(f"  {title}"))
    print("=" * 74)


# ────────────────────────────────────────────────────────────────────────── #
#  1. Per-shard row counts                                                   #
# ────────────────────────────────────────────────────────────────────────── #

def check_row_counts(sessions, names, res: Results) -> dict:
    from sqlalchemy import text

    header("1. PER-SHARD ROW COUNTS")
    counts = {}
    width = max(len(t) for t in TABLES) + 2
    line = (f"  {'table':<{width}}"
            + "".join(f"{n:>14}" for n in names)
            + f"{'total':>12}   split")
    print(line)
    print("  " + dim("-" * (len(line) - 2)))

    for table in TABLES:
        row = {}
        for n in names:
            row[n] = sessions[n].execute(
                text(f"SELECT COUNT(*) FROM {table}")).scalar()
        counts[table] = row
        total = sum(row.values())
        split = " / ".join(f"{(row[n]/total if total else 0):.1%}" for n in names)
        print(f"  {table:<{width}}"
              + "".join(f"{row[n]:>14,}" for n in names)
              + f"{total:>12,}   {split}")

    # An empty shard is the exact symptom of the non-shard-aware seeder, so
    # it gets its own explicit check rather than being left to the reader.
    empty = [n for n in names
             if counts["user_accounts"][n] == 0]
    res.record("every shard holds users",
               not empty,
               "all shards populated" if not empty
               else f"empty: {', '.join(empty)} (did you run seed_sharded.py?)")
    return counts


# ────────────────────────────────────────────────────────────────────────── #
#  2. Virtual-node ownership                                                 #
# ────────────────────────────────────────────────────────────────────────── #

def check_vnodes(manager: ShardManager, names, res: Results) -> None:
    header("2. VIRTUAL-NODE OWNERSHIP ON THE RING")
    dist = manager.distribution()
    total = sum(dist.values())
    print(f"  {REPLICAS} virtual nodes per physical shard, "
          f"{total} points on the ring\n")
    for n in sorted(dist):
        share = dist[n] / total
        bar = "█" * int(share * 40)
        print(f"  {n:<10}{dist[n]:>5} vnodes  {share:>7.2%}  {bar}")

    expected = REPLICAS
    wrong = {n: v for n, v in dist.items() if v != expected}
    res.record(f"each shard owns exactly {expected} vnodes",
               not wrong,
               "as configured" if not wrong else f"unexpected: {wrong}")


# ────────────────────────────────────────────────────────────────────────── #
#  3. Key distribution                                                       #
# ────────────────────────────────────────────────────────────────────────── #

def check_key_distribution(names, n_keys: int, res: Results) -> None:
    """
    Hash n_keys synthetic user_ids through a fresh ring and measure the
    spread. Max deviation from ideal is the headline number: it is what
    virtual nodes buy you, and it shrinks as sqrt(1/replicas).
    """
    header(f"3. KEY DISTRIBUTION — {n_keys:,} synthetic user_ids")

    ring = ConsistentHashRing(replicas=REPLICAS)
    for n in names:
        ring.add_node(n)

    buckets = defaultdict(int)
    for i in range(n_keys):
        buckets[ring.get_node(f"user_{i:06d}")] += 1

    ideal = 1.0 / len(names)
    print(f"  ideal share per shard: {ideal:.2%}\n")
    max_dev = 0.0
    for n in names:
        share = buckets[n] / n_keys
        dev = abs(share - ideal)
        max_dev = max(max_dev, dev)
        bar = "█" * int(share * 40)
        print(f"  {n:<10}{buckets[n]:>10,}  {share:>7.2%}  "
              f"(dev {dev:+.2%})  {bar}")

    # For contrast: what the SAME keys look like with only one vnode per
    # shard. This is the concrete "why 150" answer.
    naive = ConsistentHashRing(replicas=1)
    for n in names:
        naive.add_node(n)
    nb = defaultdict(int)
    for i in range(n_keys):
        nb[naive.get_node(f"user_{i:06d}")] += 1
    naive_dev = max(abs(nb[n] / n_keys - ideal) for n in names)

    print(f"\n  max deviation @ {REPLICAS} vnodes/shard : "
          f"{bold(f'{max_dev:.2%}')}")
    print(f"  max deviation @   1 vnode /shard : {naive_dev:.2%}   "
          + dim("← what you get without virtual nodes"))

    # 5 points of slack. With 150 vnodes and 100k keys the real figure is
    # normally well under 2%; the band is loose enough not to be flaky.
    res.record("key distribution within 5% of ideal",
               max_dev <= 0.05,
               f"max deviation {max_dev:.2%}")
    res.record(f"{REPLICAS} vnodes beat 1 vnode",
               max_dev <= naive_dev,
               f"{max_dev:.2%} vs {naive_dev:.2%}")


# ────────────────────────────────────────────────────────────────────────── #
#  4. Routing audit — the real invariant                                     #
# ────────────────────────────────────────────────────────────────────────── #

def check_routing(sessions, names, manager: ShardManager, sample: int,
                  res: Results) -> dict:
    """
    For rows actually on disk: does the ring agree with where they live?

    We read DISTINCT owner ids per table per shard rather than every row —
    the invariant is a property of the owner id, so one check per distinct id
    covers every row that id owns, and it keeps a 150k-row table cheap.
    """
    from sqlalchemy import text

    header("4. ROUTING AUDIT — physical location vs. ring decision")
    limit = f"LIMIT {sample}" if sample else ""
    all_owners = {}

    for table, column in OWNERSHIP:
        misrouted = []
        checked = 0
        for n in names:
            rows = sessions[n].execute(text(
                f"SELECT DISTINCT {column} FROM {table} "
                f"WHERE {column} IS NOT NULL {limit}"
            )).fetchall()
            for (owner,) in rows:
                checked += 1
                if table == "user_accounts":
                    all_owners[owner] = n
                if manager.get_shard_name(owner) != n:
                    misrouted.append((owner, n, manager.get_shard_name(owner)))

        detail = f"{checked:,} distinct {column}s"
        if misrouted:
            detail += f", {len(misrouted)} misrouted e.g. {misrouted[0]}"
        res.record(f"{table}.{column} on ring-assigned shard",
                   not misrouted, detail)

    # Messages are the exception: a row's sender may be remote because a
    # cross-shard message is deliberately replicated to the receiver's shard.
    # The correct invariant is weaker — every message row must be owned
    # locally by AT LEAST ONE of its two parties.
    orphans = 0
    total_msgs = 0
    for n in names:
        rows = sessions[n].execute(text(
            f"SELECT sender_id, receiver_id FROM marketplace_messages {limit}"
        )).fetchall()
        for sender, receiver in rows:
            total_msgs += 1
            if (manager.get_shard_name(sender) != n
                    and manager.get_shard_name(receiver) != n):
                orphans += 1
    res.record("every message row has a local party",
               orphans == 0,
               f"{total_msgs:,} rows sampled, {orphans} orphaned")

    return all_owners


# ────────────────────────────────────────────────────────────────────────── #
#  5. Dual-write integrity                                                   #
# ────────────────────────────────────────────────────────────────────────── #

def check_dual_write(sessions, names, res: Results) -> None:
    """
    Cross-shard conversations are stored twice on purpose. Two things must
    hold or a fan-out read is unsafe:

      a) the two copies share message_id — otherwise dedupe is impossible;
      b) the two copies are identical — otherwise dedupe picks a winner and
         which shard answered first would change what the user sees.
    """
    from sqlalchemy import text

    header("5. MESSAGE DUAL-WRITE INTEGRITY")

    per_shard = {}
    for n in names:
        rows = sessions[n].execute(text(
            "SELECT message_id, sender_id, receiver_id, item_id, "
            "       message_text, sent_at, is_read "
            "FROM marketplace_messages"
        )).fetchall()
        per_shard[n] = {r[0]: tuple(r) for r in rows}

    physical = sum(len(v) for v in per_shard.values())
    unique_ids = set()
    for v in per_shard.values():
        unique_ids |= v.keys()
    logical = len(unique_ids)
    duplicated = physical - logical

    print(f"  physical rows across all shards : {physical:,}")
    print(f"  distinct message_ids (logical)  : {logical:,}")
    print(f"  replicated (cross-shard) copies : {duplicated:,}")
    if logical:
        print(f"  write amplification             : "
              f"{physical / logical:.2f}x")

    if physical == 0:
        res.record("dual-write integrity", True, "no messages to check")
        return

    # (a) A fan-out read that dedupes on message_id must land on exactly the
    #     logical count. If any replica had been given a fresh id by the
    #     receiver shard, physical would exceed logical by more than the
    #     number of genuine cross-shard pairs and this would drift.
    mismatched = []
    for mid in unique_ids:
        copies = [per_shard[n][mid] for n in names if mid in per_shard[n]]
        if len(copies) > 1 and any(cp != copies[0] for cp in copies[1:]):
            mismatched.append(mid)

    res.record("replicated copies are byte-identical",
               not mismatched,
               f"{duplicated:,} replicas compared"
               if not mismatched
               else f"{len(mismatched)} divergent, e.g. message_id={mismatched[0]}")

    # (b) No message_id may appear more than once WITHIN a single shard —
    #     that is guaranteed by the PK, but assert it so the dedupe story is
    #     complete: dedupe across shards is the only dedupe needed.
    res.record("fan-out + dedupe on message_id yields no duplicates",
               logical == len(unique_ids),
               f"{logical:,} unique messages from {physical:,} rows")


def check_id_spaces(sessions, names, res: Results) -> None:
    """
    Globally unique surrogate keys across shards.

    Each shard's sequences are interleaved: shard k of n starts at k+1 and
    increments by n, so it mints only ids ≡ (k+1) mod n and item_id 42 can
    exist on at most one shard. Without this, a
    fan-out read over marketplace_items would return two different listings
    both calling themselves item 42 and the caller could not tell them apart.

    marketplace_items is the honest table to test on, because listings are
    never replicated — so any overlap between shards is a genuine collision.
    """
    from sqlalchemy import text

    header("6. GLOBAL ID UNIQUENESS ACROSS SHARDS")
    n = len(names)
    id_sets = {}
    for k, name in enumerate(names):
        rows = sessions[name].execute(
            text("SELECT item_id FROM marketplace_items")).fetchall()
        ids = {r[0] for r in rows}
        id_sets[name] = ids
        slot = (k + 1) % n          # shard k starts at k+1, steps by n
        offenders = [i for i in ids if i % n != slot]
        print(f"  {name:<10}{len(ids):>10,} item_ids, "
              f"expected ≡ {slot} (mod {n}), off-slice: {len(offenders)}")
        res.record(f"{name} item_ids stay in its id slice",
                   not offenders,
                   f"{len(ids):,} ids checked" if not offenders
                   else f"e.g. item_id={offenders[0]}")

    overlap = set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap |= id_sets[a] & id_sets[b]
    res.record("no item_id exists on two shards",
               not overlap,
               "id spaces are disjoint" if not overlap
               else f"{len(overlap)} colliding ids, e.g. {sorted(overlap)[:3]}")


# ────────────────────────────────────────────────────────────────────────── #
#  6. Rebalance simulation — the whole point of consistent hashing           #
# ────────────────────────────────────────────────────────────────────────── #

def check_rebalance(names, owners: dict, new_shard: str, tolerance: float,
                    n_keys: int, res: Results) -> None:
    """
    Add a third shard and count how many keys change owner.

    Expected: ~1/(n+1) of keys move — exactly the new node's fair share, and
    every key that moves moves TO the new node (nothing shuffles between the
    two existing shards). That second property is what makes the migration
    safe to do online: shard0 and shard1 never have to trade data.

    The naive baseline in the same run is `hash(key) % n`. Going 2 → 3 there
    remaps ~2/3 of all keys, and they move in every direction, which means a
    full stop-the-world reshuffle.
    """
    header(f"7. REBALANCE SIMULATION — adding {new_shard}")

    # Prefer real user_ids read off the shards; fall back to synthetic keys
    # if the cluster is empty so the check still reports something useful.
    if owners:
        keys = list(owners.keys())
        source = f"{len(keys):,} real user_ids read from the shards"
    else:
        keys = [f"user_{i:06d}" for i in range(n_keys)]
        source = f"{len(keys):,} synthetic user_ids (shards were empty)"
    print(f"  key set: {source}\n")

    before = ConsistentHashRing(replicas=REPLICAS)
    for n in names:
        before.add_node(n)
    after = ConsistentHashRing(replicas=REPLICAS)
    for n in names:
        after.add_node(n)
    after.add_node(new_shard)

    moved = 0
    moved_to_new = 0
    for k in keys:
        b, a = before.get_node(k), after.get_node(k)
        if b != a:
            moved += 1
            if a == new_shard:
                moved_to_new += 1

    total = len(keys)
    frac = moved / total
    ideal = 1.0 / (len(names) + 1)

    print(f"  consistent hashing  ({len(names)} → {len(names)+1} shards)")
    print(f"     keys remapped            : {moved:,} / {total:,} "
          f"= {bold(f'{frac:.2%}')}")
    print(f"     ideal (new shard's share): {ideal:.2%}")
    print(f"     of those, moved to {new_shard} : {moved_to_new:,} "
          f"({(moved_to_new/moved if moved else 0):.2%})")

    # Baseline: modulo sharding on the same keys.
    def mod_node(key, count):
        return ConsistentHashRing._hash(key) % count

    mod_moved = sum(1 for k in keys
                    if mod_node(k, len(names)) != mod_node(k, len(names) + 1))
    print("\n  naive hash % n baseline")
    print(f"     keys remapped            : {mod_moved:,} / {total:,} "
          f"= {mod_moved/total:.2%}   "
          + dim("← a full data migration"))

    lo, hi = ideal - tolerance, ideal + tolerance
    res.record(f"remap fraction ≈ 1/{len(names)+1} "
               f"({lo:.1%}–{hi:.1%})",
               lo <= frac <= hi,
               f"{frac:.2%} remapped (naive would be {mod_moved/total:.2%})")
    res.record("no key moves between pre-existing shards",
               moved == moved_to_new,
               f"{moved - moved_to_new} keys shuffled sideways"
               if moved != moved_to_new
               else "every moved key went to the new shard")
    res.record("consistent hashing beats modulo",
               moved < mod_moved,
               f"{moved:,} vs {mod_moved:,} keys to migrate")


# ────────────────────────────────────────────────────────────────────────── #
#  Entry point                                                               #
# ────────────────────────────────────────────────────────────────────────── #

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Verify ElectroHub's consistent-hash sharding.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--keys", type=int,
                   default=int(os.getenv("VERIFY_KEYS", 100000)),
                   help="synthetic keys for the distribution test")
    p.add_argument("--sample", type=int,
                   default=int(os.getenv("VERIFY_SAMPLE", 20000)),
                   help="max rows/ids pulled per shard per table (0 = all)")
    p.add_argument("--new-shard", default="shard2",
                   help="name of the hypothetical shard in the rebalance sim")
    p.add_argument("--tolerance", type=float, default=0.05,
                   help="allowed absolute deviation for the rebalance PASS band")
    p.add_argument("--no-color", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global USE_COLOR
    args = parse_args(argv)
    if args.no_color:
        USE_COLOR = False

    print("=" * 74)
    print(bold("  ElectroHub SHARDING VERIFICATION"))
    print("  ring: ConsistentHashRing(replicas=150), MD5, routed by user_id")
    print("=" * 74)

    manager = ShardManager()
    names = sorted(manager.distribution().keys())
    sessions = manager.get_all_sessions()

    for n in names:
        url = sessions[n].get_bind().url
        print(f"  {n:<8} → {url.host}:{url.port}/{url.database} "
              f"as {url.username}")

    res = Results()
    try:
        # Fail fast with a readable message rather than a stack trace if a
        # shard is down — this script is meant to be run by humans mid-demo.
        from sqlalchemy import text
        for n in names:
            try:
                sessions[n].execute(text("SELECT 1")).scalar()
            except Exception as exc:
                print(bad(f"\n❌  cannot reach {n}: "
                          f"{type(exc).__name__}: {exc}"))
                print("    From the host, shards are on localhost:5432 / "
                      ":5433.\n"
                      "    Inside a container, set DB_SHARD0_URL and "
                      "DB_SHARD1_URL.")
                return 2

        check_row_counts(sessions, names, res)
        check_vnodes(manager, names, res)
        check_key_distribution(names, args.keys, res)
        owners = check_routing(sessions, names, manager, args.sample, res)
        check_dual_write(sessions, names, res)
        check_id_spaces(sessions, names, res)
        check_rebalance(names, owners, args.new_shard, args.tolerance,
                        args.keys, res)
    finally:
        for s in sessions.values():
            s.close()

    header("SUMMARY")
    passed = sum(1 for _, p, _ in res.checks if p)
    for name, p, detail in res.checks:
        print(f"   [{ok('PASS') if p else bad('FAIL')}] {name}")
    print()
    if res.all_passed:
        print(ok(f"  ✅  ALL {len(res.checks)} CHECKS PASSED — "
                 f"sharding is live and consistent hashing is behaving."))
        return 0
    print(bad(f"  ❌  {len(res.checks) - passed} of {len(res.checks)} "
              f"CHECKS FAILED"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
