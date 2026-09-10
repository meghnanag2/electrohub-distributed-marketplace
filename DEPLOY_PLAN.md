# ElectroHub — Production Deploy Plan

**Target shape:** React frontend on **Vercel**, the whole backend stack (6 services +
Postgres + Redis + Kafka + RabbitMQ + Nginx + Caddy/TLS) on **one Linux VM** via
`docker compose`, two separate public HTTPS origins.

Everything below was verified against the actual repo on this machine, not assumed.
Where a claim is an estimate rather than a measurement, it says so.
This document supersedes `DEPLOY_ORACLE_VERCEL.md` (which has several errors — see
[Corrections to the old plan](#corrections-to-the-old-plan)) and the "Notes on
Production Readiness" section of `DEPLOYMENT.md`.

---

## 0. Verdict first

| Question | Answer |
|---|---|
| Will this stack run on Oracle's free ARM tier (Ampere A1, aarch64)? | **Yes.** Every image and every Python wheel resolves on `linux/arm64`. Architecture is *not* the blocker. |
| Is Oracle still the right host? | **Only if $0 matters more than your time.** The real Oracle risk is `Out of capacity` on `VM.Standard.A1.Flex`, which is common and can persist for days. |
| Cheapest host that just works | **Hetzner CAX21** (4 vCPU ARM / 8 GB / 80 GB, ~€6.49/mo). Same aarch64 verification applies. See [Host options](#host-options). |
| Does the stack fit? | Comfortably. ~3–4 GB RAM steady-state, ~10 GB disk. 24 GB (Oracle) is 6× headroom; 8 GB is enough; **4 GB is tight and 2 GB will not work**. |
| Biggest actual blockers | (1) build-time RAM/disk for the SBERT image, (2) TLS — without it the Vercel frontend cannot talk to the backend at all, (3) unpinned `torch`. See [Blockers ranked](#blockers-ranked). |

---

## Blockers ranked

Ordered by probability × impact. Items marked **FIXED** were changed in this repo;
items marked **YOU** need a decision or an action from you; items marked **ACCEPTED**
ship as-is and are documented so nobody is surprised.

| # | Blocker | Status |
|---|---|---|
| 1 | **No TLS.** Vercel serves the frontend over HTTPS. Browsers hard-block an HTTPS page from calling `http://` APIs or opening `ws://` sockets. Without TLS on the backend, login, browsing and chat all fail 100% of the time from the Vercel URL — this is not a warning, it is a total outage. | **FIXED** — added `docker-compose.prod.yml` + `caddy/Caddyfile` (automatic Let's Encrypt). **YOU** must supply a domain name. |
| 2 | **Caddy and Nginx both wanted host port 80.** The old plan told you to install Caddy on the host with `reverse_proxy localhost:80` while compose already published `80:80`. Caddy would have failed to bind, and the ACME challenge with it. | **FIXED** — the prod overlay moves Nginx to `127.0.0.1:8080` and gives Caddy `:80`/`:443`. |
| 3 | **Every internal port was published on `0.0.0.0`** — Postgres 5432/5433, Redis 6379 (**no password at all**), Kafka 9092, RabbitMQ 5672 + management UI 15672, services 8001–8005, Prometheus 9090, Grafana 3001. The old plan's mitigation (`iptables -I INPUT -p tcp --dport 80 -j ACCEPT`) does **not** help: Docker publishes ports through its own `DOCKER`/`nat` chains, which bypass `INPUT` entirely. An unauthenticated Redis on a public IP is found by scanners in minutes. | **FIXED** — all of them now bind `127.0.0.1` in `docker-compose.yml`. Local dev is unaffected. |
| 4 | **`torch` is unpinned** in `services/recommendation-service/Dockerfile` (`pip install torch --index-url .../whl/cpu`). Today that resolves to torch 2.9.x. A future release, or a `sentence-transformers==2.7.0` incompatibility, turns a previously-working build into a failed deploy with no code change. | **YOU** — one line, see [Step 1](#step-1--pre-flight-on-your-laptop). Not auto-changed because pinning to an untested version is worse than pinning to the one you already built successfully. |
| 5 | **`seed_all.py` is not idempotent.** Users use `ON CONFLICT DO NOTHING`, but the 500 items, 3000 interactions, ~200 messages and activity rows are plain `INSERT`s. The `seed` service is a one-shot container that `docker compose up -d` restarts — so every routine restart appended another 500 listings to a live database. | **FIXED** — the `seed` command now checks `count(*) FROM marketplace_items` and skips if non-empty. `seed_all.py` itself was not touched. |
| 6 | **FastAPI interactive docs were publicly reachable.** All five HTTP services enable `/docs`, `/redoc` and `/openapi.json` by default, and Nginx's catch-all `location /` forwarded them straight through. Your full API surface, schemas and internal error shapes were browsable by anyone. | **FIXED** — `nginx.conf` now returns 404 for `/docs`, `/redoc`, `/openapi.json`, `/debug*` and `/metrics`. Still reachable on loopback for debugging. |
| 7 | **`GET /users/{user_id}` returned `email` with no authentication**, and `user_id`s are sequential (`user_000003`) — i.e. one-loop enumeration of every account's email. | **FIXED** — `email` removed from that response (nothing in the frontend read it). The endpoint is still unauthenticated; see [Accepted risks](#accepted-risks-shipping-as-is). |
| 8 | **Rate limiting would have collapsed to one global bucket.** With Caddy in front, `$binary_remote_addr` becomes Caddy's container IP, so all visitors on Earth would share a single 30 req/min bucket. | **FIXED** — `set_real_ip_from` (private ranges only) + `real_ip_header X-Forwarded-For` in `nginx.conf`. |
| 9 | **Insecure secret defaults would ship silently.** `POSTGRES_PASSWORD:-password`, `JWT_SECRET_KEY:-electrohub-dev-secret-change-in-production`, `RABBITMQ_*:-guest`, `GRAFANA_ADMIN_PASSWORD:-admin`. A missing or misspelled `.env` produced a fully-booted, fully-compromised stack. | **FIXED** — all five are now `${VAR:?message}`: the stack refuses to start rather than using a dev secret. Verified it errors out when unset. |
| 10 | **Build cost on a small VM.** The recommendation image pulls CPU torch + transformers + scipy + scikit-learn and bakes the model in — roughly 3–4 GB of image layers and a build that needs a couple of GB free RAM. On a 2 GB VM the build itself OOMs. | **YOU** — pick a host with ≥ 4 GB (see [Host options](#host-options)). |
| 11 | **Rate limits are demo-tuned, not traffic-tuned.** 30 req/min general with `burst=10`. One SPA page load fires several API calls, so a handful of real users will see spurious 429s. | **ACCEPTED** — left as-is because `electrohub_demo_script.md` §9 quotes these exact numbers. `nginx.conf` carries a comment with the values to change before real users arrive. |
| 12 | **Passwords are unsalted SHA-256** (`services/user-service/app/core/security.py`, and the seeder's `h()`). Not a deploy blocker, but it is the most serious security defect in the codebase: a stolen database is a rainbow-table lookup away from every password. | **ACCEPTED / YOU** — not changed because it would invalidate every seeded hash. Do not open registration to real users until this is bcrypt/argon2. |
| 13 | **Prometheus + Grafana are decorative.** `prometheus.yml` scrapes `/metrics` on four services, but **no service wires up an instrumentator** — `prometheus-fastapi-instrumentator` is in every `requirements.txt` and imported nowhere (`grep -rn prometheus services/*.py` → zero hits outside requirements). All four targets will show DOWN. Grafana also has no provisioned datasource or dashboard. | **ACCEPTED** — documented, not fixed. It costs ~250 MB RAM to run two containers that show nothing. Consider `--scale prometheus=0 --scale grafana=0` for a first deploy. |
| 14 | ~~`postgres_shard1` runs, is schema-complete, and is used by nothing.~~ **No longer true.** The `seed` service now runs `seed_sharded.py`, which routes every row through the real `ConsistentHashRing` — both shards hold ~50% of the data, verified live (`verify_shards.py`, 18/18 checks pass). The app services (`user-service` etc.) still each read `DB_HOST=postgres_shard0` only, so **application reads only see shard0's half** — the sharding is real at the data layer but not yet wired into the request path. | **PARTIALLY FIXED** — data layer done; making the API itself shard-aware (fan-out reads, `get_db_for_user` routing) is the natural next step, out of scope here. |
| 16 | **Kafka crash-looped on restart.** The image's default `log.dirs` (`/tmp/kafka-logs`) was never actually the mounted `kafka_data` volume, so "persistent" storage lived in the container's ephemeral layer — any ungraceful stop could corrupt the KRaft checkpoint and crash-loop the broker (a real self-protective feature reacting to a real storage misconfig, not a Kafka bug). | **FIXED** — `KAFKA_LOG_DIRS=/opt/kafka/data` points it at the real volume; a one-shot `kafka-volume-init` service `chown`s the volume to uid 1000 first (Docker creates new named volumes root-owned; the image runs as uid 1000). Verified surviving two consecutive restarts. |
| 15 | ~~The `backend/` monolith is not in `docker-compose.yml` at all.~~ **Resolved by deletion.** `backend/Dockerfile`, `app/main.py`, `app/api/`, `app/services/`, `app/models/`, `app/schemas/`, and the unused `app/core/*.py` files were confirmed dead (never built/run by compose, not imported by the sharding scripts) and removed outright. `backend/` now holds only what `seed_sharded.py`/`verify_shards.py` actually import: `app/core/{consistent_hash,shard_db}.py`. | **FIXED** — dead code no longer exists to worry about. |
| 17 | **`notification-service` has no `/health` endpoint and no compose healthcheck** — it's a bus consumer with zero HTTP routes, so a dead Kafka/RabbitMQ consumer currently looks indistinguishable from a healthy one. **`nginx` also has no healthcheck** and uses bare `depends_on` (no `condition: service_healthy`), so it can start before its upstream services are actually ready. | **YOU** — add a trivial `GET /health` to `notification-service` that checks its broker connections, then a `curl`-based healthcheck in compose matching the other services; give `nginx` a healthcheck + upgrade its `depends_on` entries to `condition: service_started` at minimum. Matters most for Step 8's `docker compose ps` check and for any future ALB/load-balancer target group. |

---

## Resource reality check

### RAM (estimates from image/runtime characteristics; not measured on this machine)

| Container | Steady-state RSS | Note |
|---|---|---|
| kafka (JVM) | **~1.0–1.3 GB** | Biggest single consumer. Image default heap is a fixed 1 GB. The prod overlay caps it at `-Xmx512m`, saving ~500–700 MB. |
| recommendation-service | **~0.7–1.2 GB** | torch runtime + `all-MiniLM-L6-v2` + a 500×384 float matrix. Peaks while encoding the catalogue at startup, then settles. Prod overlay caps it at 2 GB. |
| rabbitmq | ~120–150 MB | |
| grafana | ~100–150 MB | Shows nothing (see blocker 13). |
| prometheus | ~100–200 MB | All targets DOWN (see blocker 13). |
| postgres_shard0 | ~60–100 MB | |
| postgres_shard1 | ~50–60 MB | Unused. |
| user / listing / messaging / notification / activity | ~80–150 MB **each** | ≈ 500–700 MB total. |
| redis | ~10–15 MB | |
| nginx + caddy | ~10–20 MB | |
| **Total steady-state** | **≈ 3.0–4.0 GB** | With the prod overlay's Kafka cap: **≈ 2.5–3.3 GB**. |
| **Peak during `up -d --build`** | **+1–2 GB** | pip unpacking torch is the spike. |

**CPU:** idle is near zero. The only real burst is the SBERT startup encode (single-shot,
~30–90 s, 1–2 cores). 2 vCPU is enough; 4 is comfortable.

### Disk

Third-party image download sizes, **measured** from the arm64 registry manifests
(compressed; on-disk is roughly 2–2.5×):

| Image | Compressed (arm64) |
|---|---|
| `apache/kafka:3.7.1` | 201 MB |
| `postgres:15-alpine` | 108 MB |
| `rabbitmq:3-management` | 106 MB |
| `grafana/grafana:10.2.0` | 98 MB |
| `python:3.11-slim` | 47 MB |
| `nginx:alpine` | 28 MB |
| `redis:7-alpine` | 16 MB |
| `prom/prometheus:v2.48.0`, `caddy:2-alpine` | ~90 MB, ~15 MB (est.) |

Plus six locally built images: five slim FastAPI services at ~350–450 MB each
(`grpcio-tools` is most of it) and **recommendation-service at ~3–4 GB** (torch +
transformers + scipy + scikit-learn + baked model weights).

**Budget ~15 GB of disk minimum, 40 GB comfortably.** Oracle's 50 GB default boot
volume and Hetzner's 80 GB are both fine. Docker logs also grow without bound by
default — the prod overlay caps them at 10 MB × 3 per container.

---

## ARM (aarch64) verdict — **clear**

This was the single most likely thing to sink the deploy, so it was checked
empirically rather than assumed.

### Container images — all multi-arch, verified against live registry manifests

| Image | `linux/arm64`? |
|---|---|
| `postgres:15-alpine` | ✅ (arm64/v8) |
| `redis:7-alpine` | ✅ (arm64/v8) |
| `apache/kafka:3.7.1` | ✅ — note the stack uses **`apache/kafka`, not `confluentinc/*`**; the Confluent images were historically amd64-only, so this is a lucky choice |
| `rabbitmq:3-management` | ✅ (arm64/v8) |
| `python:3.11-slim` | ✅ (arm64/v8) — base for all six built services |
| `nginx:alpine` | ✅ (arm64/v8) |
| `prom/prometheus:v2.48.0` | ✅ (arm64/v8) |
| `grafana/grafana:10.2.0` | ✅ (arm64) |
| `caddy:2-alpine` | Official Caddy images are multi-arch incl. arm64. Docker Hub rate-limited (HTTP 429) during re-verification, so this one is not independently confirmed here — it will fail loudly at `docker compose pull` if wrong, before anything else runs. |

### Python wheels — every compiled dependency has a cp311 aarch64 wheel

Checked against PyPI and `download.pytorch.org`. This matters because **none of the
service Dockerfiles install a compiler** (only `backend/Dockerfile` has
`build-essential`), so a missing wheel is a hard build failure, not a slow build.

| Package | aarch64 cp311 wheel |
|---|---|
| `torch` (CPU index) | ✅ `torch-*+cpu-cp311-cp311-manylinux_2_28_aarch64.whl` — present for every version from 2.0 through 2.9.x. The `--index-url .../whl/cpu` also carries torch's own deps (`sympy`, `networkx`, `filelock`, `jinja2`, `fsspec`, `typing-extensions`, `mpmath`, `markupsafe` — all HTTP 200), so replacing PyPI for that one command is safe. |
| `psycopg2-binary==2.9.9` | ✅ `manylinux_2_17_aarch64` |
| `grpcio==1.60.0`, `grpcio-tools==1.60.0` | ✅ `manylinux_2_17_aarch64` |
| `pydantic-core` (for `pydantic==2.5.0`) | ✅ `manylinux_2_17_aarch64` |
| `numpy==1.26.4` | ✅ `manylinux_2_17_aarch64` |
| `tokenizers`, `safetensors` | ✅ `cp310-abi3` aarch64 |
| `scikit-learn` | ✅ 1.9.0 `manylinux_2_28_aarch64` |
| `scipy` | ✅ — latest scipy (1.18.x) is `requires_python >=3.12`, so pip on 3.11 resolves **1.17.1**, which has a cp311 aarch64 wheel and declares `numpy>=1.26.4,<2.7` (satisfied by the pinned `numpy==1.26.4`). No conflict. |
| `pillow`, `regex`, `uvloop`, `httptools`, `watchfiles` | ✅ aarch64 |
| `sqlalchemy`, `pydantic`, `websockets`, `kafka-python`, `pika`, `python-jose`, `sentence-transformers`, `transformers`, `huggingface-hub` | ✅ pure-Python (`-none-any.whl`) |

**Dependency-resolution check:** `sentence-transformers==2.7.0` requires
`transformers<5.0.0`, so pip picks transformers 4.57.x, which pins
`huggingface-hub<1.0` — meaning the hub 1.x breaking changes are dodged
automatically. The three hub symbols `sentence_transformers` 2.7.0 actually imports
(`HfApi`, `snapshot_download`, `hf_hub_download`) all still exist. This is luck held
in place by an upper bound, not by design — which is exactly why blocker 4 (pin
`torch`) is worth doing.

**Bottom line:** x86-vs-ARM is a non-issue for this stack. Build natively on the ARM
VM (never cross-build under QEMU — the torch install would take hours).

---

## Prerequisites you must provide

Nothing below can be done for you. Have all of it before starting.

| # | What | Why | Notes |
|---|---|---|---|
| 1 | **A cloud account** with a card on file | Oracle requires one for identity verification even for Always Free; Hetzner/DO bill it | — |
| 2 | **A domain or free subdomain** pointing at the VM's public IP | **Mandatory, not optional.** Let's Encrypt cannot issue a certificate for a bare IP, and without a certificate the Vercel frontend cannot reach the backend at all | A `*.duckdns.org` or `*.sslip.io` name is fine. If you own a domain, an `api.` subdomain is tidiest. |
| 3 | **An SSH keypair** | To reach the VM | `ssh-keygen -t ed25519 -C "electrohub-deploy"`, or let the provider generate one — **download the private key before leaving the create page; you cannot get it later** |
| 4 | **An email address for Let's Encrypt** | Certificate expiry notices | Any address you read |
| 5 | **A Vercel account** + `npm i -g vercel` and `vercel login` | Frontend hosting | Free tier is sufficient and does not sleep |
| 6 | **A GitHub repo (optional but recommended)** | **This project is not a git repo yet** — verified, there is no `.git` directory. Without one you must `scp` the code to the VM, and Vercel can't auto-deploy on push | `.gitignore` already excludes `.env`, `node_modules/`, `frontend/build/`. **Never commit `.env`.** |
| 7 | **The `torch` version your last successful local build used** | To pin blocker 4 | `docker run --rm electrohub-marketplace-main-recommendation-service pip show torch \| grep Version` |

A `.env` with real generated secrets **already exists at the repo root** — it has all
six required keys populated. It is gitignored. Do not commit it; copy it to the VM
over SSH (Step 4), never through a git remote.

---

## Host options

| Host | Spec | Cost | Verdict |
|---|---|---|---|
| **Oracle Cloud Always Free** — `VM.Standard.A1.Flex` | 4 OCPU ARM / 24 GB / 50 GB | **$0 forever** | Most headroom, zero cost, ARM verified fine. **The catch is capacity:** `Out of capacity` on A1.Flex is routine in busy regions and can block you for days. Retry loops or a different home region sometimes help. Also set the boot volume's backup policy to **"No backup policy"** — backups are the one thing Always Free does not cover and the usual source of a surprise ~$2/mo line item. |
| Oracle `VM.Standard.E2.1.Micro` | 1 OCPU / **1 GB** | $0 | **Will not work.** Not even the recommendation image build fits. Don't bother. |
| **Hetzner Cloud `CAX21`** ⭐ recommended fallback | 4 vCPU ARM / **8 GB** / 80 GB | ~€6.49/mo | Best cost-to-sanity ratio. Provisions in ~30 s, no capacity lottery, snapshots, hourly billing so a failed experiment costs cents. Same aarch64 story as Oracle, so everything verified above applies unchanged. |
| Hetzner `CAX11` | 2 vCPU ARM / 4 GB / 40 GB | ~€3.29/mo | Works, but tight. Use the prod overlay's Kafka cap and scale Prometheus/Grafana/`postgres_shard1` to 0. |
| DigitalOcean / Vultr / Linode | 2 vCPU / 4 GB | ~$24/mo | Fine, ~4× Hetzner's price. Pick if you already have credits. |
| Fly.io / Railway / Render | per-service | varies | **Avoid for this stack.** It is a 15-container compose file with a one-shot seed job, gRPC between services, and an internal Nginx gateway. Splitting it into per-service PaaS deployments is a rewrite, not a deploy. |

**Recommendation:** try Oracle A1.Flex once. If you hit `Out of capacity`, do not fight
it — spend €6.49 on a Hetzner CAX21 and be deployed in ten minutes. Every step below
is identical on both (Ubuntu 22.04/24.04, ARM).

---

# The runbook

Placeholders used throughout: `api.example.com` (your domain from prereq 2),
`<VM_IP>`, `~/.ssh/electrohub.key` (your private key), `electrohub.vercel.app`.

## Step 1 — Pre-flight on your laptop

```bash
cd /Users/atrayeenag/Downloads/electrohub-marketplace-main

# Confirm the compose file is valid and secrets resolve from .env
docker compose config >/dev/null && echo "compose OK"

# Confirm the production overlay merges (needs the two new .env keys)
docker compose -f docker-compose.yml -f docker-compose.prod.yml config >/dev/null \
  && echo "prod overlay OK"
```

Add the two TLS keys to your existing `.env`:

```bash
cat >> .env <<'EOF'
PUBLIC_DOMAIN=api.example.com
ACME_EMAIL=you@example.com
EOF
```

**Pin `torch`** (blocker 4). Find the version your working local build used, then edit
`services/recommendation-service/Dockerfile`:

```bash
docker run --rm electrohub-marketplace-main-recommendation-service pip show torch | grep Version
# then, in that Dockerfile, change:
#   RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# to (substituting the version you just printed):
#   RUN pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
```

If you have no local image to check, pin `torch==2.7.1` — it has aarch64 CPU wheels
and predates the newest API churn.

**Do not** run `docker compose up` on your laptop expecting to test the prod overlay:
Caddy will try to get a real certificate for a domain that does not point at your
laptop and will fail. Test the base stack locally; test TLS on the VM.

## Step 2 — Create the VM

Ubuntu 22.04 or 24.04 LTS, ARM (Ampere/`CAX*`), ≥ 4 GB RAM, ≥ 40 GB disk, public IPv4,
your SSH key installed.

- **Oracle:** Compute → Instances → Create. Image/shape → Edit → Ubuntu 22.04 →
  Change shape → **Ampere → VM.Standard.A1.Flex → 4 OCPU / 24 GB**. Confirm
  "Assign a public IPv4 address". Add SSH keys → paste your public key (or generate
  and **save the private key immediately**). After creation, open the instance's
  **Boot Volume** and set Backup Policy to **No backup policy**.
- **Hetzner:** New Server → Ubuntu 24.04 → **CAX21** → add SSH key → Create.

## Step 3 — DNS

Point your domain at the VM before touching Caddy — Let's Encrypt validates over
HTTP against the live DNS record.

```bash
# an A record: api.example.com -> <VM_IP>
dig +short api.example.com     # must print <VM_IP> before you continue
```

## Step 4 — Firewall: open only 80 and 443

Two firewalls exist on Oracle and **both** must allow traffic or it silently fails.

**Cloud-level** (Oracle: VCN → Subnet → Security List → Add Ingress Rules;
Hetzner: Firewalls, or leave open and rely on the host):

| Source | Protocol | Port | Purpose |
|---|---|---|---|
| `0.0.0.0/0` | TCP | 443 | HTTPS API |
| `0.0.0.0/0` | TCP | 80 | ACME HTTP-01 challenge + http→https redirect |
| your IP only | TCP | 22 | SSH |

**Host-level:**

```bash
ssh -i ~/.ssh/electrohub.key ubuntu@<VM_IP>
sudo iptables -I INPUT -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo apt-get install -y iptables-persistent   # answer "yes" to save current rules
sudo netfilter-persistent save
```

> Open **nothing else**. And know what that host firewall does and does not do:
> `iptables -I INPUT` rules do **not** govern Docker-published ports, because
> Docker DNATs them through its own chains ahead of `INPUT`. The reason
> 5432/6379/15672/3001/9090 are safe here is that `docker-compose.yml` now binds
> them to `127.0.0.1` — not the firewall. Never remove those `127.0.0.1:` prefixes
> on a public machine.

## Step 5 — Install Docker + log rotation

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo systemctl enable docker          # survives reboots
newgrp docker

# Global log rotation, in case anything runs without the prod overlay's logging block
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
sudo systemctl restart docker
```

## Step 6 — Get the code and secrets onto the VM

With a GitHub repo:

```bash
git clone <your-repo-url> electrohub && cd electrohub
```

Without one, from your laptop:

```bash
rsync -av --exclude node_modules --exclude frontend/build --exclude .env \
  -e "ssh -i ~/.ssh/electrohub.key" \
  /Users/atrayeenag/Downloads/electrohub-marketplace-main/ ubuntu@<VM_IP>:~/electrohub/
```

Then copy the secrets **separately and never via git**:

```bash
scp -i ~/.ssh/electrohub.key \
  /Users/atrayeenag/Downloads/electrohub-marketplace-main/.env \
  ubuntu@<VM_IP>:~/electrohub/.env
```

On the VM, sanity-check without printing values:

```bash
cd ~/electrohub
chmod 600 .env
cut -d= -f1 .env | grep .        # key names only
docker compose config >/dev/null && echo "secrets resolve OK"
```

If `docker compose config` errors with `required variable ... is missing a value`,
that is the new guard doing its job — fill in the named key.

## Step 7 — Set CORS to a placeholder, then build

You do not have the Vercel URL yet, so set it after Step 9. For now:

```bash
grep -q '^PUBLIC_DOMAIN=' .env || echo "PUBLIC_DOMAIN=api.example.com" >> .env
grep -q '^ACME_EMAIL=' .env    || echo "ACME_EMAIL=you@example.com"    >> .env

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Expect **10–25 minutes** on first build — mostly the torch download and the
recommendation image. Watch it:

```bash
docker compose logs -f seed                    # should end with "ALL TABLES SEEDED"
docker compose logs -f recommendation-service  # "Index ready — N items indexed" (60–120 s)
docker compose logs -f caddy                   # "certificate obtained successfully"
docker compose ps                              # everything healthy / running
```

Optional, if you are on a 4 GB box or just want the RAM back — Prometheus and
Grafana currently show nothing (blocker 13) and `postgres_shard1` is unused
(blocker 14):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d \
  --scale prometheus=0 --scale grafana=0 --scale postgres_shard1=0
```

Verified accepted by `docker compose --dry-run`. Note the flags are per-invocation:
repeat them on every later `up -d`, or those three come back.

## Step 8 — Verify the backend before touching the frontend

```bash
# On the VM
curl -s http://127.0.0.1:8080/health                      # {"service":"user-service","status":"ok"}

# From your laptop — TLS, real certificate, real data
curl -s https://api.example.com/health
curl -s https://api.example.com/marketplace/categories
curl -sI http://api.example.com/health | head -1          # expect 308 -> https

# These must all be 404 (gateway hardening)
for p in /docs /redoc /openapi.json /debug/shard-distribution /metrics; do
  printf "%-28s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' https://api.example.com$p)"
done

# These must all FAIL to connect (loopback-only bindings)
for p in 5432 6379 15672 3001 9090 8001; do
  nc -z -w3 <VM_IP> $p && echo "PORT $p EXPOSED — STOP AND FIX" || echo "port $p closed OK"
done
```

Do not continue until the certificate is live and the exposure checks pass.

## Step 9 — Deploy the frontend to Vercel

`frontend/package.json` has `"proxy": "http://localhost:80"`. **That field is read
only by the CRA dev server (`react-scripts start`) and is ignored by
`react-scripts build`** — it does nothing in production and does not need removing.
What replaces it is `REACT_APP_API_URL`, which CRA **inlines into the bundle at build
time**. Verified in the code: `frontend/src/services/api.js` sets the axios
`baseURL` from it (falling back to `""` = same-origin), and
`frontend/src/pages/Chat.jsx` derives the WebSocket host and `ws:`/`wss:` scheme from
the same value. Because it is baked in at build time, **changing it later requires a
redeploy, not a restart.**

A `frontend/vercel.json` has been added declaring the CRA framework and an SPA
rewrite — the app uses `BrowserRouter` with 7 routes, so without a fallback to
`index.html` a deep link like `/item/42` would 404 on refresh.

```bash
cd frontend
npm i -g vercel && vercel login
vercel link                       # set Root Directory to "frontend" if asked
vercel env add REACT_APP_API_URL production
# paste: https://api.example.com     (https, no trailing slash)
vercel --prod
```

Note the production URL it prints, e.g. `https://electrohub.vercel.app`.

Dashboard equivalent, if you connected the GitHub repo: Project Settings → General →
**Root Directory = `frontend`**; Environment Variables → `REACT_APP_API_URL` =
`https://api.example.com` (Production); then redeploy.

## Step 10 — Point CORS at the real frontend origin

```bash
ssh -i ~/.ssh/electrohub.key ubuntu@<VM_IP>
cd ~/electrohub
nano .env      # CORS_ORIGINS=https://electrohub.vercel.app
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Exact-match rules — FastAPI's `CORSMiddleware` compares origin strings literally:

- scheme included, **no trailing slash**: `https://electrohub.vercel.app` ✅,
  `https://electrohub.vercel.app/` ❌
- comma-separated, no spaces needed
- add a custom domain as a **second entry**, don't replace
- Vercel **preview** deployments get per-commit URLs that cannot be pre-listed; they
  will fail CORS. Test against the production URL, or add each preview URL as needed.

This env var reaches five services — `user-service`, `listing-service`,
`messaging-service`, `activity-service` and (newly) `recommendation-service`, which
previously hardcoded `allow_origins=["*"]`.

## Step 11 — End-to-end check in a browser

Open the Vercel URL and confirm, with DevTools → Network open:

1. **Login** (`demo@electrohub.com` / `password123`) → `POST /auth/login` returns 200,
   and the OPTIONS preflight before it also returns 200.
2. **Home** → listings and images render (`GET /marketplace/items`).
3. **Item detail** → the "similar items" row populates (`GET /recommendations/{id}` —
   this is the path that would have failed under the old wildcard CORS once
   credentials were involved).
4. **Chat** → the WebSocket shows `101 Switching Protocols` on a **`wss://`** URL. A
   `ws://` URL here means `REACT_APP_API_URL` was set to `http://` — rebuild.
5. **Refresh on a deep link** (`/item/42`) → still loads, no 404 (the `vercel.json`
   rewrite).

## Step 12 — Ops

```bash
# Reaching the private admin UIs — SSH tunnel, never an open port
ssh -i ~/.ssh/electrohub.key -L 3001:127.0.0.1:3001 -L 15672:127.0.0.1:15672 ubuntu@<VM_IP>
# then http://localhost:3001 (Grafana) and http://localhost:15672 (RabbitMQ)

# Health / logs / disk
docker compose ps
docker compose logs --tail=100 <service>
df -h && docker system df
docker system prune -f          # after a few rebuilds

# Update after a code change
git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Back up the database (the only stateful thing that matters)
docker exec electrohub-postgres-shard0 pg_dump -U postgres electrohub \
  | gzip > ~/electrohub-$(date +%F).sql.gz
```

**Staying up across reboots:** `restart: unless-stopped` on every service plus
`systemctl enable docker` means the whole stack returns after a reboot with no manual
step. Caddy's certificates live in the `caddy_data` volume and renew themselves;
**do not delete that volume** or you will re-request certificates and can hit Let's
Encrypt rate limits.

## Teardown

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down     # keep data
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v  # delete data
```

Then delete the VM in the provider console, and `vercel remove <project>`.

---

## Accepted risks (shipping as-is)

Deliberate, and worth knowing before you share the URL with anyone:

1. **Unsalted SHA-256 password hashing.** Fine for a demo with seeded accounts;
   unacceptable for real signups. Fix before real users.
2. **Unauthenticated endpoints**, reachable by anyone who can reach the gateway:
   `GET /users/{user_id}` (now without `email`), `GET /marketplace/items`,
   `GET /marketplace/categories`, `GET /activity/summary/{user_id}`,
   `GET /activity/popular-items`, and — the one that is actually a write —
   `POST /activity/track`, which lets anyone insert activity rows. The Nginx
   `api_general` limit is the only thing throttling it.
3. **`python-jose==3.3.0`** is old and has published advisories. Upgrading is a
   separate, testable change.
4. **No database backups by default.** The `pg_dump` line in Step 12 is manual. Put
   it in cron if the data starts mattering.
5. **Single point of failure.** One VM, one Postgres, no replicas. Fine for a demo;
   don't call it highly available.
6. **Kafka has no consumer.** Events are produced and nothing reads them
   (`electrohub_demo_script.md` says as much). It is ~1 GB of RAM for a demo of the
   producer side. Scaling it to 0 breaks `messaging-service`'s startup dependency, so
   leave it running or remove the dependency deliberately.

---

## Corrections to the old plan

`DEPLOY_ORACLE_VERCEL.md` is largely accurate about the *code* changes it claims —
those were verified present (`api.js` reads `REACT_APP_API_URL`; `Chat.jsx` derives
`ws`/`wss` from it; four services read `CORS_ORIGINS`; every service has
`restart: unless-stopped`; `recommendation-service` waits on `seed`). Its
*infrastructure* advice has four errors:

1. **Caddy on the host with `reverse_proxy localhost:80` cannot work** while compose
   publishes `80:80`. Port collision; Caddy never binds; ACME never completes.
   → Fixed by `docker-compose.prod.yml`.
2. **`iptables -I INPUT ... -j ACCEPT` is presented as what keeps 5432/6379/15672
   private.** It does not — Docker's published ports bypass `INPUT`. Those ports were
   world-reachable behind nothing but the cloud Security List.
   → Fixed by loopback bindings.
3. **"no more code changes needed unless something breaks."** Not so: `torch` is
   unpinned, `seed_all.py` re-ran destructively on every `up -d`,
   `recommendation-service` had wildcard CORS, and FastAPI `/docs` was public.
4. **"Dropping `postgres_shard1` … with no loss of working functionality"** is
   correct, but the same paragraph recommends dropping `rabbitmq` and
   `notification-service`, which `messaging-service` declares a hard
   `service_healthy` dependency on. Removing RabbitMQ without editing that
   `depends_on` prevents `messaging-service` from starting at all.

`DEPLOYMENT.md` is stale in three places: it references an `electrohub-backend`
container and `docker exec -it electrohub-backend python seed_all.py` (no `backend`
service exists in compose — seeding is the `seed` service), it describes a `frontend`
container that hot-reloads (there is none), and it lists `nginx:1.25-alpine` where
compose uses `nginx:alpine`.

---

## What changed in this repo

| File | Change |
|---|---|
| `docker-compose.yml` | All non-public ports bound to `127.0.0.1`; five secrets made required (`${VAR:?…}`) instead of having insecure defaults; `SMTP_*` made overridable from `.env`; `CORS_ORIGINS` passed to `recommendation-service`; header comments rewritten to explain the port policy. `seed` repointed at `seed_sharded.py` + `verify_shards.py` (was `seed_all.py`, shard0-only) with a two-shard idempotency guard. `kafka` given `KAFKA_LOG_DIRS` pointed at its real volume plus a `kafka-volume-init` one-shot ownership fix — see blocker 16. |
| `.github/workflows/ci.yml`, `.github/workflows/deploy-backend.yml` | **New.** Push-to-deploy pipeline — see `CI_CD_PIPELINE.md`. |
| `docker-compose.prod.yml` | **New.** Adds Caddy (TLS), moves Nginx to `127.0.0.1:8080`, caps Kafka heap and recommendation-service memory, rotates all container logs. |
| `caddy/Caddyfile` | **New.** Automatic Let's Encrypt for `PUBLIC_DOMAIN`, http→https redirect, reverse proxy to the `nginx` container. |
| `nginx/nginx.conf` | 404s `/docs`, `/redoc`, `/openapi.json`, `/debug*`, `/metrics`; `set_real_ip_from` so rate limits key on the real client behind Caddy; `server_tokens off`; `client_max_body_size 2m`; `server_name _`; forwards `X-Forwarded-Proto`. Routing and rate-limit values unchanged. |
| `.env.example` | Rewritten: documents all 12 variables (was 6), marks which are required, adds `SMTP_*`, `PUBLIC_DOMAIN`, `ACME_EMAIL`, and explains that `REACT_APP_API_URL` is a build-time frontend variable that does not belong in this file. |
| `services/recommendation-service/app/main.py` | `allow_origins=["*"]` → `CORS_ORIGINS` env, matching the other four services. |
| `services/user-service/app/api/users.py` | Removed `email` from the unauthenticated `GET /users/{user_id}` response. |
| `frontend/vercel.json` | **New.** CRA framework declaration + SPA rewrite so `BrowserRouter` deep links survive a refresh. |

Not touched: `backend/seed_all.py`, `backend/seed_sharded.py`, `backend/verify_shards.py`,
`backend/app/api/`, anything under `frontend/src/`, and all six `Dockerfile`s.
