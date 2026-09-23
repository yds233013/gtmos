# Public demo safety

What it would actually take to put GTMOS on the open internet at a URL anyone can click.

This document does not redesign anything. It checks, against the code and against the running
application, what the seven safety requirements below already hold, and then says plainly where they
do not. Findings 4 and 5 of [`security-review.md`](security-review.md) are where this starts; they are
not where it ends, because neither of them counts the surface.

Everything here was verified against the API running on `localhost:8010` at version `0.1.0`, whose
OpenAPI document reports **90 operations across 86 paths**, and against the source at commit `fcd131c`.

---

## 1 · Verdict

| # | Requirement | Status |
|---|---|---|
| 1 | No external writes | **Satisfied**, structurally |
| 2 | No emails or messages | **Satisfied**, absolutely — there is no client to send with |
| 3 | No live CRM mutation | **Satisfied by default**, two variables away from not being |
| 4 | No LLM spending | **Satisfied by default**, two variables away from *unmetered anonymous* spending |
| 5 | No feature requires a secret to render | **Satisfied** |
| 6 | No destructive action reachable | **Not satisfied by the routing table** — mitigated by P1 |
| 7 | No uncontrolled workflow execution | **Not satisfied by the routing table** — mitigated by P1 |

Requirements 1 to 5 are genuinely held, and held by structure rather than by discipline. Requirements
6 and 7 are not held by the routes themselves, and the gap is larger than the security review's prose
implies: it is not "the admin gate is a no-op", it is that **24 mutating endpoints have no gate to be
a no-op of** — even in the most hardened configuration the route decorators are capable of.

The audit in §3 is an audit of the routing table, and it remains true of it. What closes the gap is the
edge check described in §5 (P1), which now exists in `main.py` and is off unless `READ_ONLY=true`. That
is deliberate: local development and the test suite must keep every write.

---

## 2 · What is genuinely satisfied

### 2.1 No external writes, no emails, no messages

There is no SMTP client, no mail API client, no sequencer client and no messaging client anywhere in
the repository. This was checked by searching the whole of `apps/api` and `apps/web` for `smtplib`,
`sendgrid`, `mailgun`, `postmark`, `boto3`, `twilio`, `slack_sdk`, `salesloft`, `outreach.io` and
`send_email`. Zero matches that are not an unrelated substring (`responses.items()`, `EMAIL_STATUSES`).

