# Phase 4 handoff — release readiness

The repository is ready to publish. Nothing here requires more engineering; what remains is a short
list of things only the account owner can do, listed in §17.

---

## 1 · Final project description

GTMOS is an AI-native GTM control plane. It connects product signals, enrichment, CRM state and custom
decision logic to work out which accounts deserve attention, why now, who owns them, and whether any of
it worked. The point of it is the judgement layer — what a signal means, what an account is worth, what
may be said to a stranger, and what the system should refuse to do — written down with its reasoning so
it can be argued with specifically.

## 2 · Final architecture summary

Four vendor systems around one built core. **PostHog** observes the product, **Clay** buys commodity
enrichment, **n8n** moves bytes between systems where a RevOps person can edit it without a deploy, and
**HubSpot** is where reps work. GTMOS owns everything that constitutes a judgement: ingestion with
verification and dedupe, identity resolution, signal normalisation and decay, the product-qualified
rule, explainable scoring, the enrichment merge policy, evidence-grounded generation with guardrails,
routing, an idempotent workflow engine, reverse ETL with field ownership, governance, and the analytics
and evaluation that grade all of it.

Postgres is the source of truth (40 domain tables); Redis is delivery, never truth — workflow runs are
rows first, enqueued after commit, with a sweeper for anything stuck. The deterministic core is pure
functions under test; a model only ever writes prose over an evidence pack the system already holds.

## 3 · Strongest five engineering accomplishments

1. **Idempotent workflow execution under real concurrency.** `SELECT … FOR UPDATE SKIP LOCKED`, proved
   by a barrier-released race on two real database connections whose assertion — that the loser did not
   *block* — is what distinguishes it from plain `FOR UPDATE`.
2. **A webhook idempotency key that survives the vendor's actual retry semantics.** HubSpot posts an
   array and increments `attemptNumber`, so a body hash dedupes nothing; the key is the sorted set of
   member event ids.
3. **Reverse ETL that cannot clobber a human.** Update payloads carry `gtmos_*` fields only; upserts key
   on a custom unique property because HubSpot does not deduplicate API-created companies on `domain`;
   inbound changes are logged and never applied, which breaks the sync loop deliberately.
4. **A trust boundary that follows provenance rather than field name.** Sentence-level sanitisation of
   untrusted enrichment text, applied at both the evidence pack and the claim builder, after a real
   injection reached a research brief with a citation.
5. **Read-only mode as one edge check rather than thirty decorators.** Because a dependency has to be
   attached to every router, and the next route added is the one that forgets.

## 4 · Strongest five GTM accomplishments

1. **Explainable, versioned scoring** where every point traces to a named rule and its evidence, with
   per-type half-life decay from 14 to 365 days and six signal types that subtract.
2. **Experimentation that can reject a winner** — one-sided guardrails on bounce, unsubscribe, spam and
   negative reply, where a breach outranks any primary-metric win.
3. **A composite, account-level product-qualified rule** over a 14-day window, weighted toward acts with
   switching costs, thresholded so no single criterion qualifies alone, firing once per account per week.
4. **Speed-to-lead measured the way a practitioner defines it** — only genuine lead events start a clock,
   and *late*, *never touched* and *pending* are three separate numbers, not one hit rate.
5. **An enrichment merge policy that refuses to resolve a material conflict on confidence alone**, and
   raises a data-quality issue instead of silently overwriting.

## 5 · Final verified test counts

Every figure produced by running the thing that counts it, at `f3ac2d0`.

| Suite | Count |
|---|---:|
| Backend unit (pytest) | **210** |
| Backend integration (pytest + Postgres) | **262** |
| Frontend component (Vitest) | **14** |
| End to end (Playwright, production build) | **25** |
| **Total automated tests** | **511** |
| dbt **models** | 19 |
| dbt **tests** | **113** |

`dbt build` prints `TOTAL=132`, which is models plus tests, not a test count. Also green: ruff, eslint,
`mypy --strict`, `tsc`, the Next production build, migrations from empty with no model drift, the golden
flow 20/20 on both transports, and both Docker images.

## 6 · Final screenshots

Nineteen, all 2x, light mode, palette-mode PNGs under 800 KB, 7.5 MB total. **Fourteen were recaptured
in this phase** because they carried the Next.js dev-tools badge — a set-wide defect that had gone
unnoticed. One gap was filled: `19-research.png`, the evidence-grounded brief with its numbered
citations and `Hypothesis` badges. Five appear in the README; the rest are catalogued with captions in
`docs/screenshots.md`.

## 7 · Final README status

