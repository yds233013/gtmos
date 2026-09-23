# Phase 3 final report

Phase 3 had one goal: move GTMOS from a high-quality *simulation* of a modern GTM stack toward
software that can actually interoperate with the tools GTM teams use — HubSpot, n8n, PostHog and
Clay — and to be honest, in the product itself, about how far each of those connections has really
gone.

The short version of the outcome: **one integration now genuinely executes, one runs on a simulated
adapter, two are contracts exercised locally, and the application says exactly that on its own
integrations page.** Nothing anywhere claims a connection that has not happened. Getting to a state
where that sentence is true — rather than a state where four green badges hide four different
realities — was most of the work.

- **Commit and diff totals are deliberately not quoted here.** They were, and they were wrong by three commits within an hour of being written, which is a small joke at the expense of a report about rigorous self-measurement. `git diff --shortstat cc209e9..HEAD` is the number, and it is right by construction.
- **465 backend tests** (210 unit, 255 Postgres integration), 14 component, 25 e2e, 113 dbt tests — all
  passing. Migrations apply from empty with no model drift; both Docker images build and the API
  image serves live data.
- **Four genuine bugs found and fixed**, each by a mechanism built in this phase rather than by
  reading code.

---

## 1. What changed, in the order it mattered

### The HubSpot adapter was audited against current documentation, and three things were wrong

Not "could be improved" — wrong, in ways that would have failed on first contact with a real portal.

1. **Signature scheme.** GTMOS implemented only v3. HubSpot documents **private apps** as signing
   with **v1**: a plain SHA-256 hex digest of `clientSecret + body`, with no timestamp. A private app
   is exactly what a free developer test account uses, so every delivery from the most likely test
   environment would have been rejected — and would have looked like a broken integration rather
   than a wrong verifier. v1 and v2 are now accepted with v3 preferred, and because v1 carries no
   timestamp and therefore no replay window, the verifier returns a detail string saying so and the
   Operations page shows which scheme verified each delivery. A weaker guarantee, labelled as one.
2. **URI handling.** The v3 verifier ran `unquote()` over the request URI before hashing. HubSpot
   signs the URI *as sent*. Any request carrying a percent-encoded character would have failed. There
   is now a test that signs the decoded form and asserts it does **not** verify.
3. **Association types.** Contacts and deals were being synced with no associations at all, and the
   type ids in the notes conflated two different things. `1` / `2` / `5` / `6` are the **primary**
   variants; `279` / `280` / `341` / `342` are the general ones. Writing only the general type
   produces records that look associated in the UI and behave as orphans in a report, because
   territory assignment and most out-of-the-box reporting key off the *primary* company. GTMOS writes
   the primary types.

Contact and deal sync were then built for real, with the same bounded-retry and payload-hash
machinery as the company sync, and `docs/hubspot-live-setup.md` documents the exact twenty-minute
path to a live connection — including a table of what will go wrong, ranked by how often it actually
does.

### n8n is the one integration verified by execution

Six workflows in `integrations/n8n/`, version-controlled as JSON, running on a **pinned** image
(`n8nio/n8n:2.40.5` — an orchestration layer that silently changes version under you is precisely the
thing this project should know better than). They reach the API at `host.docker.internal:8010`, sign
requests with the shared HMAC secret, and they genuinely fire.

Workflow 05 exists specifically to prove deduplication: three deliveries of the same HubSpot event
array — the second with an incremented `attemptNumber`, the third with the array order reversed —
produce **one** stored event. That matters because the naive idempotency key, a hash of the raw body,
treats every HubSpot retry as a new event. GTMOS keys on the sorted set of member `eventId` values
instead. Workflow 06 is an error handler that was itself made to fail on purpose, to prove it fires.

The gotchas are written down in `docs/n8n.md` because they each cost real time: the CLI publishes to
the database and a *running* n8n does not notice, so the container must be restarted; `import:workflow`
always deactivates; `N8N_WEBHOOK_URL` replaced the deprecated `WEBHOOK_URL`; `/webhook-test/` only
fires while the editor is open.

### PostHog became a product-led GTM path, with a real PQL rule

`domain/pql.py` holds a composite, account-level, time-windowed rule — five weighted criteria over a
14-day window, threshold 55, so **no single criterion qualifies an account alone**, and it fires once
per account per week. The weights encode an argument: connecting a production integration scores 30
because it carries switching costs; viewing pricing scores 10 because it is commercial intent that is
cheap to fake. A reasonable GTM leader can disagree with those numbers, which is the point — they are
in a file, versioned, with the reasoning attached.