The only outbound HTTP clients in the codebase are three, all `httpx`, all against a module-constant
base URL: `integrations/hubspot.py` (`api.hubapi.com`), `integrations/clay.py` (Clay's API base) and
`integrations/enrichment_providers.py` (Apollo). Each is constructed only when its credential is
present. With no credentials configured — the shipped state — **no code path in the application
constructs an outbound HTTP client at all.**

`domain/deliverability.py` states the position in its own docstring: *"GTMOS has no mailbox, no SMTP
client and no sending integration, and it never will: the approval queue terminates in a hand-off."*
That is not a comment making a promise the code does not keep. It is a description of the code.

`outbound_send_enabled` in `config.py` defaults to `False` and, notably, is **not read by any
send path** — because there is none. It is read in exactly two places: `routes/integrations.py`, which
hardcodes `False` into the workspace response, and the web settings panel, which renders that value.
It documents a boundary rather than enforcing one, which is the correct shape when the boundary is
enforced by absence.

### 2.2 No live CRM mutation

`services/crm_sync.py:59`:

```python
def get_adapter(db, workspace_id) -> CrmAdapter:
    s = get_settings()
    if s.hubspot_access_token and s.hubspot_live_writes_enabled:
        return RealHubSpotAdapter(s.hubspot_access_token.get_secret_value())
    return DemoHubSpotAdapter(db, workspace_id)
```

Both conditions are required, and `hubspot_live_writes_enabled` defaults to `False` in `config.py`
with `.env.example` pinning it to `false` explicitly. The demo adapter writes to a
`simulated_crm_objects` table in the local database and every sync it performs is labelled
`is_simulated: true` in its own response — verified by calling the endpoint, which returned
`"is_simulated":true, "records_considered":850`.

The single-condition version of this — a token alone triggering live behaviour — is the classic form
of this bug, and the code does not have it.

### 2.3 No LLM spending

Same shape, `integrations/llm.py:124`:

```python
def get_research_writer(settings) -> ResearchWriter | None:
    if settings.llm_mode != "live":
        return None
```

and `llm_mode` is `"live"` only when `anthropic_api_key` **and** `llm_enabled` are both set.
`llm_enabled` defaults to `False`. With the writer `None`, `research_service.generate_research` uses
the deterministic generator and never imports the `anthropic` client. The live workspace endpoint
confirms it in the product: `"llm_mode":"demo"`.

**But read §4.4 before deploying.** This one has a live wire attached to it.

### 2.4 No feature requires a secret in order to render

Checked by probing the running instance with nothing configured beyond the database. Every read
surface the UI depends on returns `200`:

`/api/v1/workspace`, `/api/v1/integrations`, `/api/v1/governance`, `/api/v1/analytics/overview`,
`/api/v1/accounts`, `/api/v1/workflows`, `/api/v1/operations`, `/api/v1/experiments`, `/api/v1/drafts`,
`/api/v1/data-quality/issues`, `/api/v1/webhooks/events`.

The pages that *describe* integrations compute their mode from the running configuration
(`_current_mode` in `routes/integrations.py`) rather than failing when a credential is absent: an
unconfigured HubSpot renders as `demo`, an unconfigured Apollo as `disabled`. That is the behaviour you
want — the page still has something true to say.

The one thing that does need provisioning is Postgres with the seeded dataset. `/health/ready` reports
`database: ok` and degrades to `503` without it, so the failure is at least legible.

### 2.5 The kill switches

Three switches on the workspace row — `automation_enabled`, `outbound_enabled`, `crm_writes_enabled` —
read from the database on every check rather than cached, so a pause takes effect on the next action
instead of on the next deploy. They are enforced at three call sites: `crm_sync.py:168`,
`crm_sync.py:437` and `outreach_service.py:206`. A blocked action raises `Halted`, which the app maps
to `423 Locked` with the operator's reason attached.

The design is right. The problem is §4.3: on a public instance without an admin token, **the switches
are operable by the public**, which turns a safety control into a vandalism target.

---

## 3 · The reachability audit

This is the part the existing review gestures at without counting. Every mutating operation in the
OpenAPI document was extracted and classified by the gate actually attached to it.

**36 of the 90 operations use POST, PUT, PATCH or DELETE.** They fall into four classes.

| Class | Gate | Count | Effective in the shipped demo? |
|---|---|---:|---|
| A | `require_admin` | 4 | **No** — no-op unless `ADMIN_API_TOKEN` is set |
| B | `require_admin_for_live_writes` | 2 | **No** — no-op unless a HubSpot token *and* live writes are on |
| C | HMAC signature (`webhook_service.verify_request`) | 5 | **No** — unless a webhook secret is set, or `ENV=production` |
| D | **Nothing** | 25 | n/a — there is nothing to be effective |

Three of the twenty-five in class D are POST-shaped reads that mutate nothing — `/icp/preview`,
`/routing/simulate`, `/copilot/ask`. They matter later, in §5, because a blunt mitigation kills them.
That leaves **22 endpoints that mutate the database and have no authorisation of any kind, in any
configuration**:

| | Endpoint | What it changes |
|---|---|---|
| 1 | `POST /accounts/{id}/rescore` | Recomputes and persists an ICP score |
| 2 | `POST /accounts/{id}/enrich` | Runs the enrichment waterfall, writes fields and provenance |
| 3 | `POST /accounts/{id}/route` | Assigns an owner |
| 4 | `POST /accounts/{id}/stage` | Moves lifecycle stage, writes a stage transition |
| 5 | `POST /accounts/{id}/committee/recompute` | Rebuilds the buying committee |
| 6 | `PUT /accounts/{id}/committee/{role}` | Overrides a committee role |
| 7 | `DELETE /accounts/{id}/committee/{role}` | Clears an override |
| 8 | `POST /accounts/{id}/research` | Generates and persists a research report |
| 9 | `POST /accounts/{id}/drafts` | Generates up to three message drafts |
| 10 | `POST /accounts/{id}/opportunities` | Creates an opportunity, amount up to $100,000,000 |
| 11 | `POST /accounts/{id}/workflows/{key}/run` | Executes or enqueues a workflow run |
| 12 | `POST /opportunities/{id}/stage` | Moves a deal stage |
| 13 | `POST /signals` | Injects an arbitrary signal |
| 14 | `POST /research/{id}/review` | Approves or rejects a research report |
| 15 | `POST /drafts/{id}/transition` | Moves a draft to `approved` / `ready` / `rejected` |
| 16 | `PUT /drafts/{id}` | Rewrites a draft's subject and 5,000-character body |
| 17 | `PATCH /workflows/{key}` | Enables or disables a workflow |
| 18 | `POST /workflow-runs/{id}/retry` | Re-executes a run |
| 19 | `POST /data-quality/scan` | Full-dataset scan, writes issues |
| 20 | `POST /data-quality/issues/{id}/remediate` | **Merges contacts, merges accounts, suppresses emails** |
| 21 | `POST /data-quality/issues/{id}/ignore` | Dismisses an issue |
| 22 | `POST /webhooks/events/{id}/replay` | Re-runs a stored delivery through its processor, unsigned |

Confirmed by calling three of them against the running instance with no credential at all:

```
POST /api/v1/accounts/{id}/rescore                    → 200
POST /api/v1/data-quality/scan                        → 200  (scanned the full dataset)
POST /api/v1/integrations/hubspot/reverse-etl/run     → 200  ("records_considered":850)
```

The third is the interesting one: it is a class-B endpoint, so it *looks* protected, and it ran
anonymously against 850 accounts.

For contrast, the two gates that *are* configured locally both held:

```
PUT  /api/v1/icp          (no Authorization)  → 401 {"detail":"admin token required"}
POST /api/v1/webhooks/n8n (no signature)      → 401 signature check failed: missing token header
```

### Exposure by configuration

| Configuration | Mutating endpoints reachable with no credential |
|---|---:|
| Shipped demo (`ENV=development`, no secrets) | **33 of 36** |
| `ENV=production` + `ADMIN_API_TOKEN` + webhook secrets | **24 of 36** |

The second row is the headline. Setting every security variable the application supports still leaves
twenty-four mutating endpoints open to anyone with `curl`, because twenty-two of them were never wired
to a gate and two are wired to a gate that only engages when HubSpot live writes are on.

One genuinely good detail found while checking this: `webhook_service.py:139` upgrades an unconfigured
webhook secret from `not_configured` (accepted) to `invalid` (rejected) when `ENV=production`. That is
a real fail-closed behaviour, and it is why the second row closes class C.

---

## 4 · What a hostile visitor could actually do

Answering the question in the terms it was asked.

| Can they… | | Why |
|---|---|---|
| Reset or wipe the data? | **No** | There is no seed or truncate endpoint. `TRUNCATE` exists only in `python -m gtmos.seed --reset`, a CLI entry point with no HTTP surface. |
| Merge contacts and accounts? | **Yes** | `POST /data-quality/issues/{id}/remediate` dispatches to `merge_contacts` / `merge_accounts` / `suppress_email`. Ungated. |
| Approve drafts? | **Yes** | `POST /drafts/{id}/transition` with `target: "approved"`. Ungated. |
| Rewrite a draft's text first? | **Yes** | `PUT /drafts/{id}`, 5,000 characters, ungated. |
| Trigger syncs? | **Yes** | `POST /integrations/hubspot/reverse-etl/run`, 850 accounts per call, gate is a no-op. |
| Replay webhooks? | **Yes** | `POST /webhooks/events/{id}/replay`. No signature check on this path — event ids come from the ungated `GET /webhooks/events` listing. |
| Enqueue workflows? | **Yes** | `POST /accounts/{id}/workflows/{key}/run`, once per account per workflow key, subject only to idempotency-key suppression. |
| Disable every workflow? | **Yes** | `PATCH /workflows/{key}` with `is_enabled: false`. |
| Pause the whole system? | **Yes, unless `ADMIN_API_TOKEN` is set** | `POST /governance/pause`, with a 500-character attacker-chosen reason string that the Operations and Settings pages then display. |
| Rewrite the ICP definition? | **Yes, unless `ADMIN_API_TOKEN` is set** | `PUT /icp` re-grades every account in the product. |
| Sign every action as someone else? | **Yes** | `X-GTMOS-Actor` is accepted on faith if it is under 200 characters and contains `@`. Finding 5. |
| Send an email or a message? | **No** | §2.1. There is nothing to send with. |
| Write to a real CRM? | **No**, in the shipped config | §2.2. |
| Spend money on model calls? | **No**, in the shipped config — **see §4.4** | §2.3. |
| Read a secret back out? | **No** | `get_secret_value()` appears exactly once outside the integration clients, in `deps.py`, to compare the admin token. Nothing under `api/routes` touches it. |

### 4.1 The worst realistic outcome

Not data loss — the dataset survives, because nothing can truncate it over HTTP. The worst outcome is
**a demo that silently stops being a demo.**

A twenty-line script walking `GET /accounts` and posting to `/rescore`, `/enrich`, `/stage` and
`/opportunities` can, within minutes, put every account in `closed_lost`, attach a few thousand
$100,000,000 opportunities, and make the overview page — the first screenshot in the README, the one
with the $5.6M pipeline figure — render a number that is obvious nonsense. The remediation endpoint can
then merge the flagged duplicate pairs, which is not reversible within the running dataset; merged
records carry `merged_into_id` and do not come back.

Nobody is harmed. But the artefact is the argument, and a visitor arriving after the vandal sees a
broken argument with no way to tell it was vandalised.

### 4.2 The cheap denial of service

Finding 6 records that there is no rate limiting. What it does not record is how expensive the
individual requests are. Three ungated endpoints each do full-dataset work per call:

- `POST /icp/preview` scores up to 2,000 accounts.
- `POST /data-quality/scan` runs eleven rules across the whole dataset.
- `POST /integrations/hubspot/reverse-etl/run` considers 850 accounts.

The engine is created with SQLAlchemy's default pool — 5 connections plus 10 overflow (`db.py:17`,
no `pool_size` override). A handful of concurrent calls to any of those will exhaust it, and on the
512 MB instance sizes a free hosting tier gives you, the container will be OOM-killed before that.
This is not a sophisticated attack; it is what a single enthusiastic crawler does by accident.