Rewritten and layered: 433 lines, down from 452 but reorganised so the differentiating material is at
the top rather than at line 225. Structure — one-sentence definition, demo banner, the four-point short
version, five demo screenshots, the problem, what it does, the golden flow, a colour-coded Mermaid
diagram separating bought from orchestrated from built, six engineering highlights, integration
philosophy, failure handling, evaluation honesty, running locally, tests, demo-versus-live, limitations,
what next. All internal links resolve.

## 8 · Final demo script

Three, for three audiences: `portfolio-demo-script.md` (3 minutes, 437 spoken words, nine beats
following one account through every boundary), `60-second-demo.md` (152 words, no statistics, every
acronym glossed in the sentence that uses it), and `technical-demo.md` (10 minutes, every `file:line`
citation grepped before it was written).

## 9 · Final two résumé bullets

```
GTMOS — AI-Native GTM Infrastructure
Python · FastAPI · PostgreSQL · Redis/RQ · Next.js/TypeScript · dbt · Docker · n8n

• Idempotent execution end to end: workflow runs are Postgres rows claimed with
  SELECT … FOR UPDATE SKIP LOCKED, dead-lettered on exhaustion and resumable after,
  proved by a barrier-released race on two real database connections that a plain
  FOR UPDATE would not survive; inbound CRM webhooks key on the sorted set of member
  event ids, so a HubSpot retry with an incremented attemptNumber stores one event.

• Built the evaluation layer that grades the system's own output and then published the
  unflattering number: leakage-free scoring AUC 0.537 (95% CI 0.485–0.589) reported ahead
  of the contaminated 0.593, and one-sided guardrails that reject the seeded subject-line
  variant which lifted replies +16.3 pp because unsubscribes went 0.00% → 2.90%.
```

Full rationale, including which accomplishments were rejected and why:
[`final-resume-entry.md`](final-resume-entry.md).

## 10 · GitHub description

> An AI-native GTM control plane: product signal → enrichment → explainable scoring → routing →
> idempotent workflow → CRM reverse ETL → analytics. FastAPI, Postgres, Next.js, dbt, n8n. One of
> four integrations is verified by execution, the honest scoring AUC is 0.537, and the repo leads
> with both. Synthetic data only; it has never sent a message.

346 characters. Suggested topics: `gtm-engineering`, `revops`, `fastapi`, `nextjs`, `dbt`, `hubspot`,
`n8n`, `posthog`, `lead-scoring`, `reverse-etl`, `data-quality`, `experimentation`.

## 11 · Portfolio description

In [`portfolio-copy.md`](portfolio-copy.md) — title, subtitle, short description, tech stack, key
systems, architecture summary and what-I-learned, ready to paste.

## 12 · Deployment recommendation

**One Hetzner CX23 running the repository's existing `docker compose` behind Caddy for TLS — €5.99/month
including IPv4, about $7, plus roughly $1/month for a domain.** The deployment artefact already exists
and is exercised daily; the database does not expire, sleep or pause; the price is fixed on a system
that deliberately has no in-process rate limiting; and there is no cold start, which matters when the
audience is a stranger who clicks a link once. Runner-up if you do not want to be the operator: Railway
Hobby at roughly $10–12/month. Render's free tier is a trap — free Postgres now expires after 30 days
and free web services cold-start in about a minute. Full comparison with nine items marked
**Unverified**: [`deployment-plan.md`](deployment-plan.md).

## 13 · Public-demo safety status

**Safe to deploy publicly once `READ_ONLY=true` is set, and not before.**

Five of the seven stated requirements were already satisfied structurally: no external writes, no
emails or messages (there is no client to send with), no live CRM mutation by default, no LLM spending
by default, and no feature that needs a secret in order to render. Two were not satisfied at all, and
the gap was larger than earlier prose implied: of 36 mutating routes, four are admin-gated and two carry
a gate that is a no-op unless live writes are already enabled, leaving **24 reachable with no credential
in the most hardened configuration the route decorators support**. Verified empirically — rescore,
data-quality scan and the reverse-ETL run all returned 200 unauthenticated.

`READ_ONLY=true` now refuses every write at the edge, with three POSTs allow-listed because they compute
an answer without writing a row: the ICP preview, the routing simulator and the copilot. One live wire
was closed in code — `use_llm` on the research endpoint defaulted to `True` from the request body, which
is inert today but would have allowed unlimited anonymous billed calls on an instance with a key set.

Absolute rule for a public instance: **`LLM_ENABLED` stays false, `ANTHROPIC_API_KEY` is never set, and
`HUBSPOT_ACCESS_TOKEN` is never set.** Full audit: [`public-demo-safety.md`](public-demo-safety.md).

## 14 · Secret and history scan status

