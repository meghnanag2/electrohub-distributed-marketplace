# CI/CD Pipeline — push to `main`, it deploys itself

Builds on `DEPLOY_PLAN.md` (the verified single-EC2-VM architecture — read that
first if you haven't deployed manually yet). This document is the automation
layer on top of it: **one `git push` updates both the Vercel frontend and the
AWS backend, with no manual SSH step after the first setup.**

This repo was not a git repo until now — `git init` has been run locally, but
nothing has been committed or pushed. You do that part yourself (see
[Step 1](#step-1--commit-and-push)) — it's your GitHub account and your call
on repo visibility.

---

## The pipeline, end to end

```
you: git push origin main
        │
        ├─→ GitHub Actions: ci.yml          (always runs)
        │     • frontend builds (npm ci && npm run build)
        │     • every .py file byte-compiles
        │     • docker-compose.yml + prod overlay validate
        │     ~30–60s, catches broken commits before they reach anything live
        │
        ├─→ GitHub Actions: deploy-backend.yml   (only if backend/services/nginx/db files changed)
        │     • SSHes into your EC2 VM
        │     • git reset --hard origin/main
        │     • docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
        │     • curls /health and fails the workflow if it doesn't come back up
        │
        └─→ Vercel (its own GitHub App, not a workflow file)
              • detects the push, rebuilds frontend/, redeploys automatically
```

Two files were added: `.github/workflows/ci.yml` and
`.github/workflows/deploy-backend.yml`. Nothing needed for Vercel beyond
connecting the repo once — it does not use GitHub Actions at all.

---

## Step 1 — commit and push

```bash
cd /Users/atrayeenag/Downloads/electrohub-marketplace-main

# git init has already been run. Set your identity if you haven't globally:
git config user.name  "Your Name"
git config user.email "you@example.com"

git add -A
git status              # confirm .env is NOT listed — .gitignore excludes it
git commit -m "Initial commit: ElectroHub marketplace"

gh repo create electrohub --private --source=. --remote=origin
# or: create the repo on github.com first, then
#   git remote add origin git@github.com:<you>/electrohub.git

git push -u origin main
```

**What ends up in git** (everything except what `.gitignore` already excludes):
all source (`frontend/src`, `backend/`, `services/*/app`), every `Dockerfile`,
`docker-compose.yml` + `docker-compose.prod.yml`, `nginx/`, `caddy/`,
`database/*.sql`, `protos/`, the `.github/workflows/` you're reading about now,
`.env.example` (the template — safe, has no real values), and every `*.md`
doc. **Never `.env` itself** — it holds the real Postgres/JWT/RabbitMQ
secrets, and `.gitignore` already keeps it out. Double-check with
`git status` before every commit that touches config, not just this first
one.

If you'd rather keep the code private from Anthropic/GitHub entirely, that's
a call only you can make — a private repo (`gh repo create --private`) is the
right default for something with real user data flowing through it.

---

## Step 2 — point Vercel at the repo (frontend, no workflow file needed)

```bash
npm i -g vercel
vercel login
cd frontend
vercel link        # "Set up and deploy"? No — just link. Root Directory: frontend
```

Then in the Vercel dashboard (**vercel.com** → your project → Settings):

- **Git** → connect the same GitHub repo, production branch `main`. From now
  on every push to `main` triggers a production deploy automatically; every
  PR gets its own preview URL. This replaces `vercel --prod` from the manual
  flow in `DEPLOY_PLAN.md` Step 9.
- **Environment Variables** → `REACT_APP_API_URL` = `https://api.example.com`
  (your backend domain, https, no trailing slash). CRA inlines this at build
  time, so changing it later requires a redeploy — Vercel does that for you
  automatically since it rebuilds on every push anyway.

That's the entire frontend pipeline. No secrets, no YAML, no SSH — Vercel's
GitHub App is the trigger.

---

## Step 3 — point the backend workflow at your EC2 VM

Do the manual EC2 setup in `DEPLOY_PLAN.md` **once** (Steps 2–7: create the
VM, DNS, firewall, Docker, first `docker compose up -d --build`). After that
first manual deploy, the VM already has the repo cloned at `~/electrohub` and
a working `.env` — the workflow only ever fast-forwards it.

On the VM, make sure the deploy key can pull without a password prompt and
that the checkout is the one the workflow will `reset --hard`:

```bash
ssh ubuntu@<VM_IP>
cd ~/electrohub
git remote -v                 # should point at your GitHub repo
git status                    # should be clean — commit or stash anything local first
```

**Add three repo secrets** (GitHub repo → Settings → Secrets and variables →
Actions → New repository secret):

| Secret | Value |
|---|---|
| `EC2_HOST` | your domain, e.g. `api.example.com` (same as `PUBLIC_DOMAIN` in `.env` — the workflow's health check hits this over `https`, so it must resolve and have a valid cert, not a bare IP) |
| `EC2_USER` | `ubuntu` (or your AMI's default user) |
| `EC2_SSH_KEY` | the **private** key content that's authorized on the VM (`cat ~/.ssh/electrohub.key`) — paste the whole thing including the `BEGIN`/`END` lines |

Generate a **deploy-only** key rather than reusing your personal one, and add
only its public half to the VM's `~/.ssh/authorized_keys`:

```bash
ssh-keygen -t ed25519 -f ./deploy_key -N "" -C "github-actions-deploy"
ssh-copy-id -i ./deploy_key.pub ubuntu@<VM_IP>
# paste deploy_key's contents (the private one) into the EC2_SSH_KEY secret, then delete both local copies
```

From here, any push to `main` touching `backend/**`, `services/**`,
`nginx/**`, `database/**`, or either compose file redeploys the VM
automatically. A push that only touches `frontend/**` or docs skips this
workflow entirely (see the `paths:` filter in the workflow file) and only
triggers Vercel.

Trigger it by hand any time from **Actions tab → Deploy backend to AWS EC2 →
Run workflow**, without needing a code change.

---

## Why this shape and not ECS/EKS + CodePipeline

You asked for Docker/Kubernetes/Postgres "all in AWS" — worth being explicit
about the tradeoff instead of just picking one silently:

| | This pipeline (EC2 + GitHub Actions) | ECS Fargate + CodePipeline/CodeDeploy | EKS + Argo CD / Flux |
|---|---|---|---|
| Matches current compose file | Yes, as-is | No — needs task defs + an ALB per service | No — needs full k8s manifests/Helm chart |
| New CI complexity | 2 small YAML files | ECR push + task-def render + service update per service (6+ services) | a GitOps controller + manifests + image-update automation |
| Rollback | `git revert` + push | CodeDeploy blue/green (built-in, nicer) | `kubectl rollout undo` / Argo sync |
| Zero-downtime deploys | No — `up -d --build` briefly bounces containers | Yes — rolling/blue-green natively | Yes — rolling natively |
| Extra monthly cost | **$0** (just the EC2 box you already need) | ECS itself is free; you pay Fargate vCPU/GB + ALB (~$20) either way | **EKS control plane alone is $73/mo**, before any worker nodes |
| Right choice when | one team, one region, downtime of a few seconds during deploy is fine | you need real zero-downtime and already contracted 6 separate task defs | you need multi-region, autoscaling per-service, or you're standardizing on k8s org-wide |

**For where this project actually is — a demo/portfolio-scale marketplace —
EC2 + GitHub Actions is the right call.** ECS buys you zero-downtime deploys
for ~$20/mo more; EKS buys you the same plus more knobs for $73/mo more,
minimum, before you've served a single request. Move to one of those only
when a real availability requirement shows up, not preemptively — the
migration path (containers are already images; nothing here is EC2-specific
code) stays open either way.

If you do want to see the ECS or EKS version built out, say so explicitly —
it's a materially larger deliverable (task definitions or Helm charts, an
ECR push step, IAM roles for GitHub OIDC) and is worth its own pass rather
than bolting onto this one.

---

## Cost — the pipeline's own overhead on top of `DEPLOY_PLAN.md`

`DEPLOY_PLAN.md` §7-equivalent already covers hosting cost
(`~$65/mo` EC2 `t3.large` + Vercel free, or `~€6.49/mo` Hetzner). Automating
the deploy adds:

| Item | Cost |
|---|---|
| GitHub Actions, private repo | **Free** — 2,000 min/month included; this pipeline's jobs run in ~1–2 min combined per push, so you'd need ~1,000+ pushes/month to even approach the limit |
| GitHub Actions, public repo | **Free, unlimited** |
| GitHub repo itself | **Free** (private or public) |
| Vercel Git integration | **Free** on the Hobby plan — same tier you're already using |
| Deploy-only SSH key | **Free** — it's a keypair, not a service |
| **Total added by this pipeline** | **$0/mo** |

The pipeline doesn't change your hosting bill at all — it only automates the
`git pull && docker compose up -d --build` you'd otherwise run by hand over
SSH after every change.

---

## First real deploy checklist

1. `DEPLOY_PLAN.md` Steps 1–8 once, by hand — get the VM live with a real
   cert and a passing `/health` check.
2. This document's Steps 1–3 — push the code, connect Vercel, add the three
   GitHub secrets.
3. Make a trivial change (e.g. edit this file), push to `main`, watch
   **Actions tab** — `ci.yml` and, if you touched backend files,
   `deploy-backend.yml` should both go green.
4. Confirm Vercel's dashboard shows a new deployment from the same push.
5. From here: every `git push origin main` is your entire deploy process.
