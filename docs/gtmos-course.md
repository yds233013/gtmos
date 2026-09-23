# GTM engineering from zero, taught through GTMOS

This is a crash course in go-to-market engineering for a software engineer who has never worked in
revenue operations, taught entirely through the code in this repository. Twenty modules, each with the
same six parts: what the thing is, why a business pays for it, a worked example on GTMOS's own demo
data, where it lives in this codebase, the question an interviewer asks about it, and words you could
actually say in reply.

**How to use it.** Read a module, then open the file it cites and the page it names. The point is not to
memorise definitions — an interviewer will spot a recited definition in one sentence — but to be able to
say *"here is the decision, here is the trade-off, here is what we chose and what it cost."* That is the
whole job.

**Ground rules on honesty, which are also the ground rules for the interview.** Every number below was
read from the running application or the database on 2026-09-23, not copied out of prose. Where a
document in this repository disagrees with the running system, this course follows the system and says
so. And on integrations, the claims are strict:

- **n8n** is verified by execution. It runs locally in Docker on `n8nio/n8n:2.40.5`; five of its six
  workflows have genuinely fired against this API.
- **HubSpot** runs on a simulated adapter. The live adapter is written and has never touched a real
  portal.
- **Clay** and **PostHog** are contracts exercised locally only. No account exists with either vendor.
- **Nothing here has ever sent an email or a message to anyone**, and no paid model call was made
  building it.

Say those four sentences in that order and you have already outperformed most portfolio demos.

---

## Module 1 — What GTM means

**What it is**

Go-to-market is everything a company does between "we have a product" and "a stranger pays us for it":
choosing who to sell to, reaching them, convincing them, closing, and measuring which of those actions
worked. The people are marketing, sales development (SDRs, who start conversations), account executives
(AEs, who close), customer success, and **revenue operations** (RevOps) — the function that owns the
systems, definitions and data the other three run on.

A **GTM engineer** is the software engineer inside that function. The distinguishing skill is not writing
integrations; it is knowing which decisions belong in versioned code, which belong to a vendor, and which
belong to a human. Most GTM stacks fail not because an API broke but because nobody could say what the
score meant, so nobody trusted it, so everyone went back to a spreadsheet.

The vocabulary you will hear in the first ten minutes of any interview: **ARR** is annual recurring
revenue, the yearly subscription run-rate — the number every other number gets justified against. **ICP**
is ideal customer profile, the written description of who you sell to. **MQL** (marketing-qualified lead)
is a person marketing thinks is worth a call; **SAL** (sales-accepted lead) is one sales agreed to take;
**SQL** (sales-qualified lead) is one that survived a discovery conversation. Those three exist so that
marketing and sales can argue about a number instead of about each other.

**Why it exists**

Because attention is the scarce resource, not prospects. A rep can run perhaps 40 meaningful touches a
day, and a mid-market AE closes maybe two or three deals a month. On this demo dataset there are 2,006
accounts and, over the last 90 days, 72 meetings and 62 opportunities created for $5,624,000 of pipeline.
If a rep spends a week on accounts that were never going to buy, that is not a rounding error — it is
roughly 2% of the quarter's selling capacity, gone, and it recurs every week until someone fixes the
list. GTM as a discipline exists to make that allocation deliberate rather than accidental.

**Example**

Sentinel AI sells reliability, evaluation and observability infrastructure for AI agents. Its GTM
question is never "who could use this" — almost any company shipping an LLM feature could — but "who will
buy it this quarter, and why now". Kestrel Analytics, an 850-person AI/ML platform company in San
Francisco, raised a $120M Series C twelve days ago, launched an agent product called Kestrel Copilot,
hired a VP of AI, has 14 open AI/ML roles, and already has four people using Sentinel's free tier. That
combination — fit plus a forcing event plus product behaviour — is what GTM work is for. Finding it in a
list of 2,006 is the engineering problem.

**How GTMOS implements it**

GTMOS is the judgement layer that sits between the tools. The whole loop is visible in one API call:
`GET /api/v1/analytics/overview`, served by `apps/api/src/gtmos/services/analytics.py:46`, which reports
the 90-day funnel from accounts sourced through to won revenue. Crucially, every number it emits has a
written definition in the metric dictionary at `apps/api/src/gtmos/domain/metrics.py:28` — formula,
denominator and the caveat that stops it being misread — because most RevOps arguments turn out to be
definition arguments in disguise ("is that reply rate per send or per account?").

**Common interview question**

*"What does a GTM engineer actually do that a backend engineer doesn't?"*

**Good answer**

"The code is ordinary — Python, Postgres, webhooks. What is different is that the requirements are
contested. A backend engineer is usually handed a spec; a GTM engineer is handed a disagreement between
marketing and sales about what a qualified lead is, and part of the job is turning that into something
testable. So I optimise for explainability over cleverness. In GTMOS every account score decomposes into
named components with the sentence that justifies each one, because a rep who cannot see why an account
scored 98 will ignore the score, and an ignored score is worse than no score — you paid for it and you
still got a spreadsheet. The trade-off is real: a hand-weighted heuristic is almost certainly less
accurate than a learned model would be with enough labelled outcomes. I took the explainable version
first and then measured it honestly, which is how I know it is only barely better than random on this
data."

---

## Module 2 — CRM fundamentals

**What it is**

A CRM (customer relationship management system) is the shared memory of the revenue team. Three objects
matter: **Company** (called Account in Salesforce), **Contact** (a person), and **Deal** (called
Opportunity — a specific chance to sell a specific amount by a specific date). They are joined by
**associations**, and almost every CRM disaster is an association or a duplicate.

Two stage systems run in parallel and are constantly confused. **Lifecycle stage** is a CRM-wide
classification of your relationship with a record — subscriber, lead, MQL, SQL, opportunity, customer.
**Funnel or deal stage** tracks progress through one specific motion. A company can be a customer
(lifecycle) and simultaneously in "discovery" on an expansion deal (deal stage). Mixing them up
double-counts revenue in every board deck that follows.

**Why it exists**

Without a CRM the state of a deal lives in one person's inbox and leaves the company when they do. With a
badly run CRM it lives in three duplicate records, and the rep who calls the prospect has none of the
context that the rep who emailed them last week wrote down. Duplicates are the expensive failure: they
split activity history, cause two reps to contact the same buyer in the same week, and quietly corrupt
every conversion rate you report, because the denominator is wrong.

**Example**

Kestrel Analytics currently sits at funnel stage `opportunity` with lifecycle `opportunity`, and carries
one open deal — "Kestrel Analytics: Agent Reliability Platform", $180,000, stage `discovery`, opened
2026-09-19. If a rep tried to mark the account `won` without that deal being closed, GTMOS refuses:
winning is only reachable from `opportunity`. If a rep tried to move it backwards to `engaged` because
the champion went quiet, GTMOS also refuses — a deal that stalls is lost or stays where it is, because a
funnel you can walk backwards through produces conversion rates above 100%.

**How GTMOS implements it**

The stage vocabulary is `FUNNEL_STAGES` at `apps/api/src/gtmos/models/crm.py:27` (prospect → contacted →
engaged → qualified → meeting → opportunity → won/lost). The rules are pure functions:
`check_funnel_transition` at `apps/api/src/gtmos/domain/pipeline.py:37` allows skipping forward, forbids
going backward except into `lost`, treats won/lost as terminal unless explicitly recycled, and requires
an open opportunity before `won`. `FUNNEL_TO_LIFECYCLE` at `apps/api/src/gtmos/domain/pipeline.py:19`
derives the lifecycle a funnel stage implies (engaged → MQL, qualified → SQL) and returns `None` for
`lost`, because losing a deal does not un-qualify a company. Transitions go through
`apps/api/src/gtmos/services/crm_service.py:16` and land on `POST /api/v1/accounts/{account_id}/stage`,
which writes a `StageTransition` row — the same rows the funnel and the scoring backtest both read, so
the two can never disagree.

**Common interview question**

*"What's the difference between lifecycle stage and deal stage, and why does anyone care?"*

**Good answer**

"Lifecycle is about the relationship, deal stage is about one transaction. A customer renewing is
lifecycle 'customer' and deal stage 'negotiation' at the same time. People care because reporting breaks
when you conflate them: if you drive your funnel off lifecycle, an expansion deal looks like a new logo,
and if you drive it off deal stage, a company with three open deals counts three times. In GTMOS they are
separate columns with separate transition rules, and lifecycle is forward-only while the funnel allows
skipping forward but not going backward. The caveat I would flag is that forward-only lifecycle is
HubSpot's default and it is genuinely annoying in practice — a mis-set stage needs an admin to unwind. I
kept it because the alternative, letting stages float, makes every historical conversion number
unreproducible, and I would rather have a rigid model I can audit than a flexible one I cannot."

---

## Module 3 — HubSpot

**What it is**

HubSpot is a CRM plus a marketing suite — email, forms, sequences, workflows, reporting — and for
companies under a few hundred people it is usually the CRM, because it is dramatically cheaper to
administer than Salesforce. Its object model is Companies, Contacts, Deals, Tickets, plus custom objects,
joined by typed associations. Its API is a REST v3 surface with batch endpoints that accept at most 100
records per call.

Three HubSpot-specific facts separate people who have integrated with it from people who have read about
it. First, **`domain` is not a unique property on Company**, and HubSpot's own documentation says records
created through the API are not deduplicated on it — so you cannot use it as a batch-upsert key, and if
you try to upsert on it anyway you manufacture duplicates. Second, **private apps sign webhooks with the
v1 scheme, not v3**, which catches almost everybody. Third, **association type IDs 1, 2, 5 and 6 are the
*primary* variants** — writing 1 when you meant "just link these two" silently sets the contact's primary
company, which is the field a lot of territory logic and reporting keys off.

**Why it exists**

Reps live in a CRM. Sequences, tasks, calls, forecasting, mobile, permissions — all of it exists and none
of it is differentiating to rebuild. The moment your custom system becomes where reps work, you own a CRM
and you will lose: you will spend the next two years shipping a worse mobile app instead of shipping
judgement.

**Example**

