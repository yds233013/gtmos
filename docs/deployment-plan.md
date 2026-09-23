# Deployment plan

Where to put a public GTMOS demo, what it costs, and exactly how to stand it up.

All pricing below was read from the vendors' own pages on **23 September 2026** and every figure carries
the URL it came from. Anything that could not be confirmed on a vendor page is marked **Unverified**
rather than filled in from memory; there are nine such items and they are listed in §7.

Read [`public-demo-safety.md`](public-demo-safety.md) first. Its P0 and P1 are prerequisites for
anything in this document, not follow-ups to it.

---

## 1 · What actually has to run

Worth establishing before comparing hosts, because it changes the shape of the bill.

| Component | Needed for a public demo? |
|---|---|
| **Postgres 16** | **Yes.** 73 MB at `SEED_ACCOUNTS=2000` (2,006 account rows). Nothing works without it. |
| **FastAPI** (`apps/api`) | **Yes.** |
| **Next.js 16** (`apps/web`) | **Yes.** A separate long-running Node process. |
| **Redis** | **Not architecturally**, but keep it on the recommended host — it is free there and the compose file wants it. See §5.4. |
| **RQ worker** | **Not architecturally.** Same. See §5.4. |
| **n8n** | **No.** Profile-gated in compose; not part of the web demo. |
| **dbt / `warehouse/`** | **No.** The API reads no table in the `analytics` schema at runtime — checked, not assumed. The warehouse is an offline artefact. |

So the irreducible unit is **three processes and a database**, two of which must be publicly reachable.
Every price below is computed against that, not against the full seven-service compose file — which
matters for the PaaS options, where each service is a line on the bill, and does not matter at all for
a single box, where the two optional containers are free.

One structural fact that matters for hosting choice: the Next app proxies the browser's `/api/v1/*`
calls to FastAPI server-side (`next.config.ts` rewrites), and every page is rendered per request —
`src/lib/api.ts` is `server-only` and calls `await connection()`, which opts every data page out of
prerendering. There is no static half to put on a CDN. Both processes are always-on, and every page
view costs a server render plus at least one API round trip, so **putting the frontend and the backend
on different hosts adds that round trip to every page load.**

---

## 2 · The options, honestly

### Render

| | |
|---|---|
| Free path | Web service $0 (512 MB, 0.1 CPU); Postgres $0 (256 MB, 1 GB storage) |
| Realistic paid path | Web (API) $7 + Web (frontend) $7 + Postgres Basic-256mb $6 = **$20/month** |
| Workspace fee | Hobby $0 |