The constraint that shaped the design is that PostHog's group analytics is a paid add-on and its
outbound HTTP webhook destination appears to be gated too. So GTMOS accepts PostHog's documented
payload shape at a boundary it controls, and the same endpoint works whether events arrive from
PostHog Cloud, from n8n, or from a replay script. That is also just better engineering.

### Clay was built against the documented contract, and labelled as unrun

No Clay account exists, nothing was purchased, and the integration has never been run against a live
workspace. What exists is the boundary: the Public API client, signed-webhook verification
(`X-Clay-Signature`), and ingestion that maps enriched rows into GTMOS's existing provenance model —
a Clay value enters through the same merge policy as any other provider and gets no special authority
for having been bought. `docs/clay-live-setup.md` says plainly what is unrun and what it would take.

### A golden flow that runs the whole thing end to end

`make golden-flow` drives one account through twenty steps across every boundary — product events in,
identity resolution, signals, scoring, the PQL rule firing, research, a drafted message into the
approval queue, routing, CRM sync, the reverse-ETL diff, and the audit trail — deterministically, with
a `--run-key` so it is idempotent. `VIA_N8N=1` routes the inbound half through the real n8n container
rather than posting directly, which is how the n8n path stays honest.

### The integrations page

The surface that makes the rest of this legible. Two independent axes — **mode** (what the running
configuration does) and **verification** (how much of it has ever actually happened) — because
collapsing them into one badge is how integration pages start lying. There is no "Connected" state
anywhere. Three of four boundaries carry an explicit **Real service never reached** badge. Every
number is derived from stored deliveries, sync runs and enrichment attempts, not from configuration,
and the requirements list reports the *presence* of a credential and never its value.

As of this writing: n8n `live` / verified by execution / real service reached; HubSpot `demo` /
simulated; PostHog and Clay `test` / verified locally. The headline number on the page is **1 of 4**.

---

## 2. The four bugs, and what found them

None of these came from re-reading code. Each came from a mechanism built to look for them.

**The failure tournament found that permanently-invalid payloads were retried forever.** A malformed
payload that could never succeed was being acknowledged with `202` and queued for retry, indefinitely.
The fix introduces `PermanentError`, which marks a delivery `rejected` and returns `422` — a distinction
between "try again" and "this will never work" that the endpoint previously did not make. Three
existing tests had pinned the buggy behaviour and had to be updated, which is its own small lesson
about what a test suite guarantees.

**The security review found a real prompt-injection vulnerability that Phase 3 itself opened.** Clay
writes account fields (`industry`, `city`, `technologies`) and contact records (`name`, `title`); all
of it flowed into research evidence packs and into generated claim text unsanitised. Setting an
account's industry to a sentence containing an embedded instruction produced a research brief
repeating that instruction verbatim, *with a citation*. Reps paste briefs into outbound email, so an
attacker able to influence any enrichment source could put fabricated commercial facts into a seller's
mouth. Phase 2's sanitiser covered signal titles on the entirely reasonable assumption that
firmographics were GTMOS-owned facts; Phase 3 made that assumption false. **The general lesson is that
a trust boundary is a property of where data comes from, not of which field it lands in** — adding an
integration silently re-classifies fields that were previously safe. Sanitisation now covers both the
evidence pack and the claim text, because cleaning only the pack was not enough: the claim builder
reads the account dict directly.

**The dbt suite found that the warehouse contract had drifted.** The product-qualified workflow
introduced two activity types, `task` and `notification`, that the marts' `accepted_values` test did
not know about. Adding them required checking that every `is_*` flag tests explicit membership, so
neither counts as an attributable touch — which is the part that would have silently corrupted
attribution had it gone the other way.

**The quality-gate run found the golden flow calling correct behaviour a failure.** Steps 5 and 6
counted engagement rows inside a ten-minute window, so a second run under the same run key reported
FAIL — even though the event ids are derived from the run key precisely so that a replay collides
with itself. The harness was reporting working idempotency as a defect, which is the opposite of the
signal it exists to give. Both steps now look rows up by the run's own dedupe keys and say when the
rows were already there. A harness that cries wolf on a re-run is a harness nobody re-runs.

