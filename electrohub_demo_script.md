# ElectroHub Demo Video — Script & Navigation Guide

Everything technical claim in this script was verified directly against the source code in this repo (not just the README). Where the README oversells something that isn't actually wired up, it's flagged in **⚠️ Accuracy Note** boxes — don't repeat those claims on camera.

Estimated total runtime: **9–11 minutes** (12 segments, Segment 2.5 on the sharding design is optional).

---

## Before you hit record

**Have running:**
- Full docker-compose stack (`docker compose ps` — all healthy)
- Frontend dev server (`npm start` in `frontend/`) on `localhost:3000`

**Have open, in two separate browser windows (not just tabs — see note below):**
- Window A: logged in as **buyer** — `demo@electrohub.com` / `password123`
- Window B: logged in as **seller** — `user_000087@example.com` / `password123` (Margaret Griffin, sells item #110 — PS5)

⚠️ Use two different browser *profiles* or one regular + one incognito window. Both accounts share the same origin (`localhost:3000`), so logging into both in plain tabs of the same browser will overwrite each other's token in `localStorage`.

**Optional extra tabs** if you want to show observability at the end:
- `localhost:3001` — Grafana (admin/admin)
- `localhost:15672` — RabbitMQ management UI (guest/guest)

---

## Segment 1 — Intro (30s)

**Say:**
> "This is ElectroHub — a peer-to-peer electronics marketplace I built to demonstrate a real microservices architecture. It's not one app — it's six independent backend services, two databases, a message queue, an event stream, and a caching layer, all fronted by a single API gateway. I'm going to walk through the app as a user, and at each step explain the distributed systems concept behind what just happened on screen."

**Show:** Home page, browser at `localhost:3000`.

---

## Segment 2 — Architecture overview (60s)

**Say, while showing the architecture diagram from the README or just narrating:**
> "Under the hood there are six FastAPI microservices: user-service handles auth, listing-service handles the marketplace catalog and wishlist, messaging-service handles real-time chat, activity-service and notification-service handle logging and notifications, and recommendation-service runs a machine learning model for 'similar items.' They don't talk to each other directly over HTTP for internal calls — two of them expose gRPC servers for fast, typed service-to-service communication. Everything the browser talks to goes through a single Nginx gateway on port 80, which does routing, rate limiting, and WebSocket proxying."

**Technical grounding (for your own reference, don't need to read verbatim):**
- Services: `user-service` (8001), `listing-service` (8002), `messaging-service` (8003), `activity-service` (8004), `recommendation-service` (8005), `notification-service` (internal only)
- Data layer: 2× PostgreSQL, Redis, Kafka, RabbitMQ
- Gateway: `nginx/nginx.conf` — single entry point on port 80

⚠️ **Accuracy note:** docker-compose provisions **two** Postgres containers (`postgres_shard0`, `postgres_shard1`), but every service's `DB_HOST` env var points only at `postgres_shard0`. `shard1` is running, healthy, and schema-complete — but completely empty, zero rows in any table. There's a real sharding design in the codebase (see Segment 2.5 below), it's just not wired into the live services. Don't say "the app shards data" — say what Segment 2.5 gives you to say instead.

---

## Segment 2.5 — The sharding design (designed, not live) (60–75s)

This is optional, but it's a stronger thing to show than pretending sharding is live. Frame it explicitly as a design decision you made and a real problem you identified — not a bug, not vaporware.

**Navigate:** Optionally have `backend/app/core/consistent_hash.py` open in an editor. Nothing to click in the running app for this one.

**Say:**
> "I also designed a data-sharding layer for this project, even though I didn't wire it into the live services — and I want to walk through why, because the reason is more interesting than the implementation. The idea is a consistent-hash ring: each of the two Postgres shards gets 150 virtual points scattered around a hash circle, and a user's data is routed to whichever shard owns the nearest point clockwise from that user's hashed ID. The reason for virtual nodes instead of just splitting the circle in half is scaling — with a plain half-and-half split, adding a third shard forces you to reshuffle almost all your data, because the split points move. With virtual nodes scattered around the ring, adding a shard only remaps about one out of every N keys — the rest stay exactly where they are."

**Say (the honest part):**
> "But I didn't turn it on, because it exposes a real distributed-systems problem: this ring routes by user ID, but login happens by email. You don't know a user's ID — the thing you need to pick the shard — until after you've already found the user, which is the thing you were trying to do. So actually wiring this in means either querying both shards on every login, a scatter-gather, or maintaining a separate unsharded index just to map email to user ID and shard. Both are legitimate, both add real complexity, and I'd rather show I understand that tradeoff than ship something half-working right before a demo."

**Technical grounding:**
- `backend/app/core/consistent_hash.py` — MD5-based ring, 150 virtual nodes per shard, `get_node(key)` walks clockwise to the nearest node
- `backend/app/core/shard_db.py` — `ShardManager.get_session(user_id)` — the intended live entry point, never called by any running service
- This code lives in `backend/app/`, which docker-compose never builds — confirmed only `backend/seed_all.py` is mounted anywhere in `docker-compose.yml`

---

## Segment 3 — Login & JWT tokenization (90s)

🔑 **Login now:** Window A, go to `/login`. Credentials: **`demo@electrohub.com` / `password123`** (this is your buyer account for the rest of the video — stays logged in through Segments 4–8).

**Navigate:** Window A, log in with the credentials above. Open DevTools → Application → Local Storage before/during login to show the token land.

**Say:**
> "When I log in, `user-service` checks the password and, if it matches, issues a JSON Web Token — a JWT. This token has three parts: a header, a payload containing the user ID and an expiry timestamp, and a signature. It's signed with HS256 using a shared secret — so any service that knows the secret can verify the token is authentic without calling back to user-service over the network for every single request. That's the core trick of stateless auth in a microservices system: the token itself carries proof of identity."

**Show:** the token in `localStorage` under key `token`. Optionally paste it into jwt.io (locally decode only, don't submit anywhere sensitive) to show the decoded `sub` (user id) and `exp` claims.

> "The frontend's Axios client reads this token out of localStorage and attaches it as a `Bearer` header on every API call automatically — so I only have to log in once, and every request after that is authenticated."

**Technical grounding:**
- `services/user-service/app/core/security.py` — `python-jose`, algorithm `HS256`, 24-hour expiry, payload is just `{"sub": user_id, "exp": ...}`
- Password check: `hashlib.sha256` comparison (see accuracy note below)
- Token injection: `frontend/src/services/api.js` sets `Authorization: Bearer <token>` on the shared Axios instance

⚠️ **Accuracy note:** the README says password hashing uses **bcrypt**. The actual code (`security.py`) uses plain **unsalted SHA-256** via `hashlib`. Functionally the login still works fine for a demo, but don't say "bcrypt" on camera — say "hashed" or specifically "SHA-256" if asked. This is a real security weakness (no salt, fast hash) worth mentioning only if you want to show you can spot it, not something to present as a strength.

---

## Segment 4 — Browsing, search, and the gRPC internal call (60s)

**Navigate:** Home page — show category pills, search bar, the three rows (Trending Now / Most Saved / New Arrivals).

**Say:**
> "Browsing hits listing-service, which owns the marketplace_items table. Notice how fast navigating back to Home is after the first load — that's a five-minute client-side cache in the React app, so we're not re-fetching 500 listings every time you click back."

**Click into an item** (e.g. `/item/1`).

**Say:**
> "Opening an item does something interesting on the backend: listing-service needs to confirm I'm a logged-in user before it lets me act on this listing, but it doesn't have its own user table — it asks user-service directly over gRPC, a binary, strongly-typed RPC protocol, instead of a slower JSON-over-HTTP call. That gRPC port isn't even exposed outside the Docker network — it's purely internal service-to-service traffic."

**Technical grounding:**
- `services/user-service/app/grpc/servicer.py` — exposes `VerifyToken` and `GetUser`
- `listing-service` and `messaging-service` both call `VerifyToken` via gRPC client stubs
- gRPC ports (50051/50052) are declared internal-only in `docker-compose.yml` — not published to the host

---

## Segment 5 — AI Recommendations (SBERT) (60s)

**Navigate:** Scroll down on the item detail page to "Similar Listings."

**Say:**
> "Below the listing is a recommendations panel powered by an actual sentence embedding model — SBERT, specifically `all-MiniLM-L6-v2`. On startup, recommendation-service pulls every active listing, builds a text string from the title, category, condition, and description, and encodes it into a 384-dimensional vector. When you open an item, the service takes that item's vector and computes a dot product against every other vector in memory — since they're normalized, that's mathematically equivalent to cosine similarity — and returns the closest matches. This isn't category matching, it's semantic similarity — it understands that a 'like new iPhone 14' and a 'excellent condition iPhone 14' are close in meaning even with different wording."

**Technical grounding:**
- `services/recommendation-service/app/main.py` — loads `SentenceTransformer("all-MiniLM-L6-v2")` at startup, builds embedding matrix once, serves top-N via dot product

---

## Segment 6 — Wishlist & Redis (45s)

**Navigate:** Still Window A (`demo@electrohub.com` — no new login needed). Click the heart/save icon on an item. Go to `/saved`.

**Say:**
> "Saving an item writes to two places: a Redis SET called `wishlist:{user_id}` for instant O(1) reads and writes, and a Postgres row for durability. Redis is the fast path the app actually reads from; Postgres is the source of truth. If Redis ever restarted and lost its data, the very next request would rebuild that user's set straight from Postgres — so the cache is self-healing."

**Technical grounding:**
- `services/listing-service` — `SADD wishlist:{uid}`, `SREM`, `SISMEMBER`, `SMEMBERS`; dual-write to `item_saved` Postgres table

---

## Segment 7 — Real-time chat: WebSockets, Redis Pub/Sub, Kafka, RabbitMQ (2 min — the core segment)

🔑 **Login now (if not already):** Window B — go to `/login`, credentials: **`user_000087@example.com` / `password123`** (Margaret Griffin — seller account, owns item #110). Do this in a *separate browser window/profile or incognito*, not a second tab of Window A — same-origin tabs share `localStorage` and logging in here would silently log Window A out. Keep Window A on `demo@electrohub.com` throughout.

**Navigate:** Window A (buyer, still logged in as `demo@electrohub.com`) — open item #110 (Margaret Griffin's PS5), click "Message Seller," send: *"Hi, is this still available?"*

**Say while sending:**
> "This opens a WebSocket connection to messaging-service, authenticated with the same JWT — passed as a query parameter since browsers can't set custom headers on a WebSocket handshake. messaging-service verifies that token the same way listing-service did: a gRPC call back to user-service."

**Switch to Window B (seller, `user_000087@example.com`)**, open Inbox, show the message arriving.

**Say:**
> "Now here's the interesting part. In production you wouldn't run one messaging-service instance — you'd run several behind a load balancer, and the buyer and seller could easily be connected to two different instances. If instance A only holds the buyer's socket in memory, how does instance B — holding the seller's socket — find out a message was sent? The answer here is Redis Pub/Sub. Every message gets published to a Redis channel keyed by the conversation ID, and every messaging-service instance subscribes to it. Whichever instance is actually holding the recipient's socket delivers it. That's what makes this horizontally scalable instead of a single point of failure."

**Continue:**
> "After every message is persisted to Postgres — the source of truth — two more things happen, and they're deliberately different patterns. First, an event is published to Kafka on the topic `electrohub.message.sent` — that's fire-and-forget, meant to feed an analytics pipeline; if Kafka is down, the message still sends, it just doesn't get logged for analytics. Second, a job is published to RabbitMQ on a durable queue — that's the opposite guarantee: RabbitMQ persists the job, and if notification-service crashes mid-processing, the job gets nacked and redelivered until it's handled. That's the textbook difference between an event stream and a task queue: Kafka is 'broadcast and move on,' RabbitMQ is 'guarantee exactly this gets done.'"

**Technical grounding:**
- `services/messaging-service/app/core/connection_manager.py` — WebSocket connection manager + Redis Pub/Sub fan-out (`electrohub:chat:{conv_id}` channel)
- `services/messaging-service/app/api/messages.py` — after every message: Postgres write → Redis publish → Kafka publish (`message_sent`) → RabbitMQ publish (`message_received` job)
- `services/notification-service/app/handlers/rabbitmq_consumer.py` — durable queue `electrohub.notifications`, `ack`/`nack`-with-requeue on failure, explicitly documented as "one job processed by exactly one worker, easy to scale with more replicas"

⚠️ **Accuracy note (important — don't overstate this on camera):** Kafka events *are* genuinely published (`electrohub.item.viewed`, `electrohub.message.sent`, etc.) by `listing-service` and `messaging-service`. But **nothing in this repo currently consumes them** — there's no Kafka consumer group anywhere in `services/`. The README describes `activity-service` as "a Kafka consumer," but the real `activity-service` code is a plain REST API (`/activity/track`) that writes straight to Postgres via HTTP — and nothing in the frontend even calls it. So say "Kafka events are published for a future analytics pipeline" — not "and then the analytics service processes them," because right now nothing does. If you want that claim to be literally true on camera, that's a real gap you could fix before recording (add a minimal consumer), otherwise just describe it accurately as future-facing.

---

## Segment 8 — Inbox & notification bell (30s)

**Navigate:** Window A, look at the navbar unread badge.

**Say:**
> "The navbar polls unread count every 30 seconds — a simple mechanism, but combined with the WebSocket push for open conversations, you get both real-time delivery while you're actively chatting and eventual consistency for the badge count everywhere else in the app."

---

## Segment 9 — API Gateway & rate limiting (45s)

**Navigate:** Open `nginx/nginx.conf` in an editor, or just narrate.

**Say:**
> "Every request from the browser goes through Nginx, acting as an API gateway. It does three things: routes by path prefix to the right backend service, enforces per-IP rate limits using token bucket zones — five login attempts a minute to blunt brute-force attacks, sixty browse requests a minute for normal use — and proxies WebSocket upgrade requests through to messaging-service with long timeouts so chat connections don't get dropped."

**Technical grounding:**
- `nginx/nginx.conf` — `api_login` (5r/min), `api_browse` (60r/min), `api_general` (30r/min) zones; `/messages/ws/` location handles the `Upgrade`/`Connection` headers for WebSocket

---

## Segment 10 — Observability (optional, 45s)

**Navigate:** `localhost:3001` Grafana, `localhost:15672` RabbitMQ management.

**Say:**
> "Prometheus scrapes metrics from the services, Grafana visualizes them, and RabbitMQ's own management UI lets you watch the notification queue directly — you can see jobs land and get consumed in real time."

---

## Segment 11 — Wrap-up (30s)

**Say:**
> "So in one small demo app, we've actually touched most of the core distributed systems patterns: stateless JWT auth so services don't need shared session state, an API gateway for a single client-facing entry point, gRPC for fast internal service calls, Redis for both caching and pub/sub fan-out across horizontally scaled instances, an event stream versus a durable task queue as two different asynchronous messaging guarantees, and a semantic search feature running real ML inference. It's a small app, but it's built the way a much bigger system would actually be structured."

---

## Quick reference — credentials & IDs used in this script

| Role | Email | Password | Notes |
|---|---|---|---|
| Buyer | `demo@electrohub.com` | `password123` | Fixed demo account |
| Seller | `user_000087@example.com` | `password123` | Margaret Griffin, owns items #110, #258, #457, #453 |

| URL | Purpose |
|---|---|
| `localhost:3000` | Frontend |
| `localhost:80` | Nginx API gateway |
| `localhost:3001` | Grafana (admin/admin) |
| `localhost:15672` | RabbitMQ management (guest/guest) |
| `localhost:9090` | Prometheus |

---

## Full list of accuracy notes (so nothing said on camera is wrong)

1. **Two Postgres containers, one used.** `postgres_shard1` runs, has the full schema, but is completely empty (0 rows, verified). A real consistent-hash sharding design exists (`backend/app/core/consistent_hash.py` + `shard_db.py`) but is never imported by any live service — see Segment 2.5 for exactly what to say about it and why it's not wired in (the email-vs-user_id lookup-key problem).
2. **Password hashing is SHA-256, not bcrypt.** README says bcrypt; code uses unsalted `hashlib.sha256`.
3. **JWT library is `python-jose`, not PyJWT.** Functionally the same (HS256 JWTs), just a naming correction if asked.
4. **Kafka has publishers but no consumer.** Events are genuinely published to real topics, but nothing in this repo reads them yet. Don't claim an analytics pipeline is processing them live.
5. **`activity-service` is not a Kafka consumer**, despite the README table saying so — it's a REST API that's never actually called by the frontend or any other service. Skip it in the demo, or mention it honestly as a scaffolded-but-unused service.