### 4.3 The kill switches cut both ways

`POST /governance/pause` sets all three switches off and records `paused_by` and `paused_reason`. On a
public instance with no `ADMIN_API_TOKEN`, a visitor can pause the system and leave a 500-character
message that the product then displays as an operator's reason. React escapes it, so this is not
script injection — it is graffiti on the operations page, which for a portfolio artefact is worse in
the ways that matter and better in the ways that do not.

`ADMIN_API_TOKEN` must be set on any public instance. It costs nothing and closes four routes.

### 4.4 The one live wire

`POST /accounts/{id}/research` takes `use_llm` **from the request body**:

```python
class ResearchBody(BaseModel):
    use_llm: bool = True
```

In the shipped configuration this is inert, because `get_research_writer` returns `None` regardless. But
if a public instance is ever given `ANTHROPIC_API_KEY` and `LLM_ENABLED=true` — for instance, to make
the research surface "more impressive" — then **any anonymous visitor can issue unlimited billed model
calls, one per request, with no rate limit and no spend cap.** 2,006 accounts, each re-researchable
without limit.

The rule for a public instance is therefore absolute and costs nothing to follow: **`LLM_ENABLED`
stays `false` and `ANTHROPIC_API_KEY` is never set in the hosting environment.** The demo generator is
what the README already claims is running; keeping it is honest as well as safe.