A fifth, smaller one is worth recording because of how it was found: the test suite was reading the
developer's `.env`, so adding two development secrets turned three passing tests red. A suite whose
behaviour depends on what happens to be in a local file is not a suite you can trust. `Settings` no
longer reads `.env` under test.

---

## 3. Honest status of every boundary

| Boundary | Mode | How far it has actually gone | What blocks the next step |
|---|---|---|---|
| **n8n** | Live | **Verified by execution.** 12 real inbound deliveries from the running container. Six workflows fire; dedupe and the error handler were each proved deliberately. | Nothing. This one works. |
| **HubSpot** | Demo | Simulated adapter exercised end to end; every sync it performs is labelled SIMULATED. The **live adapter has never run against a real portal.** | A developer test account, an access token, a client secret, and `HUBSPOT_LIVE_WRITES_ENABLED=true`. A human must sign in; that is the only reason it is not done. |
| **PostHog** | Test | Contract exercised locally: the documented payload shape is accepted, deduplicated, normalised and turned into signals. **Not one event has come from PostHog itself.** | A PostHog project, plus the group-analytics add-on and a webhook destination — both of which appear to be paid. |
| **Clay** | Test | Contract exercised locally against the documented Public API and signed-webhook shape. **Nothing has ever been requested from clay.com.** | `CLAY_API_KEY`, `CLAY_WEBHOOK_SECRET`, and a workspace on a paid plan for the HTTP API column. |

No email or message has ever been sent by this system, to anyone. No paid LLM call has been made;
generation runs on the deterministic demo writer. `LLM_ENABLED=false` and
`HUBSPOT_LIVE_WRITES_ENABLED=false` were pinned in `.env` for the duration and every command was run
with `ANTHROPIC_API_KEY=` explicitly emptied.

---

## 4. What I would do next, in priority order

1. **Connect HubSpot to a developer test account.** Everything is built and documented; it needs
   twenty minutes and a human login. This is the single highest-value remaining step, because it
   converts the largest boundary from "simulated" to "verified" and will certainly surface something
   the mocks did not.
2. **Reconciliation against the remote record.** Change detection compares the payload hash to *what
   GTMOS last sent*, never to what HubSpot currently holds. `external_records.remote_updated_at`
   exists in the schema and is never read or written. Until that closes, a `gtmos_*` field edited
   inside the CRM is invisible.
3. **Group the approval queue by contact.** The browser review found four pending drafts for the same
   person, two identically titled. Each is individually correct and collectively they are the exact
   noise the queue exists to prevent. The fix is a suppression window per contact per draft type —
   the same reasoning that makes the PQL fire once per week.
4. **Rate-limit the inbound webhook endpoints.** Signature verification and a 1 MB cap exist; a
   request-rate limit does not. Deliberately not fixed in-process, because in production it belongs at
   the edge and a naive in-process limiter gives false confidence in a multi-process deployment.
5. **Get real outcome labels.** Every evaluation in this repository runs on synthetic data, and the
   honest ceiling on what that can prove is low. The matcher's held-out evaluation uses 116 cases,
   which is not enough, and `docs/scoring-evaluation.md` says so rather than rounding up.

---

## 5. What this phase is evidence of

Three things, and they are the reason the work was worth doing rather than just the code that came
out of it.

**Real tool knowledge, verified rather than recalled.** Every load-bearing vendor fact in this phase
was checked against current documentation, and three of them turned out to contradict the obvious
assumption — HubSpot's private-app signature scheme, the primary-versus-general association types, and
`domain` not being a unique property. `docs/phase3-tool-research.md` marks thirteen cells
**Unverified** rather than guessing, which is a better signal of how the research was done than any
of the cells that are filled in.

**A working understanding of the buy / orchestrate / build boundary.** The temptation in a portfolio
project is to rebuild everything so the README can claim the system replaces a stack of well-funded
products. GTMOS explicitly does not send email, does not store events, does not run a provider
network, and does not offer a workflow canvas. What it owns is the judgement layer — what a signal
means, what an account is worth, who works it, what may be said to them, and whether any of it
worked — and the test for whether something belongs there is whether a reasonable GTM leader would
want to argue with it.

**A refusal to overstate.** The integrations page says 1 of 4. The security review lists what an
attacker could still do. The evaluation docs state their sample sizes and their limits. The failure
tournament marks one of its five invariants *qualified* and explains that the strength comes from not
applying inbound changes at all rather than from a clever guard. That habit is worth more than any
individual feature here, because it is the thing that makes every other claim in the repository
checkable.