Sentinel AI wants Kestrel's score, tier and next best action visible on the HubSpot company record so the
AE sees it without switching tabs. GTMOS pushes `gtmos_icp_score: 98`, `gtmos_intent_score: 96`,
`gtmos_score_grade: A`, `gtmos_account_tier: "Tier 2: Enterprise"`, the last signal and its timestamp,
and `gtmos_next_best_action`, keyed on `gtmos_account_id` — a custom property GTMOS created with
`hasUniqueValue: true`. Name and domain go **only on the first push**, the one that creates the record;
every push after that carries `gtmos_*` fields and nothing else, because a rep may have corrected the
name, and overwriting a rep's correction once is enough to lose the team's trust in the integration
permanently. (All of this runs against the simulated adapter. Kestrel's `hubspot_company_id` is `null`.)

**How GTMOS implements it**

`apps/api/src/gtmos/integrations/hubspot.py:42` is `ID_PROPERTY`, the upsert key per object type:
companies on `gtmos_account_id`, contacts on `email`, deals on `gtmos_opportunity_id`. The reasoning is
in the module docstring at the top of the same file. `BATCH_LIMIT = 100` at line 40 is the documented
ceiling. `ASSOCIATION_TYPES` at line 93 carries the primary-variant trap in a comment rather than leaving
a bare integer in a payload. Two adapters implement one protocol: `DemoHubSpotAdapter`, which writes to a
`simulated_crm_objects` table and injects deterministic simulated 429s so the retry path is always
exercised, and `RealHubSpotAdapter`, which has never run against a portal. Inbound signature verification
handles v1, v2 and v3 in `apps/api/src/gtmos/integrations/signatures.py:87`. The mapping is served as
data at `GET /api/v1/integrations/hubspot/mapping`.

**Common interview question**

*"Why wouldn't you upsert companies on domain?"*

**Good answer**

"Two reasons, and the API one is the one that bites first. HubSpot's batch upsert requires the
`idProperty` to have uniqueness enforced, and `domain` doesn't — their docs are explicit that companies
created via the API aren't deduplicated on it. So the call is rejected, or worse, you write with a
different endpoint and quietly create parallel records. The second reason is that domain isn't an
identity anyway: subsidiaries share one, companies rebrand, and holding companies have a dozen. So GTMOS
creates its own custom property with `hasUniqueValue: true`, stores the account UUID in it, and keys
every write on that — which makes replay safe, because re-running a sync updates instead of duplicating.
The cost is real and I would raise it unprompted: on a first live run, existing HubSpot companies have no
`gtmos_account_id`, so you create parallel records unless you backfill first by exporting, matching on
domain, and re-importing. That backfill is the actual go-live risk, not the code."

---

## Module 4 — Enrichment and Clay

**What it is**

**Enrichment** is buying the facts about a company or person that you do not have: headcount, industry,
funding, technologies in use, a verified work email. **Firmographics** are company facts (size, sector,
geography, revenue); **technographics** are the tools they run.

A **waterfall** is the pattern that makes enrichment affordable. For each field, you ask providers in a
defined order and stop at the first confident answer, so you pay for one lookup rather than five. The
order is per-field, because the best source for headcount is rarely the best source for tech stack.

**Clay** is the tool that productised this. It looks like a spreadsheet — each row a company, each column
a data source, a formula, or an agent — and its real product is the *provider network* behind those
columns, not the spreadsheet. You are buying the fact that someone else negotiated forty data contracts.

**Why it exists**

Coverage and cost. No single vendor knows every company; the best one might cover 70% of your list, and a
waterfall over several gets you materially higher coverage for less than buying them all. The failure you
are guarding against is silent: enrichment quietly overwrites a correct human-entered headcount with a
confident wrong one, that moves the company into a different size band, the size band changes the
territory, and now a strategic account is sitting in the SDR queue. Nothing errors. You find out in QBR.

**Example**

Kestrel Analytics' provenance shows `employee_count: 850` from `crm_import` at confidence 0.87, and
`ai_team_size: 64` from `demo_hiring` at 0.72. Suppose a re-enrichment run returns 1,400 employees from a
provider at 0.90 confidence. That is a 65% gap — large enough to move Kestrel from the `enterprise` band
into `strategic`, which changes the routing rule that fires. GTMOS does not take the higher-confidence
answer. It keeps 850, records the disagreement, and raises it as a `provider_conflict` data-quality
issue. Across the demo workspace there are currently **15 open provider conflicts** of exactly this kind,
and the Stack Inspector reports that for **9** of them the rejected answer lands in a different segment
band or industry tier — meaning nine accounts' owners and grades are resting on which provider was asked
first.

**How GTMOS implements it**

`run_waterfall` at `apps/api/src/gtmos/domain/enrichment.py:303` walks positions across the per-field
order in `DEFAULT_WATERFALL` (`apps/api/src/gtmos/integrations/enrichment_providers.py:218`), batching
fields that share a provider at the same position into one paid call and caching the whole response for
the run. The subtle part is `detect_conflict` at `apps/api/src/gtmos/domain/enrichment.py:246`: because a
provider call returns every field it supports, a call made at position 2 for one field usually carries a
free second opinion on a field already resolved at position 0, and those observations would otherwise be
thrown away. `values_disagree` at line 206 filters the noise — a 15% numeric tolerance, and tech stacks
count as disagreeing only when each provider sees something the other denies, because coverage
differences are not contradictions. `apply_conflict` at line 279 then refuses to overwrite an existing
value on a contested answer. Clay enters through the same policy at
`apps/api/src/gtmos/services/clay_service.py:511`; the boundary contract is served at
`GET /api/v1/integrations/clay/contract`, which reports `verified_against_live_clay: false` about itself.

**Common interview question**

*"Two enrichment providers disagree about a company's headcount. What do you do?"*

**Good answer**

"First I decide whether it is a disagreement at all. 240 versus 247 is the same fact measured a month
apart, and flagging that trains everyone to ignore flags — GTMOS uses a 15% tolerance before it will even
look. If it is material, the instinct is to take the higher confidence, and I think that is wrong.
Confidence is a provider's opinion of itself, and the two vendors are usually answering slightly
different questions — one legal entity versus the whole group. So GTMOS keeps the value that is already
there, stores the rejected answer with the provider that gave it, and raises a data-quality issue for a
human. That is deliberately a worse experience than silently picking a winner, and I would defend it: the
alternative is that an account changes segment, and therefore owner, because of a 0.05 confidence
difference nobody saw. The honest cost is a queue — there are 15 open right now — and if nobody works the
queue, the policy degrades into 'always keep the stale value'."

---

## Module 5 — Automation and n8n

**What it is**

n8n is an open-source workflow automation tool: a visual canvas of nodes — triggers, HTTP requests, code,
conditionals — that runs on a schedule or a webhook. Think Zapier, self-hostable and far more capable.
Every GTM team has thirty small automations ("when a form comes in, post it to Slack and add a task")
that are individually not worth an engineer's week, and this is where they live.

**Why it exists**

Two reasons, and the second is the important one. First, the integration long tail: nobody is going to
build a bespoke connector for the webinar tool. Second, **ownership** — a RevOps person needs to change
the wiring without waiting for a sprint. That is a political fact as much as a technical one. If every
change needs an engineer, the automation stops being maintained and the team goes back to CSV exports.

The corresponding failure mode is business logic sprawling onto the canvas, where it cannot be
unit-tested, cannot be code-reviewed, and is invisible to your audit log. The dividing line GTMOS uses:
**anything that decides revenue lives in versioned code; anything that moves bytes between systems lives
in n8n.** A scoring change should be reviewable in a diff. Adding a Slack notification should not need
one.

**Example**

Workflow 05 in this repository receives a HubSpot-shaped event array, normalises it, and forwards it to
GTMOS — and deliberately does *not* implement its own deduplication. It could: n8n has static data. It
would be wrong the first time two deliveries raced or the container was redeployed. Instead the batch is
forwarded untouched and GTMOS's unique constraint on `webhook_events.idempotency_key` does the work. That
was verified by execution: the same batch was delivered three times with `attemptNumber` 0, 2 and 3 (the
third with the array order reversed), and GTMOS recorded one event whose `duplicate_count` went 0 → 1 →
2.

**How GTMOS implements it**

Six workflow definitions live in `integrations/n8n/`, version-controlled JSON with explicit top-level
`id` fields so `n8n import:workflow` upserts rather than duplicating. Five have been executed against the
running API; `04-crm-update-to-rescore.json` calls `api.hubapi.com` directly and is reported as **not
executed** for want of a token. The dedupe that makes it safe is
`apps/api/src/gtmos/services/webhook_service.py:91`, `idempotency_key_for`, which hashes a *stable* body:
`RETRY_VOLATILE_KEYS` at line 64 strips `attemptNumber`, `retryCount` and `deliveryId` first. That
constant exists because of a real bug — HubSpot retries never deduplicated at all, since its payload is a
JSON array with an incrementing attempt counter, so every retry hashed differently. Signed deliveries
land on `POST /api/v1/webhooks/n8n`. Over the last seven days the Operations page reports 70 inbound
webhook events with **60 duplicates absorbed**.

**Common interview question**

*"You already have a workflow engine. Why also run n8n?"*

**Good answer**

"Because they solve different problems and conflating them is how you end up with scoring logic in a Code
node that nobody can test. GTMOS's engine runs GTM semantics — enrich, rescore, find the committee,
research, draft, route, sync — with idempotency keys, persisted step state, row-locked execution and dead
letters. n8n runs plumbing: receive this webhook, reshape it, forward it, every hour check a diff. The
test I use is: would a reasonable revenue leader want to argue with this logic? If yes, it needs to be
explainable, versioned and diffable, so it belongs in code. If it is just moving bytes, put it on the
canvas where an operator can change it without a deploy. The honest cost of running both is a second
system to operate — n8n prunes executions after fourteen days, which is precisely why the error workflow
writes its failures into GTMOS rather than trusting n8n's execution list as the record of record."

---

## Module 6 — Product-led GTM and PostHog

**What it is**

Product-led growth (PLG) means the product itself does the qualifying: people sign up, try it, invite
colleagues, and hit a limit — all before anyone from sales speaks to them. A **PQL** (product-qualified
lead, or account) is one whose *usage* says they are ready for a conversation.

PostHog is open-source product analytics: event capture, session replay, feature flags, and — the part
that matters for B2B — **group analytics**, which attributes events to a company rather than only to a
user. Without group analytics you cannot answer "how many people from this company are active", which is
the only question a B2B GTM team is asking. Note that group analytics is a paid add-on; this is a real
constraint on any design that assumes it.

**Why it exists**

Because in a product-led business, usage is the strongest and earliest buying signal, and it arrives
before any form is filled. A team that connected the product to their production model provider and
pushed real traffic is further along than one that downloaded a whitepaper — and if nobody calls them,
they either churn quietly or buy the smallest possible plan. Both outcomes cost real money and neither
shows up as a lost deal.

The mistake almost everyone makes is defining a PQL as a single event. "Viewed pricing" fires constantly:
competitors check it, candidates check it, your own reps check it. One signup is an individual; a team is
a budget.

**Example**

Kestrel Analytics currently qualifies on breadth and depth at once: four distinct users active in the
14-day window, `integration_activated` fired (they connected a production integration), `usage_threshold`
crossed (real traffic through the free tier), and repeated pricing views — which GTMOS collapsed into one
signal titled "Viewed pricing 5 times in 7 days" rather than five separate ones. The composite score
clears the bar, one `usage_threshold` signal is written with source `gtmos:pql`, and the
`pql-to-ae` workflow fires. It fires **once per account per ISO week**, not once per event, which is the
difference between an alert and background noise a rep learns to mute.

**How GTMOS implements it**

The rule is at `apps/api/src/gtmos/domain/pql.py`. `CRITERIA` at line 50 is the weighted composite: three
or more distinct users 25 points, a second user 10, connected a production integration 30, crossed the
usage threshold 25, viewed pricing 10. `PQL_THRESHOLD = 55` at line 39, deliberately set above the
largest single criterion so **no one criterion can qualify an account alone**. The ordering encodes an
opinion worth defending: integration is the heaviest because it has switching costs behind it, and
pricing is the lightest because a rep checking a competitor looks identical. `window_ref` at line 191 is
the weekly dedupe key. On the ingestion side, `distinct_product_users` at
`apps/api/src/gtmos/services/product_events.py:191` counts on the resolved contact where there is one and
the raw `distinct_id` otherwise — refusing to count unmatched users would systematically under-qualify
exactly the accounts worth calling. PostHog-shaped payloads arrive at `POST /api/v1/webhooks/posthog` and
map to signal types via `EVENT_SIGNAL_MAP` at `apps/api/src/gtmos/integrations/posthog.py:63`.

Verification status: this path is exercised continuously with locally generated traffic in PostHog's
documented shape. **No PostHog account exists, and no event has ever arrived from real PostHog.**

**Common interview question**

*"How would you define a PQL?"*

**Good answer**

"At the account level, as a composite over a window, weighted toward acts with switching costs, and fired
once. Concretely, in GTMOS: three or more distinct users in fourteen days is 25 points, connecting a
production integration is 30, crossing the usage threshold is 25, and viewing pricing is only 10 —
because pricing views are cheap to fake and a competitor looks identical to a buyer. The threshold is 55,
which is above the largest single criterion on purpose, so nothing qualifies on one fact. And it
deduplicates per account per week, because an account that stays qualified shouldn't page someone every
day. The caveat is that none of those weights is calibrated — they're a defensible opinion, not a fitted
model. To know whether they're right I'd need outcomes and a holdout: contact a random sample of
non-qualifying accounts too, and compare. I can't do that here because this system deliberately sends
nothing."

---

## Module 7 — ICP and segmentation

**What it is**

The **ICP** (ideal customer profile) is the written, structured description of who you sell to:
industries, size band, regions, technologies, the personas who buy, and — the part people forget —
explicit exclusions. It is a company-level statement. A **persona** is the person-level counterpart.

**Segmentation** is the coarser cut used for operations rather than targeting: which accounts get an
enterprise AE, which get an SDR, which get self-serve. It is usually headcount or revenue banding, and it
is the input to routing, quota and coverage models.

**Territory** is the third term in the family: the slice of the market one rep owns, typically by
geography, segment, industry, or a named list.

**Why it exists**

An ICP that lives in a slide deck is a preference; an ICP that lives in a validated data structure is a
system input. The difference is testable change. When someone proposes "let's also go after healthtech",
you want to preview the grade movement before you commit, not discover in six weeks that you quietly
diluted the A list.

Exclusions are the underrated half. Sanctioned countries are a compliance requirement, not a preference,
and an account below your minimum size is not a low-priority lead — it is a lead your pricing cannot
serve, and letting it score 40 instead of being excluded means a rep will eventually work it.

**Example**

Sentinel's ICP: core industries AI/ML Platforms, Developer Tools, Data Infrastructure and B2B SaaS;
adjacent (half credit) Fintech, Healthtech, Cybersecurity, E-commerce Software and Martech; size band
100–10,000 with a sweet spot of 250–5,000 and a hard minimum of 25; primary region NA, secondary EMEA.
Excluded: Government and Nonprofit as industries, and KP, IR, SY, CU as countries. On the current
dataset that produces 2,006 accounts of which **49 are grade X** — excluded outright rather than scored
low — and a segment split of 177 strategic, 674 enterprise, 886 mid-market, 236 smb. Kestrel at 850
employees lands in `enterprise` (the band is 500–1,999) and inside the fit sweet spot, so it takes the
full 12 of 12 size points.

**How GTMOS implements it**

`ICPDefinition` at `apps/api/src/gtmos/domain/icp.py:89` is a Pydantic model, so the ICP is validated
data rather than free text an LLM interprets. `default_icp()` at line 148 is Sentinel's actual profile.
Two validators earn their place: `_known_signals` at line 114 rejects an unknown signal type and — more
importantly — **rejects a disqualifying signal configured as a positive one**, so a typo cannot make
"laid off half the company" raise an account's score; and `_sum_to_100` on `CategoryWeights` at line 22
refuses a weight set that does not add up, which keeps the score interpretable as points out of 100.
Segmentation is a separate, blunter function: `segment_for` at
`apps/api/src/gtmos/seed/profiles.py:260`, ≥2,000 strategic, ≥500 enterprise, ≥100 mid-market, else smb.
Editing the ICP goes through `PUT /api/v1/icp`, and `POST /api/v1/icp/preview` shows the grade
distribution a change would produce **before** you save it.

**Common interview question**

*"How would you build an ICP, and how would you know it was right?"*

**Good answer**

"I'd start from closed-won and closed-lost, not from aspiration — what do the deals we actually won have
in common, and what do the ones that died in procurement have in common. That gives industries, a size
band and usually a technographic marker. Then I'd write it as structured data with explicit exclusions,
because 'too small' and 'sanctioned country' are different from 'low priority' and should not be a low
score, they should be a hard stop. In GTMOS the ICP is a validated object and there's a preview endpoint
that shows the grade distribution a change would produce before you save it, which is what makes the
argument concrete instead of theoretical. On knowing it's right: I'd be careful. The ICP selects who gets
contacted, so measuring it against conversion is circular — you only see outcomes for accounts the ICP
approved. The only clean answer is a small randomised holdout on the target list, and I'd budget about 5%
for it."

---

## Module 8 — Signals

**What it is**

A signal is an observed, timestamped fact that changes *when* or *whether* an account is likely to buy. A
funding round, an executive hire, a job posting that names your problem, a pricing-page visit, a
competitor going live. Signals are the difference between "this company fits" and "call them this week".

Three properties make a signal taxonomy useful rather than decorative:

- **Half-life.** A funding round is worth acting on for about a quarter; a pricing-page visit is stale in
  a fortnight. If both decay at the same rate, your "hot" list is full of last spring's news.
- **Polarity.** A taxonomy where every observation is encouraging cannot tell you to stop, and "stop
  working this account" is the cheapest recommendation a GTM system can make.
- **Dedupe.** The same real-world event arrives from three feeds. Without a stable key you score it three
  times.

**Why it exists**

Timing is most of outbound. The same message to the same person lands differently the week after their
company raised money and the week after it announced layoffs. Reps are already doing this — five browser
tabs of news alerts and LinkedIn — and doing it badly, inconsistently, and only for the accounts they
already like.

**Example**

GTMOS ships 19 signal types, of which 6 are disqualifying. Compare the half-lives: `funding_round` 90
days, `executive_hire` 120, `ai_hiring_surge` 45, `pricing_page_visit` 14, `usage_threshold` 21. Now the
negatives: `competitor_adopted` 180 days ("not permanent — renewals come round — but the near-term window
is closed"), `champion_departed` 60, and `unsubscribed` **365 days**, because an unsubscribe is
compliance, not preference, and forgetting it in a month is how you end up in a spam folder. Each
negative carries the action it implies: layoffs say "pause outbound and re-enrich", champion departed
says "multithread immediately: the replacement has no context and no commitment".

On Kestrel, the funding round observed 12 days ago is still worth 6.18 of its 7 available points — 90-day
half-life, so 12 days costs it about 9%. The `tech_adoption` signal from 45 days ago is down to 2.82 of 5.

**How GTMOS implements it**

`SIGNAL_TYPES` at `apps/api/src/gtmos/domain/signals.py:32` is the catalogue: key, scoring category,
default strength, half-life, description, whether it is negative, and the action it implies. `decay_factor`
at line 205 is plain exponential decay — `0.5 ** (age_days / half_life)` — with future timestamps clamped
so clock skew from a feed cannot inflate a score. `signal_dedupe_key` at line 211 hashes
`(signal_type, account_key, source_ref)` so the same event from two feeds becomes one row; it is applied
at `apps/api/src/gtmos/services/signal_service.py:55`, and a duplicate returns the existing signal and
triggers nothing downstream. The catalogue is served at `GET /api/v1/signal-types`. The demo workspace
currently holds **4,719 signals** across all 19 types, the largest being `website_visit` (776) and
`funding_round` (576), the smallest `ai_project_cancelled` (26).

**Common interview question**

*"How would you detect buying signals, and how do you stop them becoming noise?"*

**Good answer**

"Detection is the easy half — feeds, job boards, funding databases, your own product events. The hard
half is that every one of them is happy to sell you more volume than you can act on. Three things keep it
useful. First, every signal type carries a half-life, so a funding round stays relevant for about a
quarter and a pricing-page visit for a fortnight, and the score decays rather than the signal just
sitting there. Second, a stable dedupe key on type plus account plus source reference, so the same
funding round from three feeds is one signal and not three score bumps. Third, and this is the one people
skip, some signals have to be negative. Six of nineteen in GTMOS subtract points — competitor adopted,
layoffs, budget freeze, champion departed, unsubscribed, initiative cancelled — and each carries the
action it implies. The caveat: negatives are much harder to source reliably than positives. Layoffs get
reported; a quiet budget freeze does not, so the taxonomy is systematically more optimistic than
reality."

---

## Module 9 — Scoring

**What it is**

A score is a single number that ranks accounts so a rep knows what to work first. The useful split is
**fit** (are they the kind of company that buys from us — firmographics, technographics, which barely
change) against **intent** or "why now" (signals, timing, engagement — which change weekly). A score that
mixes them without separating them cannot answer either question: a perfect-fit account with no forcing
event and a mediocre account that just raised $200M can land on the same number.

The other distinction interviewers probe: is it a **model** or a **heuristic**? A heuristic has weights
set by hand and can be argued with. A model has weights learned from labelled outcomes and needs a
training set, a holdout, calibration and drift monitoring. Both are legitimate; claiming the second while
running the first is not.

**Why it exists**

Because rep attention is finite and the alternative to a score is a sort by alphabetical order or by
whoever shouted loudest. But the reason it has to be *explainable* is different: a rep who cannot see why
an account scored 98 will not work it, and an ignored score is more expensive than no score, because you
paid for it and you still got a spreadsheet.

**Example**

Kestrel Analytics scores **98/100, grade A**, and every point is traceable. Fit 35/35: industry 15
("AI/ML Platforms is a core ICP industry"), size 12 ("850 employees is inside the sweet spot
(250–5,000)"), geography 8. Technical 15/15: an AI/ML org of ~64 engineers, four LLM-stack technologies
detected, and Datadog/Kubernetes/Snowflake for platform maturity. Intent 25/25, capped — the raw
components sum higher, driven by the hiring surge (8.85 of 10), the Copilot launch (6.57 of 9) and
pricing activity (7 of 7). Timing 13/15, engagement 10/10. Its **intent index is 96**, computed separately
from fit, which is what lets you ask "why now" without re-reading the fit points.

Now the honest part. Across the contacted cohort of 1,212 accounts with 139 meetings (base rate 11.5%),
the **structural** score — fit plus technical only, the part usable before anyone has been contacted —
has an AUC of **0.537 with a 95% interval of 0.485–0.589**. That interval includes 0.5. On this dataset
the score is **not distinguishable from random**. The total score, which includes engagement, scores
0.593 — and that is worse evidence, not better, because engagement points are awarded for replies and
meetings, and "booked a meeting" is the outcome being predicted.

**How GTMOS implements it**

`score_account` at `apps/api/src/gtmos/domain/scoring.py:425` is a pure function of (ICP, account facts,
signals, engagement, now) — same inputs, same output, which is what makes it unit-testable and diffable
between ICP versions. Category budgets come from the ICP weights (Fit 35, Intent 25, Timing 15, Technical
15, Engagement 10) and each category is capped at its budget.

Two design decisions are worth more than the arithmetic. First, `_negative_components` at line 478
subtracts penalties **after** the category caps are applied, because inside a category an account already
at its engagement ceiling would lose nothing for its champion walking out — and the entire point of a
negative signal is that it must be able to hurt. Only the strongest instance of a type counts: two layoff
reports are one layoff, and stacking would punish an account for how loudly its bad news was covered.
Second, `GRADE_THRESHOLDS` at line 29 is `A ≥ 72, B ≥ 58, C ≥ 45`, and the comment records why they moved
from 80/65/50: under the old bands grade A held **one account in 2,006**, which is not a list anyone can
work. Today A holds 8 (0.4%) and B holds 204 (10.2%) — a day's list and a quarter's list.

The evaluation is separate and deliberately model-agnostic: `roc_auc` at
`apps/api/src/gtmos/domain/evaluation.py:93` with a Hanley–McNeil interval at line 126, and `VARIANTS` at
`apps/api/src/gtmos/services/scoring_eval.py:29` splitting the score into structural, pre-engagement and
total precisely so the leakage is visible. The whole report is served at
`GET /api/v1/analytics/scoring-evaluation`, and the harness takes `(score, outcome)` pairs, so the day
the score becomes a model prediction, the same backtest grades it.

**Common interview question**

*"How would you score accounts, and how would you know the score works?"*

**Good answer**

"I'd start with a hand-weighted heuristic, not a model, because on a new territory there are no labelled
outcomes to learn from — and a heuristic a revenue leader can argue with beats a model nobody can
interrogate. GTMOS splits it into fit, intent, timing, technical and engagement, weighted to a hundred,
with every point attributed to a named rule and a sentence. Then the important half: measuring it. I run
a backtest that splits the score into a structural part with no leakage and a total that includes
engagement, and reports AUC with a confidence interval. On this dataset structural AUC is 0.537 with an
interval of 0.485 to 0.589 — which includes 0.5, so it is not distinguishable from random, and the
repository says that rather than quoting the flattering 0.593. The 0.593 is contaminated: engagement
points come from replies, and the outcome is a meeting. The real limitation is that none of this is
causal, because the score chose who got contacted. Fixing that needs a randomised holdout on the target
list, which is what I'd build next."

---

## Module 10 — Routing

**What it is**

Routing is deciding which human owns an account or a lead, and doing it fast enough to matter.
**Speed-to-lead** is the metric it exists to protect: the elapsed time between a lead event and the first
genuine outbound touch. The published research is old but directionally uncontested — response rates fall
off a cliff within the first hour.

A **territory** is the slice one rep owns. A **named account** is one assigned by agreement, usually
negotiated above the RevOps team, that no rule is allowed to move. A **round robin** distributes evenly
across a pool; **least-loaded** assigns by current capacity.

**Why it exists**

Because an unowned lead is a lost lead and nobody notices. Routing failures are silent by construction:
nothing errors, no alert fires, the record just sits there. The second-order reason is trust — routing
that quietly reassigns a rep's named account is how a RevOps team loses the ability to change routing at
all, because after that every change gets escalated.

**Example**

GTMOS runs seven rules. Existing customers go to Account Management at priority 10 with a 48-hour SLA and
are the one rule allowed to override an existing owner. High-intent strategic accounts go to a named
Senior AE at priority 20 with a **4-hour** SLA. Enterprise NA and Enterprise EMEA sit at priority 30 with
24 hours. High-intent mid-market NA jumps to the enterprise pool at priority 40 with 8 hours. SMB and
mid-market round-robin to the SDR pool at 48 hours. And at priority 999 sits `revops-triage`, the
**fallback queue**, with a 72-hour SLA — because "unmatched" should be a destination, not a shrug.

The measurement is the interesting part. Over the last 90 days, **604** lead-event assignments carried an
SLA: **474 met** (78.7% of those decided), **106 touched late**, **22 never touched at all**, and 2 still
pending with the clock running. Median time to first touch: **4.4 hours**. The worst offender is Helio
Intelligence, untouched and 957.8 hours overdue. Late, never-touched and pending are counted separately
on purpose: a late touch is a process problem, an untouched one is a leak, and a pending one is neither —
collapsing them hides the leak inside the process problem and inflates the hit rate with the pending.

**How GTMOS implements it**

`route` at `apps/api/src/gtmos/domain/routing.py:127` resolves in a fixed order: named account first
(line 148, and no rule gets a vote), then lowest priority number, then the more specific rule (more
conditions) on a tie, then alphabetical key — boring on purpose, so a conflict always resolves the same
way and the losing rules are returned with the decision so a human can see what was considered.
`pick_round_robin` at line 106 is worth reading: it hashes the account over a sorted pool rather than
keeping a pointer. That gives up exact balance in exchange for **idempotency** — re-running routing after
a replay or a crash reaches the same rep, and two workers racing cannot produce two different owners.
When exact balance matters, `pool_least_loaded` is the better strategy and the rules say which they use.

Measurement lives in `sla_report` at `apps/api/src/gtmos/services/routing_service.py:170`. Two constants
carry the judgement: `FIRST_TOUCH_TYPES` at line 161 (email, call, LinkedIn, meeting — an internal note is
not a touch) and `LEAD_TRIGGERS` at line 167, which restricts the metric to genuine lead events, because
a territory reshuffle assigns thousands of accounts at once and starts no clock. Breach is computed
against real activity rather than stored as a boolean on the decision, which is what keeps "late" and
"never touched" distinguishable. `POST /api/v1/routing/simulate` explains a hypothetical assignment
without applying it; `GET /api/v1/routing/sla` serves the numbers above.

**Common interview question**

*"How would you design lead routing?"*

**Good answer**

"Deterministic, explainable, and with a clock on it. The resolution order matters more than the rules:
named accounts first, because those are negotiated above RevOps and routing that moves one is routing
nobody will let you change again; then priority; then specificity; then a stable tie-break so the same
lead always lands the same place. Anything that matches and loses gets returned with the decision, so
when a rep asks why they didn't get it there's an answer. Two things I'd insist on. A fallback queue, so
'no rule matched' is a destination rather than silence — about 92 assignments went through ours in the
last 90 days. And an SLA per rule, measured against the first real outbound touch, with 'late' and 'never
touched' counted separately. Ours is 78.7% met, 106 late, 22 never touched. Collapsing those two would
have shown a better number and hidden the 22, which are the ones that actually cost money."

---

## Module 11 — Outbound

**What it is**

Outbound is contacting people who have not asked to hear from you. The machinery: a **campaign** (a play
with a target list and a message), a **sequence** (an ordered series of steps — email, wait, email, call,
LinkedIn), and a **sequencer** (the tool that actually sends them and stops on reply — Outreach, Salesloft,
Apollo, HubSpot Sequences). The **buying committee** is the set of people who collectively decide: a
champion who wants it, an economic buyer who pays, a technical evaluator who tests it, an executive
sponsor who blesses it, and end users who will live with it. Selling to one of them is how deals die in
month four.

**Deliverability** is the constraint nobody mentions until it bites: how much you can send before mailbox
providers start filtering you. Since February 2024 Google's bulk-sender rules put the spam-complaint
limit at **0.30%** and the target at **0.10%**, measured in Postmaster Tools. Cross it and *every*
campaign from that domain gets throttled, including the ones that were working.

**Why it exists**

Because inbound alone rarely fills an enterprise pipeline, and because the alternative — waiting — is not
a plan. But the economics are asymmetric in a way that shapes every design decision here: an
unsubscribe is a **permanently untargetable account**, and a burned sending domain is a cost paid by
whoever sends next quarter, not by the person who ran the campaign this quarter. That asymmetry is why
deliverability has to be modelled as a limit rather than a metric to trade against.

**Example**

For Kestrel, GTMOS does **not** default to the champion. Because the account already has an open
opportunity, `pick_recipient` reorders the committee and drafts to the economic buyer first — and because
the champion, Priya Raman (Head of AI Platform), has already attended a meeting, the opener references
her by name rather than opening cold. That is multi-threading, and it is a rule, not a prompt.

Every draft then passes guardrails before it can be approved. The blocking ones: no number may appear
that is not in the cited evidence; no banned claim pattern (guarantees, "10x", "industry-leading",
"customers like", "as we discussed"); the anchor signal must be under 120 days old and at least 70%
confident; and the contact must be reachable. Across the workspace there are currently 741 drafts: **722
have cleared approval and sit at `ready`, 19 are still in review, and none has been transmitted**,
because `ready` is the hand-off point to a sequencer and no sequencer is connected. The 3,863 "sends" in
the analytics below are seeded synthetic outbound history, not messages this system transmitted;
`outbound_send_enabled` is `false` and there is no code path behind it.

The deliverability picture is why that restraint matters. Over 90 days: 3,863 messages, 101 hard bounces
(**2.61%**, 95% CI 2.16–3.17%, entirely above the 2% healthy line), 3 spam complaints across 747 accounts
touched (**0.40%**, above the 0.10% target for its whole interval), a 1.34% unsubscribe rate whose
interval still reaches back under 1% — reported as *not proven, not ignorable* — and a contact list that
is **12.73% never verified**. Risk score 41/100, verdict **throttle**, throttle factor 0.5.

**How GTMOS implements it**

`pick_recipient` at `apps/api/src/gtmos/services/outreach_service.py:62` does the committee reordering;
`_engaged_champion` at line 89 supplies the warm-intro reference only when that person has actually met
with us. The message itself is built from a reasoning chain, not a blank prompt — signal → pain
hypothesis → value proposition → proof → CTA — where "proof" may only come from
`SELLER_PROOF_LIBRARY` at `apps/api/src/gtmos/domain/personalization.py:17`, a fixed set of
seller-approved statements, so a draft cannot invent a customer result. `run_guardrails` at line 125
checks every draft, deterministic or model-written, and `BANNED_PATTERNS` at line 63 lists what is
refused and why. The approval state machine is `MESSAGE_TRANSITIONS` at line 279 and
`check_message_transition` at line 288, which refuses to move a draft to `approved` or `ready` while a
blocking guardrail fails; it is exposed at `POST /api/v1/drafts/{draft_id}/transition`. Deliverability is
modelled as a constraint in `apps/api/src/gtmos/domain/deliverability.py` (`assess_risk` at line 556) and
served at `GET /api/v1/outbound/deliverability`.

**Common interview question**

*"How do you personalise outbound at scale without it becoming obvious spam — or worse, wrong?"*

**Good answer**

"I'd separate the three things people lump together. Personalisation is a *structure* problem first: every
message follows signal, pain hypothesis, value, proof, call to action, and the signal has to be a real
row in the database with a timestamp and a confidence, not a paraphrase of the company's homepage. Then
proof is restricted to an approved library — the generator physically cannot cite a customer result,
because there's a fixed dictionary of allowed claims. Then guardrails: every number in the draft has to
appear in the cited evidence, no superlatives, no 'as we discussed', and the contact has to be reachable.
Blocking failures stop approval, they don't just warn. The honest limitation is that none of this makes a
message *good* — it makes it defensible. A mechanical check cannot tell you whether a well-cited claim is
persuasive. And I'd rather show you the deliverability page than the reply rate: 2.6% hard bounces and a
12.7% unverified list means the answer right now is send less, not personalise harder."

---

## Module 12 — Pipeline

**What it is**

Pipeline is the stock of open opportunities and their value; the **funnel** is the flow that produces it.
The numbers a revenue leader asks for weekly: conversion between stages, **velocity** (how long a deal
takes and what it is worth), **win rate**, and where deals are stalling.

The methodological trap is cohort versus snapshot. A snapshot funnel ("how many accounts are in each
stage today") mixes accounts contacted yesterday with accounts contacted last March and produces
conversion rates that move for no reason. A **cohort** funnel fixes the denominator — accounts whose
first touch fell inside the window — and then counts later stages whenever they occur, including after
the window closes.

**Why it exists**

Because "pipeline is down" is a question, not a fact, and the answer is always one of: fewer accounts
entering, a worse conversion at one specific step, longer cycles, or smaller deals. A funnel that cannot
distinguish those four sends the team to fix the wrong thing. Stall detection matters for the same
reason — a deal that has not moved in 30 days is not in your pipeline in any meaningful sense, but it is
still in your forecast.

**Example**

Over the last 90 days on the demo data, the contacted cohort is **495 accounts**. Of those, 127 reached
engaged (25.7%), 71 qualified, 39 booked a meeting, 28 became opportunities and 4 are won; 22 are lost.
Note the shape: the big loss is the first step — three quarters of contacted accounts never reply — and
every step after that converts above 50%. That is the signature of a targeting or messaging problem, not
a closing problem, and it is the opposite conclusion you would draw from staring at the 14% opportunity-
to-won rate at the bottom.

Stall rules are explicit rather than a single "30 days" catch-all: no reply 21+ days after first touch,
replied but not qualified for 14+, qualified but no meeting for 10+, meeting held but no opportunity for
14+, opportunity open 30+ days in one stage. Different stages decay at different speeds, and one global
threshold flags the wrong ones.

**How GTMOS implements it**

`funnel` at `apps/api/src/gtmos/services/analytics.py:186` builds the cohort and states its own
definition in the payload, so the denominator travels with the number. `velocity` at line 446 reports
cycle length, deal size and win rate. `stuck_accounts` at line 517 applies `STUCK_RULES` at line 508 —
the per-stage thresholds above. Everything reads `StageTransition` rows written by
`check_funnel_transition` (`apps/api/src/gtmos/domain/pipeline.py:37`), which is also what the scoring
backtest uses for its outcome labels, so the funnel and the backtest cannot tell different stories. Served
at `GET /api/v1/analytics/funnel`, `/velocity` and `/stuck`.

**Common interview question**

*"Pipeline fell 30% this quarter. How do you find out why?"*

**Good answer**

"I'd decompose before I theorise, because 'pipeline fell' has exactly four possible mechanical causes:
fewer accounts entering the funnel, a worse conversion at one specific step, longer cycles so deals that
would have closed haven't yet, or smaller average deals. Those need different fixes and the wrong
diagnosis costs a quarter. So first a cohort funnel, not a snapshot — fix the denominator to accounts
first touched in the window, and let later stages mature. On our demo data that shows 495 contacted, 127
engaged, and everything below that converting above 50%, which says the problem is at the top, not the
close. Then period-over-period on each step to see which one actually moved. The caveat I'd give: a
cohort funnel always understates recent windows, because accounts contacted last week haven't had time to
convert, so the most recent bar is not comparable to the others and someone will always misread it."

---

## Module 13 — Attribution

**What it is**

Attribution assigns credit for a deal across the marketing and sales touches that preceded it. The
standard models: **first-touch** (all credit to what started the relationship), **last-touch** (all credit
to the touch nearest the opportunity), **linear** (split evenly), and **U-shaped** (40% first, 40% last,
20% spread across the middle).

None of them is a measurement. They are conventions for dividing a number, and which one a company uses
usually correlates with which team owns the dashboard.

**Why it exists**

Because budget gets allocated by it. If webinars get no credit, the webinar programme gets cut, and if
the model is last-touch, webinars will never get credit, because a webinar is almost never the last
thing that happens before a deal opens. The honest reason to compute four models rather than one is to
make that arbitrariness visible instead of letting one convention pass as fact.

**Example**

GTMOS's attribution spotlight is a real opportunity from the demo data: Solstice Metrics, $320,000,
opened 2026-09-19, with six recorded touches. The earliest is "Webinar: Evaluating LLM agents in
production", 96.9 days before it opened; the other five are the generic ICP campaign, the last of them
5.5 days before.

- **First-touch:** the webinar gets **100%** — $320,000.
- **Last-touch:** the webinar gets **0%**; the ICP campaign gets $320,000.
- **Linear:** ICP 83.3% / webinar 16.7%.
- **U-shaped:** ICP 60% / webinar 40%.

Same deal, same touches, four answers between $0 and $320,000 for the same webinar. Across the whole
180-day window there are 77 opportunities worth $6,669,000, of which **14 opportunities and $1,074,000
are unattributed** — 16.1% of pipeline with no recorded touch at all. GTMOS reports that explicitly
rather than crediting it to "direct", which is what most tools do and which is how a channel that does
not exist ends up with a budget.

**How GTMOS implements it**

`weights_for` at `apps/api/src/gtmos/domain/attribution.py:47` is the whole model set in fifteen lines —
which is the point: the models are trivial, the judgement is in what counts as a touch and what happens
to the remainder. `eligible_touches` at line 66 applies a 180-day lookback before opportunity creation;
later touches are influence, not sourcing. `TOUCH_TYPES` at
`apps/api/src/gtmos/services/attribution_service.py:18` is the list that counts — email sent, email
replied, meeting held, webinar attended, LinkedIn — and **email opens are deliberately excluded**,
because since Apple Mail Privacy Protection an open mostly measures the recipient's mail client. The
unattributed tail is a first-class field on the result, not a footnote. Served at
`GET /api/v1/analytics/attribution`.

**Common interview question**

*"First-touch or last-touch — which do you use?"*

**Good answer**

"Neither, as a single answer. I'd show both and treat the gap between them as the finding. We have an
opportunity in the demo data — Solstice Metrics, $320,000 — where first-touch gives a webinar a hundred
percent of the credit and last-touch gives it zero, from exactly the same six touches. If I pick one
model I've decided the webinar budget with a convention, not with evidence. So GTMOS computes four side
by side, and reports the unattributed share separately: sixteen percent of pipeline in that window has no
recorded touch at all, and calling that 'direct' is how a channel that doesn't exist gets funded. The
thing I'd say out loud is that none of these are causal. Attribution answers 'what did we do before this
deal', not 'what caused it'. If someone needs a causal claim about a channel, that's a holdout or a
geo-split experiment, and it costs real pipeline to run."

---

## Module 14 — Experimentation

**What it is**

Running a controlled comparison of two GTM treatments — subject lines, sequences, channels — and reading
the result honestly. The statistical furniture: randomise at a unit, define a **primary metric** before
you start, pre-register a **minimum sample**, and use intervals rather than point estimates.

The GTM-specific part is **guardrail metrics**. Bounces, unsubscribes, spam complaints and negative
replies are not competing success metrics to be traded against replies; they are **limits**. A variant
that wins replies by pushing a guardrail past its ceiling has not won — it has borrowed reply rate from
the sending domain and booked the loan as revenue.

Two other concepts separate a verdict from a decision. **Practical significance**: a p-value says "is
this difference real", not "is it worth retraining the team and rewriting the sequences". And **minimum
detectable effect** (MDE): the smallest lift your sample size could have caught, which is what turns a
null result into "no effect worth having" rather than "we were blind".

**Why it exists**

Because outbound samples are small and noisy, and most "winning" subject lines are noise someone declared
a winner too early. Repeatedly checking a p-value and stopping at the first p < 0.05 — peeking — pushes
the false-positive rate far above 5%. Pre-registering the sample and the metric is the cheapest available
fix.

**Example**

This is the page worth spending five minutes on. The seeded experiment `provocative-subject` tests a
curiosity-gap subject line against a plain value subject, randomised at the account level, minimum 250
per arm.

Result on the primary metric: control **20.68%** reply rate (n=266), treatment **36.96%** (n=276). That
is **+16.3 percentage points**, 95% CI +8.7 to +23.6, **p = 2.95 × 10⁻⁵**. The verdict is
`treatment_better`, and the whole difference interval clears the 2 pp practical bar.

The recommendation is **do not ship**.

Unsubscribes went from **0.00% (0 of 266)** to **2.90% (8 of 276)**, 95% CI 1.48–5.61% — an interval that
sits *entirely above* the 1% policy ceiling. Negative replies went 2.63% → 10.14%. Spam complaints went
0.00% → 0.72%, over the 0.3% ceiling but with an interval that still reaches back under it, so it is
flagged `watch` rather than `breach`: not proven, not ignorable. Hard bounces actually improved, and are
reported as `ok` — never as a win, because a guardrail is only ever checked for harm.

The lift is real. It is being paid for out of the sending domain, by whoever sends next quarter.

**How GTMOS implements it**

`assign_variant` at `apps/api/src/gtmos/domain/experiments.py:110` hashes `(salt, unit_id)` into 10,000
buckets, so assignment is reproducible from the account id with no assignment table — and randomising at
the account rather than the contact means two people at one company never receive competing messages.
`GUARDRAILS` at line 54 carries each limit with its `ceiling`, its tolerated `max_regression` from
control, and a written rationale, so the UI never shows a bare threshold. `evaluate_guardrail` at line
351 is one-sided and deliberately **not** gated on the experiment's minimum sample — that minimum is
powered for the primary metric, and evidence of harm should not have to wait for it; the Wilson lower
bound does the honest work instead. `minimum_detectable_effect` at line 221 inverts
`required_sample_size` by bisection rather than a second closed form, so the two numbers can never
disagree. And `recommend` at line 427 encodes the ordering that is the whole point: **a confirmed
guardrail breach outranks any win on the primary metric.** Served at `GET /api/v1/experiments/{key}`, and
rendered at `/experiments/provocative-subject`.

**Common interview question**

*"Your best-performing subject line lifts reply rate 16 points with p < 0.001. Do you ship it?"*

**Good answer**

"Not on that evidence alone, and this is the exact case I built the experiments page around. In our
seeded test the treatment does lift replies from 20.7% to 37.0% with p under 0.001 — and the
recommendation is do not ship, because unsubscribes went from zero to 2.90% with a confidence interval of
1.48 to 5.61%, entirely above our 1% ceiling, and negative replies went from 2.6% to 10.1%. Those aren't
competing metrics I trade against replies, they're limits. An unsubscribe is a permanently untargetable
account and a spam rate over Gmail's 0.3% throttles every campaign from the domain, not just this one.
The asymmetry is the real argument: the lift is booked this quarter by whoever ran the test, and the
deliverability is paid for next quarter by whoever sends next. The caveat I'd add is that randomisation
only licenses a causal read of the gap between these two arms, on this audience, in this window —
nothing wider."

---

## Module 15 — Reverse ETL

**What it is**

Normal ETL moves operational data *into* a warehouse for analysis. **Reverse ETL** moves modelled data
back *out* — scores, tiers, product usage, propensity — into the tools where people work: the CRM, the
sequencer, the ad platform. Hightouch and Census (now Fivetran Activations) productised it. The contract
is always the same four pieces: a model with a primary key, a **match key** on the destination, a sync
mode, and **change detection** so only diffs are sent.

**Why it exists**

Because a score that lives in a dashboard changes nothing. The rep does not open the dashboard; the rep
opens the CRM record. Getting the number onto that record is the entire difference between analytics and
operations.

The failure modes are specific. Sending the full record on every push overwrites whatever a human fixed.
Sending everything every time burns API quota and makes the change log useless. And keying on an
unstable field creates duplicates that nobody notices until the account count in the CRM exceeds the
number of companies in the market.

**Example**

GTMOS syncs A, B and C grade accounts with a domain. Running the preview right now:
`considered: 850, would_create: 0, would_update: 0, unchanged: 850`. Every one of those 850 is skipped
because the hash of its computed payload matches what was last pushed — which is exactly the behaviour
you want, and also why the number to watch is `unchanged` rather than `succeeded`. Earlier today a single
signal arrived for Kestrel, which moved one account's `gtmos_last_signal`, and the hourly n8n workflow
picked up `would_update: 1`, ran the sync, and wrote back a signed run record: 850 considered, 1 changed,
1 succeeded, 849 skipped, 536 ms.

**How GTMOS implements it**

`plan_company_sync` at `apps/api/src/gtmos/services/crm_sync.py:119` is where the field-ownership rule
lives, and it is enforced rather than documented: if the account has never been pushed, the payload is
`domain`, `name` and the `gtmos_*` fields; on every later push it is **`gtmos_*` only**. A rep's rename
survives forever. `payload_hash` at line 96 is `sha256` over canonical JSON with sorted keys — and it
hashes only the owned fields even on the create path, because hashing the create payload would make every
account look changed on the very next run. `run_company_sync` at line 155 checks the CRM kill switch
*before* building the adapter, chunks into batches of ≤100, and retries retryable failures for up to
`MAX_RETRY_ROUNDS = 3` (line 50), re-sending only the still-pending records. `preview_reverse_etl` at line
302 is the dry run, served at `GET /api/v1/integrations/hubspot/reverse-etl/preview`.

Everything above runs against the **simulated** adapter. Over the last seven days the Operations page
records 41 sync runs, 5,205 records changed and 72 record-level failures — all of them simulated 429s
that the demo adapter injects deterministically so the retry path is always exercised. That is honest
about the mechanism and dishonest about the world, which is why demo mode is never offered as evidence
that live retries work.

**Common interview question**

*"What is reverse ETL, and how do you stop it overwriting what reps have changed?"*

**Good answer**

"Reverse ETL is pushing modelled data out of wherever you computed it into the tools people work in — the
CRM, the sequencer. The contract is a primary key, a match key, a sync mode and change detection. The
overwrite problem is solved by field ownership, and it has to be enforced in code rather than agreed in a
doc, because the doc doesn't run. In GTMOS the planner builds two different payloads: on create it sends
name, domain and the gtmos-namespaced fields; on every later push it sends only the gtmos fields. So a
rep's rename survives every subsequent sync. Then a payload hash per record skips anything unchanged —
right now that's 850 of 850 accounts skipped, zero API calls. The subtle bug I'd mention is that the
stored hash covers only the owned fields, not the create payload; if it covered the create payload every
account would look changed on the very next run and be re-pushed once for nothing."

---

## Module 16 — Data quality

**What it is**

The unglamorous discipline of knowing what is wrong with your data and how much it costs. The recurring
categories: duplicates, missing required fields, invalid emails, stale enrichment, orphaned records,
records whose two stage systems disagree, transitions that should have been impossible, and external IDs
pointing at records that no longer exist.

The distinction that makes it tractable is **severity by consequence, not by count**. Three hundred stale
enrichment records are low severity — they degrade a score slowly. Six duplicate accounts are high
severity, because each one splits pipeline, breaks routing, and double-counts in every report.

**Why it exists**

Because every downstream system silently inherits the error. A missing employee count is not one bad
field: it means no segment, so no routing rule matches, so no owner, so no follow-up. The Stack Inspector
traces exactly that chain on this dataset: **37** live accounts have no employee count, **33** of those
also have no segment, and the chain ends in accounts with no territory owner. That is the argument for
treating data quality as a pipeline problem rather than a hygiene chore.

**Example**

GTMOS runs 12 rules and currently reports **504 open issues**: `stale_enrichment` 310, `invalid_email`
81, `missing_employee_count` 35, `duplicate_contact` 18, `provider_conflict` 15, `orphan_contact` 14,
`missing_domain` 9, `lifecycle_conflict` 8, `bad_external_id` 6, `duplicate_account` 6,
`invalid_pipeline_transition` 2, and `missing_owner` **0**.

That last zero is worth as much as the 310. `missing_owner` flags high-fit accounts with nobody assigned
— direct pipeline leakage — and on this dataset there are genuinely none: every A and B account has an
owner, which is what the fallback routing queue exists to guarantee. A rule that reports nothing is
either working or broken, and the only way to tell them apart is to know what it would have caught.

The 15 `provider_conflict` issues are the ones that show judgement: fields where two providers materially
disagree and GTMOS refused to pick a winner on confidence alone. That is deliberately a worse experience
than silently overwriting.

**How GTMOS implements it**

`RULES` at `apps/api/src/gtmos/services/data_quality.py:41` declares each rule with its severity and a
one-line `why` that is shown in the UI, so an issue always arrives with its consequence attached. Each
rule is a separate function — `rule_provider_conflict` at line 477 reads `field_provenance` rows where a
stored conflict is marked material; `rule_stale_enrichment` at line 275 uses a 180-day threshold matching
the enrichment module's own `STALE_AFTER`. Remediation is audited rather than silent: `merge_contacts` at
line 625 and `merge_accounts` at line 663 set `merged_into_id` rather than deleting, so activity history
survives and the merge is reversible, and `remediate` at line 703 routes an issue to its handler and
writes an audit row. Served at `GET /api/v1/data-quality`, with `POST /api/v1/data-quality/scan` to
re-run.

One detail found by a test and worth mentioning in an interview: the Data Quality page originally sorted
a *page* of results rather than the table, so an older high-severity issue could never reach the top of
the list. Severity ordering that only works on the first page is not severity ordering.

**Common interview question**

*"How do you prioritise data-quality work when the backlog is thousands of rows?"*

**Good answer**

"By consequence, not by count. Our scan has 504 open issues and 310 of them are stale enrichment, which
is the biggest pile and the least urgent — it degrades a fit score slowly. Six duplicate accounts are far
worse: each one splits pipeline, breaks routing, and double-counts in reporting. So every rule carries a
severity and a written reason that's shown with the issue, and I'd work high severity first regardless of
volume. The other thing I'd do is trace the chain rather than the field. Missing employee count isn't one
bad cell — 37 accounts have no employee count, 33 of those have no segment as a result, and no segment
means no routing rule matches and nobody owns them. Presenting it as 'no territory owner caused by a
missing field' gets it fixed; presenting it as '35 missing employee counts' gets it deprioritised. The
caveat is that merges are the risky remediation — ours set a merged-into pointer rather than deleting, so
they're reversible and history survives."

---

## Module 17 — GTM observability

**What it is**

Knowing whether the GTM machine is actually running. Not application uptime — whether workflows are
firing, syncs are landing, webhooks are being processed, providers are answering, and how long the gap is
between a signal arriving and an owner being assigned. Plus the two things that make an incident
survivable: an **audit log** with an actor, a before/after and a correlation id on every mutation, and a
**kill switch** an operator can hit without a deploy.

**Why it exists**

Because GTM automation fails silently and expensively. A workflow that stopped firing three weeks ago
does not page anyone; it just quietly stops creating pipeline, and you find out at the end of the
quarter. And when something *is* going wrong — a sequence sending to the wrong list, a sync corrupting
records — the gap between noticing and stopping is measured in records damaged per minute. An environment
variable is not a stop button: it needs an engineer, a config change and a restart.

**Example**

The Operations page, last seven days: workflows 67 succeeded, 76 skipped (conditions not met — which is
the system working, not failing), 3 failed and 5 dead-lettered, a 10.7% failure rate on 75 executed runs,
median duration 8,937 ms, 9 retried steps. Syncs: 41 runs, 0 failed, 3 partial, 5,205 records changed, 72
record failures, all simulated. Webhooks: 70 events with **60 duplicates absorbed** — the dedupe is doing
most of the work. Queue backend is `inline`; the LLM is in `demo` mode with no model configured.

The integration status page is the one to show an interviewer, because it refuses to flatter itself.
There is **no "Connected" badge anywhere**. Each boundary carries a mode and a verification level derived
from actual traffic: n8n is `live` / `verified_by_execution` with `reached_real_service: true`; PostHog
and Clay are `test` / `verified_locally` with `reached_real_service: false`; HubSpot is `demo` /
`simulated`. Each lists exactly what is blocking it — for Clay, `CLAY_API_KEY`,
`CLAY_WEBHOOK_SECRET` and "a Clay workspace on the Growth plan".

The three kill switches are separate on purpose, because the reasons differ: **automation** (a rule is
firing on the wrong accounts), **outbound** (a message or a list is wrong), **CRM writes** (sync is
corrupting records).

**How GTMOS implements it**

`workflow_health`, `sync_health`, `webhook_health`, `provider_health` and `routing_latency` are at
`apps/api/src/gtmos/services/operations.py:28`, `:116`, `:169`, `:240` and `:298`; `integration_status` at
line 737 derives each boundary's posture from configuration plus observed traffic rather than from a
hand-maintained table. `audit` at `apps/api/src/gtmos/services/common.py:72` writes actor, actor type,
before/after snapshots, a reason and a correlation id on every mutation. `SWITCHES` at
`apps/api/src/gtmos/services/governance.py:32` defines the three kill switches, and `is_enabled` at line
108 **reads the database on every check** — a cached flag would mean a pause takes effect whenever the
cache happens to expire, which is the one property a stop button cannot have. Blocked requests return
`423` carrying the operator's reason. Served at `GET /api/v1/operations`, `GET /api/v1/integrations/status`
and `POST /api/v1/governance/pause`.

The deepest surface is the Stack Inspector: `causal_chains` at
`apps/api/src/gtmos/services/stack_inspector.py:208` traces **one account set intersected through every
link**, so it reports the true overlap rather than two true numbers about different accounts. The
territory chain is the clearest: 294 non-customer accounts sit in a region no active routing rule
mentions, 87 of them were routed in the last 90 days and matched nothing. A dashboard that reported "294
uncovered" and "87 unmatched" as two tiles would be stating two facts and implying a third that might not
be true.

**Common interview question**

*"How do you stop an automated GTM system that is doing damage?"*

**Good answer**

"With a button, not a deploy. GTMOS has three runtime kill switches — automation, outbound and CRM writes
— kept separate because the reasons differ: a misbehaving rule is not the same incident as a bad message
list or a sync that's clobbering records, and you rarely want to stop all three. Every check is a
database read on the workspace rather than a cached flag, so a pause takes effect on the next action.
Blocked requests return a 423 with the operator's reason attached, and queued work stays queued, because
pausing isn't cancelling and resuming should pick up where it stopped. Pausing records who did it and
why, since the first question after any incident is 'when did we stop and who stopped us'. The honest
gap: the actor on every audit row is caller-asserted in this version rather than derived from a session,
which makes it a change log with a name on it rather than a true audit trail. It's written up as a
finding in the security review rather than glossed over."

---

## Module 18 — AI in GTM

**What it is**

The useful framing is not "where can we add AI" but **where a language model is allowed to be the source
of truth — which is nowhere.** A model is good at turning evidence you already hold into prose a human
will read. It is bad at being a database, and catastrophic at being a CRM field, because a fabricated
fact in a research brief becomes a fabricated fact in an email to a prospect.

The three failure modes with names: **hallucination** (inventing a fact), **ungrounded numbers**
(inventing a figure that sounds plausible, which is the one that survives review because numbers look
authoritative), and **prompt injection** (text scraped from the outside world containing instructions
that the model then follows).

**Why it exists**

Because research is genuinely expensive — a rep spends real minutes per account reading news, LinkedIn
and a website — and because the alternative to automated research is no research, which produces the
generic outbound everyone deletes. The constraint is that the output goes in front of a customer, so the
acceptable error rate is far lower than for an internal summary.

**Example**

GTMOS's research pipeline builds an **evidence pack** first: every fact it holds about the account,
numbered E1..En, with source, confidence and timestamp. Any generator — deterministic or model-driven —
must cite those refs, and `validate_sections` strips any claim citing nothing or citing a ref that does
not exist. On Kestrel that pack includes the firmographics with their provenance, eighteen signals, the
committee members with their inferred roles, recent activities and the score itself.

The injection defence is not theoretical. The evaluation harness caught the generator copying
attacker-supplied text out of a signal feed verbatim into a research brief. The fix was
`sanitize_external`, which drops *sentences* matching instruction patterns rather than whole fields —
removing the field loses the real signal that usually sits beside the injected line, and removing nothing
lets an attacker write your sales pitch — and replaces them with a visible marker, because silently
altering evidence is its own kind of dishonesty. A second round caught the same class of bug again: a
poisoned `industry` value reached a brief because the claim text read the account dict directly, so
sanitising only the evidence pack was not enough.

The Copilot takes the same position from the other side. It maps a question onto one of eight approved
analyses and runs deterministic metric functions. **No model ever writes or runs SQL.** Metrics GTMOS
does not model — revenue, ARR, churn, NPS, CAC, quota — are refused *by name* with a list of what it can
answer instead, because the fuzzy matcher would otherwise latch onto a shared word and answer "what's the
churn rate" with a meeting rate. That bug happened, and `UNSUPPORTED_METRICS` is the fix.

**How GTMOS implements it**

`sanitize_external` at `apps/api/src/gtmos/domain/research.py:109` with its pattern set at line 99;
`validate_sections` at line 469 strips uncited claims and reports them as unsupported rather than
discarding them quietly. The optional hosted writer is behind a protocol at
`apps/api/src/gtmos/integrations/llm.py:124` — `get_research_writer` returns `None` unless the mode is
explicitly `live`, so the default path is the deterministic generator, and the running system reports
`llm: {mode: "demo", model: null}`. Outbound guardrails are `run_guardrails` at
`apps/api/src/gtmos/domain/personalization.py:125`. Copilot refusals are `REFUSALS` at
`apps/api/src/gtmos/services/copilot.py:119` and `UNSUPPORTED_METRICS` at line 160. The grading harness is
`apps/api/src/gtmos/domain/llm_eval.py`, with `check_injection_resistance` at line 196; it grades whatever
writer is configured against seven adversarial cases — invented citations, ungrounded numbers, banned
superlatives, a stale low-confidence signal presented as current, contradictory evidence, and an
instruction hidden inside the evidence. The deterministic writer passes 7 of 7, which it largely does by
construction; the value of the suite is that it fails the moment a model is put behind the same
interface and misbehaves.

**No paid model call was made building this system.**

**Common interview question**

*"How do you stop AI hallucinating in outbound?"*

**Good answer**

"By never letting it originate a fact. The generator is handed a numbered evidence pack built from
records we already hold, every claim has to cite a ref, and any claim citing nothing or citing a ref that
doesn't exist is stripped before the brief is stored. Then a second layer on the draft itself: every
number in the message has to appear in the cited evidence, proof statements can only come from a fixed
seller-approved library, and a blocking guardrail failure prevents approval rather than warning. The part
I'd emphasise is that I found a real bug this way — the evaluation harness caught the generator copying
attacker-supplied text straight out of a signal feed into a research brief. Signal titles come from
scrapers and webhooks, so they're untrusted input, and they're now sanitised sentence by sentence at the
boundary. The limitation is that all of these checks are mechanical. They catch invented citations and
ungrounded numbers; they cannot tell you whether a well-cited claim is actually persuasive. That still
needs a human, which is why nothing gets approved without one."

---

## Module 19 — How GTMOS connects everything

**What it is**

The one-sentence architecture: **PostHog observes the product, Clay buys commodity enrichment, n8n glues
systems together, HubSpot is where the revenue team works, and GTMOS owns the judgement** — what a signal
means, what an account is worth, who should work it, what may be said to them, and whether any of it
worked.

The test for whether something belongs in the built layer rather than the bought one: **would a
reasonable revenue leader want to argue with it?** If yes, it needs to be explainable, versioned and
diffable, which means it belongs in code you own — not in a vendor's black box and not on a workflow
canvas.

**Why it exists**

Because the failure mode of a project like this is sprawl. Rebuilding Clay badly, or building a worse
CRM, is how you spend two years producing something nobody can operate. Naming what you deliberately do
*not* build is as much a part of the architecture as the diagram: no email sending, no enrichment vendor
network, no event store, no CRM UI, no general workflow builder, and no "the AI decides".

**Example**

One signal, end to end. Three people at Kestrel use the free product. PostHog-shaped events carrying
`$groups.company` arrive; n8n normalises and HMAC-signs them; `POST /api/v1/webhooks/posthog` verifies the
signature, deduplicates on event id, and stores the raw event. Identity resolution matches the group key
to `kestrel-analytics.example`. Engagement rows are written, the PQL rule fires, a `usage_threshold`
signal is created with a weekly dedupe key, the score is recomputed, and because it crossed a threshold a
workflow is emitted with an idempotency key of
`wf:<workflow>:v<version>:<trigger_type>:<event_id>`. The run enriches, rescores, infers the committee,
generates research, drafts outreach into the approval queue, routes an owner with an SLA, and syncs the
computed properties to the CRM. The CRM sends a change webhook back, which is **logged and never
auto-applied** — that is the cycle-breaker that stops a sync loop. The same webhook delivered again is
deduplicated. Analytics, Operations and the audit log all reflect it.

That is `make golden-flow`: 20 steps, and `VIA_N8N=1 make golden-flow` runs the identical sequence routed
through the real n8n container.

**How GTMOS implements it**

`emit_event` at `apps/api/src/gtmos/services/workflow_engine.py:243` checks the automation kill switch
*before* creating any run row, so a pause leaves no queue to drain. `create_run` at line 291 enforces the
idempotency key from `apps/api/src/gtmos/domain/workflows.py:67` inside a savepoint, so a concurrent
duplicate delivery loses the race cleanly. `_claim` at line 372 takes `FOR UPDATE SKIP LOCKED` on the run
row — added after two workers executed the same run and duplicated every side effect, because persisted
step state alone does not prevent it: both workers read the same `pending` rows before either writes.
Because the lock is held by the transaction rather than by a status flag, a worker that crashes releases
it and the run stays resumable. Runs are enqueued **after commit** via an SQLAlchemy `after_commit`
listener at line 358, and a sweeper re-enqueues anything stuck in `queued`. Retries use exponential
backoff from `apps/api/src/gtmos/domain/workflows.py:73`; exhausted retries end in `dead_letter`, and
`retry_run` at line 535 resumes at the failed step rather than from the beginning. The four shipped
workflows are `DEFAULT_WORKFLOWS` at `apps/api/src/gtmos/domain/workflows.py:77`.

**Common interview question**

*"Walk me through what happens between a product event and a rep taking action."*

**Good answer**

"Event arrives at a signed webhook, signature verified, deduplicated on event id, stored raw before
anything interprets it — so a bad processor is replayable rather than a lost event. Identity resolution
maps the company group key to an account; free-mail domains never match, because gmail.com is not a
company. That becomes an engagement row, which feeds a composite product-qualified rule evaluated at the
account level over fourteen days. If it crosses, one signal is written with a weekly dedupe key, the
score recomputes, and a workflow is created with an idempotency key of workflow, version, trigger type
and event id — so a redelivered event never re-runs the play. The run enriches, rescores, finds the
committee, writes research, drafts outreach into an approval queue, routes an owner with an SLA clock,
and syncs computed properties to the CRM. The two details I'd call out: runs are enqueued after commit,
not during, so the queue can never hold a run the database doesn't; and execution takes a row lock with
skip-locked, which I added after two workers ran the same run and duplicated every side effect."

---

## Module 20 — How to explain GTMOS in an interview

**What it is**

The final module is not a concept, it is a performance. You have roughly ninety seconds before the
interviewer decides whether this is a portfolio project or evidence of judgement, and the difference is
almost entirely in what you volunteer about its limitations.

**Why it exists**

Because a demo is easy to make impressive and hard to make trustworthy, and experienced interviewers know
that. Every impressive claim they hear is discounted by their prior that portfolio projects overstate.
The fastest way to remove that discount is to be the one who raises the inconvenient number first. You
cannot be caught out on something you said unprompted.

**Example**

The ninety-second narrative, spoken. Time it once; it comes in just under.

> "GTMOS is an AI-native GTM operating system for a fictional seller, Sentinel AI, which sells
> reliability infrastructure for AI agents. It runs the whole loop on 2,006 synthetic accounts: find the
> accounts, explain why now, draft evidence-grounded outreach for human approval, route it, sync it, and
> measure it.
>
> The architecture decision it's really about is what to buy and what to build. PostHog observes the
> product, Clay buys enrichment, n8n moves bytes between systems, HubSpot is where reps work — and GTMOS
> owns the judgement: what a signal means, what an account is worth, who works it, what may be said to
> them. My test for that boundary is whether a revenue leader would want to argue with the logic. If
> they would, it has to be explainable, versioned and diffable, so it lives in code.
>
> Three things I'd point at rather than the feature list. One: of four integrations, exactly one is
> verified by execution — n8n, in Docker, five of six workflows actually fired. HubSpot runs on a
> simulated adapter and its live half has never touched a portal. The product says that itself; there's
> no 'Connected' badge anywhere. Two: the scoring model doesn't work yet, and the repository is what says
> so — structural AUC 0.537 with an interval of 0.485 to 0.589, which includes 0.5. Three: the
> best-performing subject line is recommended against. It lifts replies 16.3 points with p under 0.001,
> and unsubscribes went from zero to 2.9%, so the verdict is do not ship.
>
> Nothing in it has ever sent a message to anyone."

**How GTMOS implements it**

Three surfaces carry the whole argument, and they are worth showing in this order.

1. **`/integrations`** — thirty seconds, and go here *first*, before claiming anything. The page is
   generated by `integration_status` at `apps/api/src/gtmos/services/operations.py:737`, which derives
   each boundary's mode and verification level from configuration plus observed traffic. Point at the
   fact that there is no "Connected" badge anywhere, and at the per-integration blocking-requirements
   list. Establishing that you distinguish "built" from "verified" before you claim anything buys
   credibility for everything after it.
2. **`/experiments/provocative-subject`** — two minutes, and the one to linger on. Served by
   `GET /api/v1/experiments/{key}`; the ordering that produces the verdict is `recommend` at
   `apps/api/src/gtmos/domain/experiments.py:427`. A decisive statistical win carrying a `do_not_ship`
   recommendation is a judgement call an interviewer can push on, and it shows you treat guardrails as
   constraints rather than competing objectives.
3. **`docs/scoring-evaluation.md`** — two minutes. Show the structural / pre-engagement / total split
   from `VARIANTS` at `apps/api/src/gtmos/services/scoring_eval.py:29` and explain the leakage. A project
   that grades its own headline feature and then reports the unflattering number is doing something
   almost no portfolio does.

**Common interview question**

*"Isn't this all fake data, though?"* — the first of the four hard ones, and the one that decides the
rest of the conversation.

**Good answer**

"Completely fake, and I'd say that before you ask — 2,006 synthetic accounts on reserved `.example`
domains, deterministic from a seed, labelled DEMO on every page. What that means is that nothing here is
evidence about real-world conversion, and the scoring evaluation says so in its own words rather than
leaving you to work it out. What it isn't is a reason to discount the machinery. The enrichment conflict
policy, the webhook idempotency keys, the guardrail ordering and the evaluation harness are the same code
you'd run against real data, and several of them are the shape they are because tests against this data
found them wrong — retries that never deduplicated because the payload carried an incrementing attempt
number, two workers executing the same run, a generator copying attacker-supplied text into a research
brief. Synthetic data is a weak substitute for real outcomes and a perfectly good substrate for finding
concurrency and trust bugs. I'd rather be judged on the second."

### The other three hard questions

*"You built a worse version of Clay and HubSpot."* — No, and the boundary document argues the opposite.
Three simulated enrichment providers exist to prove the waterfall mechanics — batching, per-field order,
fallback on miss, cost accounting — and that is precisely where you stop and buy the real thing, because
Clay's product is a provider network, not a spreadsheet. GTMOS keeps the merge policy, because that is
where the business logic is: Clay tells you what a provider said; it does not decide whether that should
overwrite what you already believe.

*"Your score doesn't predict anything."* — Correct, on this data, and the repository is what establishes
it. Structural AUC 0.537, interval 0.485–0.589. Then be precise about why, because the reason is the
interesting part: range restriction biases it down (only accounts above a propensity floor were ever
contacted), and targeting feedback biases it up (measured across all 1,957 non-excluded accounts it rises
to 0.553, but the uncontacted ones count as failures partly because the score said so). The truth is
between them and neither number is causal. The only unbiased design is a randomised holdout on the target
list, which this system cannot run, because it sends nothing.

*"Why should I believe the integrations work at all?"* — Do not claim more than the evidence. n8n is
verified by execution with reproducible commands in `docs/n8n.md`, including a deduplication proof where
one batch was delivered three times with different attempt numbers and produced one event whose duplicate
count went 0 → 1 → 2, and an error-workflow proof where another workflow was deliberately broken. Workflow
`04-crm-update-to-rescore.json` calls `api.hubapi.com` and is reported as not executed. HubSpot's live
adapter is implemented against current documented APIs and has never run. Clay's contract endpoint
reports `verified_against_live_clay: false` about itself.

### What NOT to claim, ever

- Do **not** say any integration is "live" or "connected" except n8n, and for n8n say "runs locally in
  Docker", not "in production".
- Do **not** say GTMOS has synced to a real HubSpot portal, received an event from a real PostHog
  project, or read a row from a real Clay workspace. None of those has happened.
- Do **not** say it has sent an email, a LinkedIn message, or anything else to any person. There is no
  sender. `outbound_send_enabled` is `false` and there is no code path behind it. Drafts stop at `ready`.
- Do **not** quote the total-score AUC of 0.593 as the result. It leaks by construction.
- Do **not** quote matcher precision as "96%" without the interval. It is 0.962 on 79 attempted matches
  with a 95% interval of 0.894–0.987 — 116 held-out cases cannot distinguish that from 0.90, and the
  evaluation document says so explicitly.
- Do **not** call the score a model, a prediction, or AI. It is a hand-weighted heuristic and the whole
  argument depends on being straight about that.
- Do **not** claim the demo's operational history is all real execution. Recent runs were executed by the
  engine; older workflow runs, sync runs and webhook events are seeded synthetic history, and the UI
  labels them as such.
- Do **not** claim any paid model call was made, or that generated prose came from a hosted model. The
  default writer is deterministic and the running system reports `llm: {mode: "demo", model: null}`.

### One more, if they ask what you would change

"Two things, and they're related. I'd split the score into a fit score and an engagement score and never
add them. Combining them is convenient for sorting a list and it's exactly what makes the evaluation
uninterpretable — engagement points come from replies, so the total score partly predicts itself, and
splitting them would have given me a clean number from day one instead of a document explaining why the
flattering one is wrong. Second, I'd snapshot the score as of every touch rather than only its current
value, because without point-in-time features you cannot honestly backtest anything, and retrofitting
that is the single hardest piece of building a real model later. The thing I wouldn't change is the
boundary — three simulated enrichment providers to prove the mechanics, and then stop."

---

## Appendix: numbers in this course, and where they came from

Every figure above was read on 2026-09-23 from the running API (`localhost:8010`) or from Postgres
directly, not from prose. The generated file `docs/demo-numbers.md` (produced by `make docs-numbers`) is
the canonical source for routing, experiment, data-quality and deliverability figures; the scoring
figures regenerate with `make backtest`. If a number in any prose document disagrees with the generated
file or the API, the generated file and the API are right.

Three places where prose in this repository has drifted from the running system, current as of this
reading:

Writing this course turned up three, and all three have since been corrected at source — they are
recorded here because the *pattern* is worth knowing, not because the numbers are still wrong.

- **Table count.** The `public` schema holds 41 tables, one of which is `alembic_version`, Alembic's own
  migration bookkeeping. The domain schema is 40. Both numbers are true and they answer different
  questions; documents now say "40 domain tables" so it is clear which.
- **The 90-day outbound funnel** in `docs/gtm-concepts.md` had drifted a few per cent across every stage.
  It now reads from `GET /api/v1/analytics/overview`, and the prose says to run the endpoint rather than
  trust the line.
- **The reverse-ETL preview** in `docs/crm-sync-design.md` quoted 635 considered / 635 unchanged against
  a live 850 / 850.

None of them changed an argument. All three are the ordinary rot of hand-typed numbers over a reseeded
dataset, which is exactly why the headline figures live in `docs/demo-numbers.md` and are regenerated by
`make docs-numbers` rather than maintained by hand. **Volunteering that mechanism unprompted is a better
interview move than quoting any single figure**, because it answers the question behind the question: not
"is this number right today" but "how would you know when it stopped being right".