The same reasoning applies to `HUBSPOT_ACCESS_TOKEN`. The moment both HubSpot variables are set on a
public host, the two class-B endpoints become live CRM writers *and* acquire a real gate on the same
line of code — which means the failure mode is not "unprotected live writes", it is "live writes
protected by a token, reachable by anyone who does not have it" returning 401. Safe, but pointless.
Do not set it.

---

## 5 · Recommendation

In priority order. Each item states what it costs and what it takes away, because a mitigation whose
cost is not stated is a mitigation someone will reverse later without knowing what they are buying.

### P0 — Environment discipline · 5 minutes · breaks nothing

Set on the public instance:

```
ENV=production
ADMIN_API_TOKEN=<32+ random bytes>
WEBHOOK_SECRET=<32+ random bytes>
LLM_ENABLED=false          # and never set ANTHROPIC_API_KEY
HUBSPOT_LIVE_WRITES_ENABLED=false   # and never set HUBSPOT_ACCESS_TOKEN
```

Closes class A (4 routes) and class C (5 routes), and `ENV=production` makes the webhook secret
mandatory rather than optional — the fail-closed path at `webhook_service.py:139`.

**What breaks:** nothing a visitor touches. The ICP editor's save button and the three governance
controls will return 401 from the browser; the ICP *preview* still works, which is the part of that
page worth looking at. If those buttons should not appear at all, that is P2.