**Clean.** All blobs across the entire history scanned for `sk-ant-*`, `pat-na*`/`pat-eu*`,
`xox[baprs]-*`, `AKIA*`, `gh[pousr]_*` and PEM private-key headers — zero matches. The two locally
generated development secrets in `.env` were searched **by value** across all of history — zero matches;
`.env` has never been tracked and is git-ignored. Every email address anywhere in history is a synthetic
fixture on a reserved `.example` domain, except the author's own commit address, which is inherent to
publishing a git history rather than a leak. One machine-specific path was generalised.

**One thing to know, not a security issue:** `.git` is 67 MB, most of it successive versions of the
screenshot set. It clones fine and is far below any GitHub limit, but it can only be reduced *before*
the first push. Doing so means rewriting history, which has not been done.

## 15 · Git identity recommendation

**No history rewrite is needed, almost certainly.** GitHub attributes a commit by the author *email*,
not the author name; the name is a free-text display string it ignores. All 74 commits carry
`yashshah2311@berkeley.edu`. If that address is verified on `yds233013`, every commit already attributes
to that account. This could not be confirmed from here — reading the account's email list needs a token
scope the stored credential does not carry, and refreshing it unprompted is not something to do on a
guess. Check GitHub → *Settings → Emails*, add and verify the address if absent, and set a
per-repository `user.name` / `user.email` for future commits. Rewriting is the right tool only if the
address genuinely cannot go on the account, and must happen before any push.
Full reasoning: [`git-identity-review.md`](git-identity-review.md).

## 16 · Remaining limitations

Unchanged from Phase 3 and all documented in the README's own Limitations section: no reconciliation
against the remote CRM record; no conditional writes; a draft's cited evidence is never re-validated at
approval time; no inbound rate limiting (deliberate — it belongs at the edge); single-operator
authorisation with a caller-asserted audit actor; routing rules and workflow definitions are not
editable in the product; the approval queue does not group by contact; no supply-chain scanning; and
every evaluation runs on synthetic data with no real outcome labels anywhere.

## 17 · Exact steps requiring your action

1. **Verify the commit email.** GitHub → *Settings → Emails* on `yds233013`. Add and verify
   `yashshah2311@berkeley.edu` if it is not there. This is the only item that changes whether 74 commits
   attribute to you.
2. **Decide the display name.** `yds2330` reads as the *other* account. Set a per-repository identity.
3. **Decide on the 67 MB history.** Keep it (fine) or shrink it (needs a rewrite, before any push).
4. **Authorise the push.** Nothing has been pushed; no remote exists.
5. **If deploying:** buy a domain, create the host, and set `READ_ONLY=true` — and never set
   `ANTHROPIC_API_KEY` or `HUBSPOT_ACCESS_TOKEN` on it.
6. **Optional, highest remaining value for the project itself:** point the HubSpot adapter at a free
   developer test account. Twenty minutes and a login, and it converts the largest boundary from
   simulated to verified.

## 18 · Exact commands for release

**Not run. These require your explicit authorisation.** Run them in order, from the repository root.

```bash
# 0 · Confirm the identity you want on future commits (see §15 first)
git config user.name  "Yash Shah"
git config user.email "<the address verified on yds233013>"

# 1 · Final pre-flight — all must pass
make lint && make typecheck && make test && make e2e && make warehouse
git status --porcelain            # must print nothing

# 2 · Create the remote as PUBLIC and push
gh repo create gtmos --public --source=. --remote=origin \
  --description "An AI-native GTM control plane: product signal → enrichment → explainable scoring → routing → idempotent workflow → CRM reverse ETL → analytics. FastAPI, Postgres, Next.js, dbt, n8n. One of four integrations is verified by execution, the honest scoring AUC is 0.537, and the repo leads with both. Synthetic data only; it has never sent a message."
git push -u origin main

# 3 · Topics
for t in gtm-engineering revops fastapi nextjs dbt hubspot n8n posthog \
         lead-scoring reverse-etl data-quality experimentation; do
  gh repo edit --add-topic "$t"
done

# 4 · Homepage, once a demo exists
gh repo edit --homepage "https://<your-demo-url>"
```

Note that `gh` currently has two authenticated accounts with `yds233013` active; confirm with
`gh auth status` before step 2. The full checklist, including what each step assumes, is
[`github-release-checklist.md`](github-release-checklist.md).

## 19 · Git status

Clean. Zero modified, staged or untracked files. No remote configured. Branch `main`.

## 20 · Final HEAD

```
f3ac2d098a64468a547f96867a1141f4225ce745
f3ac2d0  Public-demo safety: a read-only mode, and the audit that justified it
```

74 commits total; 6 of them Phase 4, changing 42 files (+5,286 / −387).
