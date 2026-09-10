# ElectroHub Deployment Checklist

Consolidated from `DEPLOY_PLAN.md` and `CI_CD_PIPELINE.md`. Paste this whole
file into a claude.ai browser chat if you want help on a step while you're
doing the console/browser work there — it won't have this project's files,
but it will have full context on what you're trying to do and why.

Currently deploying via **Google Cloud (free $300/90-day trial credit)** for
the backend + **Vercel (free)** for the frontend, to validate everything
works before spending any money. Same steps work on Hetzner, AWS EC2, or
Oracle later — only Phase 1 (account + VM creation) changes.

---

## What actually needs to be deployed (the files that matter)

The repo has a lot in it, but only some of it is "the system." Here's what's
load-bearing vs. what's just documentation:

| Path | What it is | Deployed how |
|---|---|---|
| `docker-compose.yml` + `docker-compose.prod.yml` | Defines all 14 containers: 5 FastAPI microservices, 2 Postgres shards, Redis, Kafka, RabbitMQ, nginx, Prometheus, Grafana, Caddy (TLS) | Runs on the backend VM via `docker compose up -d --build` |
| `services/*/` (user, listing, messaging, notification, activity, recommendation) | The 6 real microservices — each has its own `Dockerfile` | Built and run by compose, on the VM |
| `services/shared/` | Code shared by every service (Kafka/RabbitMQ/Redis clients, logging, exceptions) | Copied into each service's image at build time |
| `protos/*.proto` | gRPC contracts between services | Compiled into Python stubs at Docker build time (each service's Dockerfile does this itself) |
| `database/01_schema.sql`, `02_indexes.sql` | Postgres schema | Auto-applied to both shards on first container start (`docker-entrypoint-initdb.d`) |
| `backend/seed_sharded.py`, `verify_shards.py`, `backend/app/core/{consistent_hash,shard_db}.py` | Generates realistic demo data routed through the real consistent-hash ring across both shards, then verifies the split | Run once via the `seed` service in compose |
| `nginx/nginx.conf` | Reverse proxy / gateway, routes `/api/*` to each service, hardened (blocks `/docs`, rate limits) | Runs as the `nginx` container |
| `caddy/Caddyfile` | Automatic HTTPS (Let's Encrypt) in front of nginx | Runs as the `caddy` container, prod overlay only |
| `.env` (never committed — see `.env.example` for the template) | All secrets: DB passwords, JWT key, RabbitMQ creds, your domain | Copied to the VM over `scp`, never via git |
| `frontend/src/`, `frontend/public/`, `package.json`, `vercel.json` | The React app | Deployed to **Vercel**, not the VM — separate hosting entirely |
| `.github/workflows/*.yml` | CI (build/lint check on every push) + CD (push-to-deploy to the VM) | Runs on GitHub's servers, not yours |

**Not deployed anywhere — reference only:** every `*.md` file (this one
included), `images/` (used by `README.md`), `prometheus.yml` (config the
`prometheus` container reads, technically deployed but decorative right now
— nothing wires up the metrics endpoints yet).

---

## The full checklist, in order

### Phase 0 — Already done ✅
- [x] Sharding verified: both Postgres shards hold real data through the
      consistent-hash ring (18/18 checks pass in `verify_shards.py`)
- [x] Kafka crash-loop bug fixed (log dir + volume permissions)
- [x] Dead code removed (unused monolith API, stale build artifacts)
- [x] Secrets rotated after an accidental console leak
- [x] `docker-compose.prod.yml` + `caddy/Caddyfile` written (adds TLS)
- [x] `.github/workflows/ci.yml` + `deploy-backend.yml` written (CI/CD)
- [x] `frontend/vercel.json` written (SPA routing for Vercel)
- [x] AWS billing set up (in case we switch to it later)

### Phase 1 — Google Cloud account + VM
- [ ] Create a Google Cloud account at cloud.google.com and start the free
      trial (**$300 credit, 90 days** — a card is required but nothing is
      charged until you explicitly upgrade to a paid account after the
      trial)
- [ ] Create a Project in the GCP Console (any name, e.g. `electrohub`)
- [ ] Enable the **Compute Engine API** for that project (console prompts
      you the first time you visit Compute Engine)
- [ ] Create the VM: Compute Engine → VM instances → Create instance →
      Ubuntu 24.04 LTS → machine type **e2-standard-2** (2 vCPU / 8GB) —
      use the standard x86 family, not the Tau T2A (ARM) family, so none of
      the ARM-wheel verification from the Oracle plan needs re-checking
- [ ] Under **Firewall**, check "Allow HTTP traffic" and "Allow HTTPS
      traffic" (GCP's default network blocks 80/443 otherwise — this is the
      one setup step Oracle/Hetzner don't have)
- [ ] Under **Security → SSH Keys**, add your public key
      (`cat ~/.ssh/id_ed25519.pub`), or use the "SSH" browser button GCP
      provides after creation if you'd rather not manage a key yet
- [ ] Reserve a **static external IP** (VPC network → IP addresses →
      Reserve external static address, attach it to the VM) — free while
      attached to a running instance, avoids the IP changing on restart
      (which would break your DNS record)
- [ ] Copy the VM's external IP

### Phase 2 — Domain + DNS
- [ ] Get a domain or free subdomain (a `*.duckdns.org` or `*.sslip.io` name
      works fine with Let's Encrypt) — **mandatory**, TLS cannot issue a
      certificate for a bare IP
- [ ] Point an A record at the VM's public IP
- [ ] Confirm with `dig +short yourdomain.com` — must print the VM's IP
      before continuing

### Phase 3 — Server setup
- [ ] SSH into the VM
- [ ] Open firewall ports 80 + 443 only (both the cloud Security List AND
      the host's `iptables` — Oracle has two separate firewalls)
- [ ] Install Docker (`curl -fsSL https://get.docker.com | sudo sh`)
- [ ] Enable Docker to survive reboots, set up log rotation

### Phase 4 — Get the code + secrets onto the VM
- [ ] Push this repo to GitHub (`git add -A && git commit && gh repo create`
      — nothing has been pushed yet)
- [ ] `git clone` it onto the VM
- [ ] `scp` the real `.env` file over separately — **never via git**
- [ ] Add `PUBLIC_DOMAIN` and `ACME_EMAIL` to `.env` on the VM

### Phase 5 — Build and verify
- [ ] Pin `torch` to a known-good version in
      `services/recommendation-service/Dockerfile` (one line)
- [ ] `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
      (first build takes 10–25 min)
- [ ] Watch `seed`, `recommendation-service`, and `caddy` logs until each
      reports success
- [ ] From your laptop: `curl https://yourdomain.com/health`, confirm
      `/docs` and admin ports (5432, 6379, 15672, 3001, 9090) are all
      unreachable from outside

### Phase 6 — Frontend
- [ ] `vercel login`, `vercel link` (root directory = `frontend`)
- [ ] Set `REACT_APP_API_URL` = `https://yourdomain.com` in Vercel's env vars
- [ ] `vercel --prod`, note the production URL it prints

### Phase 7 — Connect them
- [ ] Set `CORS_ORIGINS` on the VM's `.env` to the real Vercel URL
- [ ] Redeploy backend (`docker compose up -d`)
- [ ] Open the Vercel URL in a browser: log in as
      `demo@electrohub.com` / `password123`, browse listings, open a chat
      (confirms WebSocket over `wss://` works), refresh on a deep link

### Phase 8 — Automate it (optional but built already)
- [ ] Add 3 GitHub repo secrets (`EC2_HOST`/`EC2_USER`/`EC2_SSH_KEY` — name
      is generic, works for any host including this Oracle VM)
- [ ] Connect the GitHub repo in Vercel's dashboard for auto-deploy on push
- [ ] From here: every `git push origin main` deploys both sides automatically

---

## After the $300 / 90-day trial credit runs out

You'll need to decide whether to keep paying (GCP `e2-standard-2` runs
roughly $49/mo on-demand after the trial) or move the exact same setup to
Hetzner CAX21 (~€6.49/mo) or AWS EC2 `t3.large` (~$65/mo). Same runbook,
same files — only Phase 1's VM-creation step changes.