**What it does not do:** it leaves 24 mutating endpoints open. P0 alone is not sufficient and should
not be mistaken for sufficient.

### P1 — One read-only flag, checked in one place · 1–2 hours · this is the fix

**This has landed.** `config.py` gained `read_only: bool = False`, and `main.py` gained a
`enforce_read_only` middleware guarded by two module constants:

```python
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_POST_ALLOWLIST = frozenset({
    "/api/v1/icp/preview",
    "/api/v1/routing/simulate",
    "/api/v1/copilot/ask",
})
```

Any request whose method is not safe and whose path is not allow-listed returns `403` with a message
telling the visitor to clone the repository and run `make up`. Set `READ_ONLY=true` in the hosting
environment and leave it unset everywhere else, so local development and the test suite are untouched.

A middleware rather than a dependency, deliberately: a dependency has to be attached to every router
and the next route added will be the one that forgets — which is how this gap appeared in the first
place. A method check at the edge cannot be forgotten, and it covers the four webhook paths and the
replay path without naming them.

The allow-list is the whole subtlety. Without it, the three best interactive surfaces in the product —
the ICP preview ("change this threshold, watch 2,006 accounts re-grade"), the routing simulator and the
copilot — go dead, and those are precisely what a visitor should be allowed to play with, because none
of them writes a row. Three literal strings, and they must be kept in step with the routes.

`.env.example` documents the flag, pinned to `false`, and `tests/integration/test_read_only.py` pins
the behaviour in eight cases: every allow-listed path still exists in the routing table, each one
accepts a POST with the flag off and on, reads are unaffected, a write is refused with the explanation
attached, the webhook paths are refused too, and — the case that matters most to everyone who is not
deploying this — **the flag is off by default**, so nothing about local development or the rest of the
suite changes.

**What breaks, precisely:** all 22 ungated mutating endpoints plus the two reverse-ETL endpoints return
403. In the UI that is: Rescore, Enrich, Route, Change stage, Recompute committee, Override role,
Generate research, Approve/reject research, Generate drafts, Edit draft, Approve/reject draft, Create
opportunity, Move deal stage, Run workflow, Retry run, Enable/disable workflow, Run data-quality scan,
Remediate issue, Ignore issue, Replay webhook, and both reverse-ETL buttons.