Sources: [render.com/pricing](https://render.com/pricing), [render.com/docs/free](https://render.com/docs/free).

**Good at:** the least ceremony of any PaaS here. Dockerfile detection works, both images in this repo
build clean, and a `render.yaml` would describe the whole thing. Health checks, TLS and a subdomain are
automatic.

**What bites:**

- **The free Postgres expires after 30 days**, with a 14-day grace period before deletion. This was cut
  from 90 days and Render's own changelog records the change
  ([changelog](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90)).
  A CV link that works for a month and then serves a 503 is worse than no link. The free tier is
  therefore not usable for this; the $6 Basic-256mb is the real floor.
- **Free web services spin down after 15 minutes of no inbound traffic and take "about one minute" to
  cold start** ([docs/free](https://render.com/docs/free)). A stranger clicking a link from a CV will
  not wait sixty seconds, and they will not know why. This single property disqualifies the free
  compute tier for a portfolio demo more thoroughly than any cost consideration.
- Two web services, because the frontend and the backend are separate processes, so the $7 is really $14.
- Cron jobs bill per minute with a **$1/month minimum per cron service**
  ([docs/cronjobs](https://render.com/docs/cronjobs)) — small, but it means the reseed has a floor.

### Railway

| | |
|---|---|
| Hobby | **$5/month, including $5 of usage** |
| Rates | RAM **$10/GB/month**, CPU **$20/vCPU/month**, volumes $0.15/GB/month, egress $0.05/GB |
| Estimate here | **~$10–12/month** — *my arithmetic, see below* |

Sources: [railway.com/pricing](https://railway.com/pricing), [docs.railway.com/reference/pricing](https://docs.railway.com/reference/pricing).

**Good at:** no sleeping by default, so no cold start. Postgres and Redis are ordinary containers you
deploy from templates rather than separate priced products, and cron is a schedule on a service
(minimum interval 5 minutes, [docs](https://docs.railway.com/reference/cron-jobs)).

**What bites:**

- The estimate above is **Unverified**. Railway publishes rates but not the idle consumption of a
  Postgres or Redis container, so any monthly figure is a guess multiplied by a published rate. Three
  always-on containers at roughly 300 MB each comes out near $9–10 of usage against $5 included; that
  arithmetic is mine, not Railway's.
- **Usage-based billing on a public instance with no rate limiting is the wrong pairing.** Finding 6 of
  [`security-review.md`](security-review.md) records that GTMOS has no inbound rate limit, and §4.2 of
  `public-demo-safety.md` shows three ungated endpoints that each do full-dataset work per call. A
  crawler that finds one of them turns a $10 month into an open question. A fixed-price host does not
  have this failure mode.
- The "Free" plan is $0 with **$1/month of included usage**, which is not enough to run anything here;
  the free trial is $5 of one-time credit over 30 days.

### Fly.io

| | |
|---|---|
| Compute (from 1 Oct 2026) | shared-cpu-1x 256 MB **$2.19/month**; shared-cpu-2x 512 MB **$4.39/month** |
| Managed Postgres, cheapest | **Basic, shared-2x · 1 GB — $38/month** + $0.28/provisioned GB |
| Realistic total | **~$44–54/month** |

Sources: [fly.io/docs/about/pricing](https://fly.io/docs/about/pricing/), [fly.io/pricing-update](https://fly.io/pricing-update/), [fly.io/docs/mpg](https://fly.io/docs/mpg/).

**Good at:** genuinely cheap compute, real scale-to-zero (`auto_stop_machines = "stop"` is the `fly
launch` default, and a stopped machine costs only $0.15/GB of rootfs per 30 days), and the best
multi-region story of anything here — which this project does not need.

**What bites:**

- **Managed Postgres starts at $38/month**, which is five times the entire Hetzner bill for a demo
  database holding 73 MB. That single line makes Fly the most expensive option on this list.
- The cheap alternative is **Fly Postgres (unmanaged)**, which Fly's own documentation describes as
  something they *"are not able to provide support or guidance for"*
  ([docs/postgres](https://fly.io/docs/postgres/)). Running an unsupported database under a demo whose
  entire pitch is engineering judgement is a bad look, and the bad look is deserved.
- **Prices change on 1 October 2026**, eight days from now. Extra RAM goes from ~$5 to $6 per GB per
  month. Any figure quoted from the current table is about to be stale.
- **Unverified:** Fly's cold-start time for an auto-started machine, and the idle threshold before
  auto-stop. Neither number appears in their documentation, which matters because scale-to-zero is the
  feature that would have made Fly cheap.

### A single VPS — Hetzner Cloud, running the existing `docker compose`

| | |
|---|---|
| **CX23** (2 vCPU x86, 4 GB RAM, 40 GB NVMe) | **€5.49/month** + €0.50 IPv4 = **€5.99/month ≈ $6.87** |
| CAX11 (2 vCPU ARM, 4 GB, 40 GB) | €5.99 + €0.50 = €6.49/month ≈ $7.44 |
| Included traffic | **20 TB**, then €1.00/TB in the EU |
| Setup fee | None listed — **Unverified**, see §7 |

Sources: [hetzner.com/cloud/cost-optimized](https://www.hetzner.com/cloud/cost-optimized/); prices from Hetzner's own public price API (`website-price-api.hetzner.com/api/v1/products/CLOUD_132`, `CLOUD_111`, `CLOUD_21`), which is the endpoint the pricing page itself calls. EUR→USD at 1.1463 (ECB reference rate, 2026-09-22). Hetzner's own USD list prices are $6.49 + $0.60 = **$7.09**, and those are what you would actually be billed in USD.

Note that **CX22 no longer exists**; CX23 is the current equivalent at the same 2 vCPU / 4 GB / 40 GB.
ARM is currently the *more* expensive of the two, reversing the old CAX11/CX22 relationship.

**Good at:** everything this specific repository is shaped for. `docker-compose.yml` already defines
the whole stack with health checks, dependency ordering and the correct `API_INTERNAL_URL` build arg;
`make up` already works and is exercised daily. 4 GB of RAM runs all seven services with headroom.
Fixed price regardless of traffic. Postgres that does not expire, sleep, pause or get deleted. No cold
start ever.

**What bites:** you own it. TLS, a domain, OS patching, the firewall, backups, and being the only
person who will notice when it stops. There is no managed failover and one box is one point of
failure. Set against that: this is a portfolio demo, its uptime requirement is "works when a stranger
clicks a link", and a weekly `apt upgrade` and an unattended-upgrades unit is the whole operational
burden.

### Vercel for the frontend + a separate backend host

| | |
|---|---|
| Vercel Hobby | $0 |
| Vercel Pro | $20/month base, **$20 per developer seat** |
| Plus a backend host and a database | Render API $7 + Postgres $6 = $13 |
| Realistic total | **$13/month** on Hobby, **$33+/month** on Pro |

Sources: [vercel.com/pricing](https://vercel.com/pricing), [vercel.com/docs/plans/hobby](https://vercel.com/docs/plans/hobby), [vercel.com/docs/limits/fair-use-guidelines](https://vercel.com/docs/limits/fair-use-guidelines).

**Good at:** the Next.js build. Nothing else on this list will build and serve a Next 16 app as well,
and the Hobby allowances (100 GB data transfer, 1M function invocations, 4 CPU-hours active) are far
beyond what this demo will use.

**What bites:**

- **The Hobby plan's commercial-use restriction is a real question, not a technicality.** The Fair Use
  Guidelines say *"Hobby teams are restricted to non-commercial personal use only"*, and define
  commercial usage as *"any Deployment that is used for the purpose of financial gain of **anyone**
  involved in **any part of the production** of the project"*. The listed examples are all payment,
  advertising and affiliate cases, and a demo that exists to help its author get hired is not among
  them — but "financial gain of anyone involved in any part of the production" is broad enough that
  someone could read it that way. It is a grey area, it is Vercel's call and not yours, and the
  downside of being wrong is your demo going away at the least convenient moment. **Unverified:**
  whether Vercel treats a job-seeking portfolio as commercial. If this route is taken, the honest move
  is to pay for Pro rather than argue about it, and Pro at $20/seat makes it the second most expensive
  option here.
- **Hobby teams cannot connect projects to repositories owned by a Git organisation**
  ([docs/limits](https://vercel.com/docs/limits)). Fine if the repository is under a personal account,
  which it will be.
- **Vercel solves the easy half.** It cannot host FastAPI — functions cap at 300 s on Hobby and there
  is no long-running process — and it no longer offers first-party Postgres or Redis; Vercel Postgres
  was transitioned to Neon and databases are now bought through the Marketplace
  ([docs/marketplace-storage](https://vercel.com/docs/marketplace-storage)). So you still need a
  backend host and a database, and you have added a cross-provider network hop to *every* page render,
  because every page in this app is dynamic.

### The free managed databases, for completeness

Considered and rejected as the database behind any of the above:

| | Limit | Why it fails here |
|---|---|---|
| **Neon** free | 0.5 GB storage, 100 CU-hours/project/month, plan is *"permanent (not a trial)"* | **Suspends after 5 minutes of inactivity and this cannot be disabled on Free.** That is a cold start on the database as well as the app. ([neon.com/pricing](https://neon.com/pricing)) |
| **Supabase** free | 500 MB database, max 2 active projects | *"Free projects are paused after 1 week of inactivity."* A demo nobody clicks for eight days is a dead demo. ([supabase.com/pricing](https://supabase.com/pricing)) |
| **Render** free Postgres | 1 GB storage | Expires in 30 days. Covered above. |
| **Upstash** Redis free | 500K commands/month, 256 MB | Would be fine — but no Redis is needed. ([upstash.com/pricing/redis](https://upstash.com/pricing/redis)) |

The 73 MB dataset fits in all of them. The problem is never storage; it is that every free managed
database on the market now either suspends, pauses or expires, and the one property this demo needs
above all others is **that the link still works in six months.**

### Summary

| Option | Monthly | Cold start | Database risk | Ops burden |
|---|---:|---|---|---|
| **Hetzner CX23 + compose** | **~$7** | None | None — you own it | **Highest** |
| Railway Hobby | ~$10–12 *(Unverified)* | None | None | Low |
| Render (paid) | $20 | None | None | Lowest |
| Vercel Hobby + Render backend | $13 | None | None | Low, plus a licence question |
| Render (free) | $0 | **~60 s** | **Dies at 30 days** | Lowest |
| Fly.io + Managed Postgres | ~$44–54 | Unverified | None | Medium |

---

## 3 · Recommendation

**One Hetzner CX23, running the repository's existing `docker compose`, behind Caddy for TLS.
€5.99/month including the IPv4 address — about $7 — plus roughly $1/month for a domain.**

Four reasons, in the order they should persuade you.

**1 · The deployment artefact already exists and is exercised daily.** `docker-compose.yml` encodes the
whole topology: health checks on every service, `depends_on` with `condition: service_healthy`,
`alembic upgrade head && python -m gtmos.seed --if-empty` as the API's start command, and — the detail
that matters most — `API_INTERNAL_URL: http://api:8000` as a **build arg** on the web image, which is
correct precisely because both containers share a network. Deploying to a PaaS means taking that file
apart into three or four platform services and re-deriving every one of those relationships in a
dashboard. Deploying to a box means `git clone && make up`. For a project whose README tells readers to
run `make up`, hosting it any other way means maintaining two descriptions of the same system.

**2 · The database does not expire, sleep or pause.** Every managed free tier now fails on one of
those three, and the paid tiers that do not are $6–$38/month for a 73 MB database. On your own box it
is a container with a volume.

**3 · Fixed price, on a system with no rate limiting.** §4.2 of `public-demo-safety.md` shows three
ungated endpoints that each do full-dataset work per request. On a usage-billed host that is a bill;
on a fixed-price box it is at worst a slow afternoon. Given that the application's own security review
declines to add in-process rate limiting on the (correct) grounds that it belongs at the edge, the host
should be one where the absence of it is not also a financial exposure.

**4 · No cold start, ever.** The audience is a stranger who clicked a link once. Render's free tier
gives them a minute of white screen; Neon's free tier adds a database wake on top. That is the whole
impression, spent.

**The honest cost:** you become the operator. Budget an hour for the initial setup, then
`unattended-upgrades` and a monthly glance. If that is not wanted, the runner-up is **Railway Hobby at
roughly $10–12/month** — no cold start, no expiring database, and the closest thing to "it just works"
among the managed options. Render at $20 is the most polished and the most expensive of the sensible
three; its free tier is a trap and should not be used for this.

---

## 4 · Environment variables

Derived by reading every field of `Settings` in `apps/api/src/gtmos/config.py` and cross-checking
against `.env.example`. Pydantic maps each field to its upper-case name.

**Four settings fields have no line in `.env.example`** — `LOG_LEVEL`, `CLAY_WEBHOOK_SECRET`,
`CLAY_API_KEY` and `OUTBOUND_SEND_ENABLED`. They are read by the application regardless. Worth fixing
in `.env.example` before release.

### Backend (`apps/api`)

| Variable | Required? | Default | For the public demo |
|---|---|---|---|
| `ENV` | **Required** | `development` | **`production`** — makes an unset webhook secret fail closed (`webhook_service.py:139`) and makes `ADMIN_API_TOKEN` mandatory for admin routes |
| `DATABASE_URL` | **Required** | `postgresql+psycopg://gtmos:gtmos@localhost:56432/gtmos` | See the scheme warning below |
| `ADMIN_API_TOKEN` | **Required in production** | unset | 32+ random bytes. Without it the four admin routes return `503` when `ENV=production` |
| `WEBHOOK_SECRET` | **Required in production** | unset | 32+ random bytes. Without it, webhook deliveries are rejected when `ENV=production` |
| `READ_ONLY` | **Required** | `false` | **`true`.** The edge check in `main.py` that refuses every write; P1 of [`public-demo-safety.md`](public-demo-safety.md). Reads, the ICP preview, the routing simulator and the copilot still work |
| `QUEUE_BACKEND` | Optional | `inline` | Leave at `inline`. Compose overrides it to `redis`; override it back |
| `REDIS_URL` | Optional | unset | Leave unset |
| `CORS_ORIGINS` | Optional | `["http://localhost:3010","http://127.0.0.1:3010"]` | Not needed — the browser never calls the API cross-origin; Next proxies server-side |
| `LOG_LEVEL` | Optional | `INFO` | `INFO`. Not in `.env.example` |
| `SEED_ACCOUNTS` | Optional | `2000` | `2000`. Lower it to shrink memory and reseed time |
| `LLM_MODEL` | Optional | `claude-opus-5` | Irrelevant while the LLM is off |
| **`ANTHROPIC_API_KEY`** | Optional | unset | **Never set on a public instance.** §4.4 of the safety document: `use_llm` comes from the request body, so a key here means any anonymous visitor can spend money |
| **`LLM_ENABLED`** | Optional | `false` | **`false`** |
| **`HUBSPOT_ACCESS_TOKEN`** | Optional | unset | **Never set** |
| `HUBSPOT_LIVE_WRITES_ENABLED` | Optional | `false` | **`false`** |
| `HUBSPOT_WEBHOOK_CLIENT_SECRET` | Optional | unset | Leave unset |
| `APOLLO_API_KEY` | Optional | unset | Leave unset |
| `CLAY_API_KEY` | Optional | unset | Leave unset. Not in `.env.example` |
| `CLAY_WEBHOOK_SECRET` | Optional | unset | Leave unset. Not in `.env.example` |
| `OUTBOUND_SEND_ENABLED` | Optional | `false` | `false`. Documents a boundary; nothing reads it on a send path, because there is none. Not in `.env.example` |

**The `DATABASE_URL` scheme is a real trap.** `db.py` passes the string straight to
`create_engine` with no normalisation, and `psycopg[binary]` (psycopg **3**) is the only driver
installed. Managed providers hand out `postgres://…` or `postgresql://…`, and SQLAlchemy resolves the
bare `postgresql://` form to psycopg **2**, which is not installed — the app will fail at startup with
a driver error that reads like a networking problem. The URL must begin **`postgresql+psycopg://`**.
On the recommended single-box deployment this is already correct, because compose sets it explicitly.

### Frontend (`apps/web`)

| Variable | Required? | Notes |
|---|---|---|
| `API_INTERNAL_URL` | **Required at build time *and* at run time** | See below |
| `PORT` / `HOSTNAME` | Set by the Dockerfile | `3000` / `0.0.0.0` |
| `NEXT_TELEMETRY_DISABLED` | Optional | Set to `1` in the Dockerfile |

**`API_INTERNAL_URL` is needed twice, for two different reasons, and this is the single most likely
thing to be got wrong on a PaaS.** `src/lib/api.ts` reads it at run time for server-component fetches.
But `next.config.ts` reads it when the rewrite table is built, and Next bakes the result into the build
output — verified by inspecting the built artefact, where
`.config._originalRewrites.afterFiles[0].destination` contains the literal
`http://127.0.0.1:8010/api/v1/:path*` from the machine that ran the build. Set it only at run time and
the browser's `/api/v1/*` calls will be proxied to whatever host was compiled in, which is a failure
that looks like an intermittently broken UI rather than a misconfiguration.

The compose file gets this right already (`args: API_INTERNAL_URL: http://api:8000` **and**
`environment: API_INTERNAL_URL: http://api:8000`). On Render or Vercel you must remember to mark it as
available at build.

### Not read by the application

`GTMOS_DB_PORT`, `GTMOS_REDIS_PORT`, `GTMOS_API_PORT`, `GTMOS_WEB_PORT` are compose host-port
overrides. `N8N_*` and `GTMOS_BASE_URL` belong to the optional n8n container.
`TEST_DATABASE_URL` is read only by `apps/api/tests/conftest.py`.

---

## 5 · Standing it up

### 5.1 The box

```bash
# Hetzner Cloud console: create a CX23 in NBG1/FSN1/HEL1, Ubuntu 24.04, SSH key, no extra volume.
# Then, as root:
adduser --disabled-password --gecos "" gtmos && usermod -aG docker,sudo gtmos
apt update && apt install -y docker.io docker-compose-v2 unattended-upgrades
systemctl enable --now docker

# Firewall: only 22, 80, 443. Nothing else — in particular NOT 5432, 6379, 8010, 3010 or 5678.
ufw default deny incoming && ufw allow 22,80,443/tcp && ufw --force enable
```

The firewall line is not boilerplate. The compose file publishes Postgres on the host port and, under
the `n8n` profile, an unauthenticated n8n on 5678. Neither may be reachable from the internet.

### 5.2 The application

```bash
su - gtmos && git clone https://github.com/<you>/gtmos.git /srv/gtmos && cd /srv/gtmos
cat > .env <<'EOF'
ENV=production
READ_ONLY=true
ADMIN_API_TOKEN=<openssl rand -hex 32>
WEBHOOK_SECRET=<openssl rand -hex 32>
QUEUE_BACKEND=inline
LLM_ENABLED=false
HUBSPOT_LIVE_WRITES_ENABLED=false
EOF
chmod 600 .env
docker compose up --build -d              # db, redis, api, worker, web — n8n is profile-gated and stays off
```

**No edit to `docker-compose.yml` is needed, and that is the point of choosing this host.** Bring up
everything except n8n, which does not start unless `--profile n8n` is passed.

Two things about the `.env` above. `QUEUE_BACKEND=inline` in it will be **ignored** by the `api` and
`worker` services, because the compose file sets `QUEUE_BACKEND: redis` in their `environment:` blocks
and `environment:` takes precedence over `env_file:`. That is fine and is why Redis and the worker stay
— see §5.4. The line is left in the file so that a `docker compose run` or a shell invocation that does
not inherit the service environment still defaults to something sane.

`ENV`, `READ_ONLY`, `ADMIN_API_TOKEN` and `WEBHOOK_SECRET` are *not* overridden by the compose file, so
those four take effect as written.

### 5.3 Migrations

**Already handled, and there is nothing to add.** The API service's command is:

```
alembic upgrade head && python -m gtmos.seed --if-empty && uvicorn gtmos.main:app --host 0.0.0.0 --port 8000
```

It runs inside the API container at every start, after `depends_on: db: condition: service_healthy`,
so the database is accepting connections before Alembic touches it. `alembic upgrade head` is
idempotent; `--if-empty` makes the seed a no-op once a workspace exists. A restart, a redeploy and a
first boot all do the right thing.

Alembic gets its URL from the application settings, not from `alembic.ini` — `migrations/env.py:12`
does `config.set_main_option("sqlalchemy.url", get_settings().database_url)`, and the URL in
`alembic.ini` is the deliberate placeholder `postgresql+psycopg://set-via-DATABASE_URL`.

On a PaaS this same command becomes a **release command** (Render: "Pre-Deploy Command"; Railway: a
custom start command). Do not run migrations in a build step: the build container generally cannot
reach the database.

### 5.4 Redis and the worker — not needed

`QUEUE_BACKEND=inline` is the default in `config.py`, and `workflow_engine.dispatch` reads it:

```python
if settings.queue_backend == "redis" and settings.redis_url:
    ...defer to the RQ worker...
execute_run(db, run.id)
```

Inline means a workflow run executes in the request that triggered it. For a demo that is correct, and
with P1's read-only flag in place nothing triggers a run anyway — there is no in-app scheduler; n8n
does the scheduling, and n8n is not deployed.

So: **no Redis, no worker, two containers saved.** `/health/ready` skips its Redis check entirely when
`REDIS_URL` is unset, so the health endpoint stays green rather than degraded.

The cost is small and worth naming: the Operations page will report `queue: {backend: "inline",
redis_configured: false}`, which is true and slightly undersells the architecture. A reader who wants
to see the queue runs `make up` locally, which still brings up Redis and the worker. That is the right
place for it — a queue with nothing in it is not a demo of a queue.

### 5.5 Build and run commands

| | Build | Run |
|---|---|---|
| **API** | `docker build -t gtmos-api apps/api` | `alembic upgrade head && python -m gtmos.seed --if-empty && uvicorn gtmos.main:app --host 0.0.0.0 --port 8000` |
| **Web** | `docker build --build-arg API_INTERNAL_URL=http://api:8000 -t gtmos-web apps/web` | `node server.js` (Next standalone output, port 3000) |

Without Docker, on a PaaS with native runtimes:

| | Build | Run |
|---|---|---|
| **API** | `cd apps/api && uv sync --frozen --no-dev` | `cd apps/api && uv run uvicorn gtmos.main:app --host 0.0.0.0 --port $PORT` |
| **Web** | `cd apps/web && npm ci && npm run build` | `cd apps/web && npm start` |

Python must be **3.13 or newer** (`requires-python = ">=3.13"`); Node **24** is what the Dockerfile and
CI use.

### 5.6 Health checks

| Endpoint | What it does | Use it for |
|---|---|---|
| **`/health/ready`** | `select 1` against Postgres, pings Redis if `REDIS_URL` is set. Returns **`503`** when degraded. | **The platform health check.** This is the real one. |
| `/health/live` | Returns `{"status":"ok"}`. No database. | Liveness / restart probes. |
| `GET /` (web) | The rendered overview page. | The frontend's health check, as in its Dockerfile. |

**There is no `/health`.** Configuring a platform probe against it will produce a 404 and a service
that is restarted forever.

Both are at the application root, not under `/api/v1` — the routers are mounted with that prefix and
the health routes are not.

### 5.7 TLS

Nothing in the repository terminates TLS. Add Caddy as a fourth service:

```
demo.example.com {
    reverse_proxy web:3000
}
```

Caddy obtains and renews a Let's Encrypt certificate automatically. The API stays on the internal
Docker network with no published port — the browser only ever talks to the Next server, which proxies
`/api/v1/*` itself. **Do not publish the API port.** It is not a security boundary (the proxy forwards
every method), but it removes one way to reach the API without going through anything you control, and
it is where a rate limiter goes if P4 is ever applied.

Cost of a domain: **Unverified** — registrar-dependent, typically $10–15/year for a `.com`.

---

## 6 · Demo reset

### Why it is not optional

There are two reasons, and the second is the one that is easy to miss.

**Safety.** Even with P1's read-only flag, a reset is the recovery path if the flag is ever off, and it
cleans up after a live walkthrough where someone clicked things.

**The data goes stale on its own.** `seed/generator.py:2830`:

```python
anchor = anchor or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
```

Every date in the dataset is generated relative to the moment of seeding. The overview's 90-day cohort
funnel, the "last 30 days" signal counts, the routing SLA window, the experiment window — all of them
are computed against wall-clock now. Six months after a single seed, **the rolling windows are empty
and the demo renders as a dead system with 2,006 accounts and no activity.** A reseed is what keeps a
link on a CV showing a live-looking product a year later. That is a product requirement, not a
housekeeping one.

### How

```cron
17 4 * * * cd /srv/gtmos && docker compose exec -T api python -m gtmos.seed --reset >> /var/log/gtmos-reset.log 2>&1
```

`make reset` is the local equivalent (`cd apps/api && uv run python -m gtmos.seed --reset`); inside the
container the module is on the path directly. Daily at a quiet hour is right with P1 in place; hourly
if writes are ever enabled.

**Cost on the recommended host: zero.** It is a minute of CPU on a box you already pay a flat rate for.
On Render it would be a cron service at $0.00016/minute with a **$1/month minimum**
([docs/cronjobs](https://render.com/docs/cronjobs)) — about a dollar a month, which is the minimum, not
the usage. On Railway it is a cron schedule on a service, minimum interval 5 minutes.

### What to know about it

- **It takes about 54 seconds** at 2,000 accounts (measured in
  [`phase2-baseline.md`](phase2-baseline.md)), and it begins by truncating every table. For that minute
  the app serves a partially-populated dataset. Schedule it at 04:00 and accept it, or take the site
  down behind Caddy for the duration if that matters — it does not.
- **The result is byte-identical content, not a different random world.** Fixed RNG seeds and `uuid5`
  ids throughout (`seed/generator.py:75`), so the workspace id, the flagship account id and every deep
  link survive a reset. A bookmarked URL keeps working. Screenshots stay accurate. Documented figures
  stay true.
- **The dbt marts in the `analytics` schema go stale**, because the source ids change — `make
  warehouse-refresh` exists for exactly this. It does not matter for the deployment, because the API
  reads no `analytics` table at runtime. If the warehouse is ever served from the box, add
  `dbt build --full-refresh` to the same cron line.
- The seeded database is **73 MB**; a 40 GB NVMe disk is not a constraint.

---

## 7 · Marked Unverified

Nine claims that could not be confirmed on a vendor page and are therefore not asserted above.

1. **Railway's monthly cost for this stack (~$10–12).** Their rates are published; the idle RAM and CPU
   consumption of a Postgres or Redis container is not. The dollar figure is rates × my assumption.
2. **Fly.io cold-start time for an auto-started machine.** No figure in their documentation.
3. **Fly.io's idle threshold before auto-stop.** The docs say only that the stop loop "runs every few
   minutes".
4. **Fly.io shared-cpu-1x at 512 MB after 1 October 2026.** Not a listed preset in the new table; the
   ~$3.69/month figure is arithmetic from the published base plus the published per-GB RAM rate.
5. **Hetzner setup fee.** No page states "no setup fee". Their price API returns no `setup` field for
   `CLOUD_*` products where it does return one for dedicated servers — a strong inference, not a quote.
6. **Hetzner CX23/CAX11 stock at NBG1/FSN1/HEL1.** The pricing page markup currently renders these rows
   with an "unavailable" string, which may be a genuine stock-out or a pre-hydration placeholder.
   **Check in a browser before committing to this recommendation**; if CX23 is out of stock, CX33 or a
   different location is the fallback and the price changes.
7. **Whether Vercel treats a job-seeking portfolio as commercial use** under the Hobby plan's
   restriction. The wording is broad and the interpretation is Vercel's.
8. **Whether Render's free web-service tier requires a payment method on file.** Not checked, and it
   does not affect the recommendation, which uses no Render free tier.
9. **Domain registration cost.** Registrar-dependent.

One figure that was checked and came back different from the common assumption: **Render's free
Postgres expires after 30 days, not 90.** Their changelog records the cut. Anything still saying 90 is
stale.

---

## 8 · The bill

| Line | Monthly |
|---|---:|
| Hetzner CX23, 2 vCPU / 4 GB / 40 GB NVMe | €5.49 |
| Primary IPv4 address | €0.50 |
| Domain (amortised, **Unverified**) | ~€1 |
| Postgres, Redis, TLS certificate, cron, 20 TB traffic | €0 |
| **Total** | **≈ €7 / $8** |

Set against: Railway ~$10–12 (Unverified), Vercel Hobby + Render backend $13, Render $20, Fly.io
~$44–54.

The prerequisite is not on this bill and is the larger cost: **P0 and P1 of
[`public-demo-safety.md`](public-demo-safety.md), about three hours.** Without them, this plan puts 24
ungated mutating endpoints on the open internet with a link to them from a CV.