That is most of the verbs in the product, and it is worth being honest that a read-only GTMOS is a
weaker demo than a live one. What survives is still substantial and is still the argument the README
makes: 2,006 scored accounts with per-rule breakdowns, the signals timeline, the pipeline and
attribution analytics, the experiment with the rejected winner, `/integrations` with its "1 of 4"
honesty, the approvals queue as a *read*, the operations and webhook-delivery surfaces, the data-quality
issue list, the ICP preview, the routing simulator and the copilot. The three surfaces
`phase3-handoff.md` names as "the argument" — `/integrations`,
`/experiments/provocative-subject` and the scoring evaluation — are all reads.

### P2 — Tell the visitor, in the product · 2–4 hours · improves the demo

A 403 that a button produces with no explanation reads as a broken app, which is a worse outcome than
the vandalism it prevents. Two things:

1. A persistent banner: *"Public read-only demo. Write actions are disabled — `git clone` and
   `make up` to use them."* The workspace endpoint already returns mode flags; adding `read_only` to
   that payload is one line, and the web app already reads it.
2. Disable the write buttons rather than letting them fail. `settings/integrations-section.tsx`
   already conditions on `outbound_send_enabled`, so the pattern exists.

This is presentation, not safety, but it is the difference between "considered" and "broken".

### P3 — Scheduled reseed · 1 hour · the belt to P1's braces

Even with P1, keep this. It is the answer to "what if the read-only flag is ever off", and it also
resets the demo after a live walkthrough where someone clicked things.

`python -m gtmos.seed --reset` truncates every table and reloads the deterministic dataset. Measured at
**~54 s** in `docs/phase2-baseline.md` at 2,000 accounts; the resulting database is **73 MB**. The
schedule should be hourly if writes are enabled, daily if P1 is in place.

Two things worth knowing. The seed is deterministic, so a reset restores byte-identical demo content
rather than a different random world — screenshots and documented figures stay true. And the dbt marts
in the `analytics` schema *do* go stale after a reset, because the source ids change, but this does not
matter for the web demo: the API reads no table in the `analytics` schema at runtime. That was checked,
not assumed. The warehouse is an offline artefact.

Cost depends on the host and is covered in [`deployment-plan.md`](deployment-plan.md); on any platform
with a cron primitive it is a scheduled one-off command against the same image, and the compute is a
minute a day.

### P4 — Rate limiting at the edge · 30 minutes, host-dependent

Finding 6 argues correctly that this does not belong in application code. It does belong in front of
a public instance. Something crude is sufficient: 60 requests per minute per IP. The three
full-dataset endpoints in §4.2 are the reason, and P1 closes two of the three (`/icp/preview` stays
open by design). **Unverified:** whether the recommended host in `deployment-plan.md` offers this
without a paid add-on — checked per-platform there.

### Considered and rejected

**A per-visitor sandbox** — a database schema or a container per session, so writes are real but
isolated. This is the right answer for a product and the wrong answer for this. It is days of work, it
multiplies the hosting bill by the number of concurrent visitors, and it introduces a new failure mode
(session leakage) into a repository whose whole argument is that it does not ship things it has not
verified.

**Session auth in front of the demo** — a login wall on a portfolio piece defeats the purpose. The
person you want to reach it is a stranger who clicked a link from a CV and will not create an account.

**Wiring `require_admin` onto all 24 routes** — the correct production fix, named as such in
Finding 4, and the wrong fix here. It is twenty-four edits, each of which can be forgotten on the
twenty-fifth route, and it produces exactly the read-only behaviour that P1 produces in one block of
code. Do it when there is a session to derive identity from; do P1 now.

---

## 6 · Summary for the release checklist

| | |
|---|---|
| Requirements 1–5 | Satisfied, structurally, and re-verified here |
| Mutating operations | 36 of 90 |
| With no gate of any kind | 22 |
| With a gate that is a no-op in the demo configuration | 2 |
| **Reachable with no credential, best case** | **24** |
| **Reachable with no credential, as shipped** | **33** |
| Can a visitor destroy data? | Not the dataset; yes, individual merges, irreversibly |
| Minimum safe public configuration | P0 + P1 |
| Effort for that minimum | Under three hours |
