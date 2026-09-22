# Demo script (≈10 minutes)

Start from a fresh dataset for a predictable story: `make reset`, then open http://localhost:3010.
Everything shown is **DEMO** data and **SIMULATED** integrations; say so up front.

> **Opening line (15 s):** "GTMOS is the system a GTM engineer builds so a sales team always knows who to
> call, why now, and what to say, and so RevOps can see whether the machine is working. It's deterministic
> where money moves and uses AI only where evidence exists."

## 1. Command center (45 s): `/`

- Point at the **DEMO banner**: synthetic data, simulated CRM, deterministic AI mode, nothing is ever sent.
- Stat row: accounts, ICP accounts, meetings, pipeline created, open pipeline, won revenue, all computed live.
- **Act now**: the highest-intent A/B accounts. Note one is **Unowned**; we'll see why later (routing gap).
- **Does the score predict outcomes?** Meeting rate by grade among contacted accounts. Mention the caveat
  printed under it (engagement feeds the score, so a holdout backtest is the honest next step).

## 2. The flagship account (2 min): Accounts → Kestrel Analytics

- Header: A-grade 98, owner Sam Okoro (senior AE), stage Opportunity.
- **Why this score**: Fit 35/35, Intent 25/25 (capped), Timing 13/15, Technical 15/15, Engagement 10/10.
  Read one intent line aloud: *"14 open AI/ML roles, observed 6 days ago… 45-day half-life → 88% of 10 pts."*
  Every point is a rule with evidence. The input hash makes it reproducible.
- **Company data & provenance**: each field shows provider, confidence and timestamp. Demo providers are
  labeled.
- **Signals tab**: Series C ($120M, 12 days), Kestrel Copilot launch, new VP of AI, LLM-eval job posting, a free
  workspace → teammates → integration → usage threshold (a PQL).
- **Buying committee**: Priya Raman (Head of AI Platform) is champion because of her title, director
  seniority, free-product usage and meeting. Elena Park (new VP of AI) is economic buyer, Dana Whitfield (CTO)
  is sponsor. Show an **override** dropdown: manual choices survive recomputation.
- **Research**: every sentence carries evidence chips (E1…). Pain points are tagged **Hypothesis**. Research
  is a draft and never CRM truth.

## 3. Run the workflow (1 min): **Run signal → outreach workflow**

- Enrich → rescore → committee → research → draft → route → CRM sync (simulated).
- **Outreach tab** or **Approvals**: the email goes to **Elena Park**, not Priya: *"I've been working with Priya on
  agent reliability, and saw that Kestrel Analytics launched Kestrel Copilot…"* The account already has an open
  opportunity, so GTMOS multi-threads to the economic buyer and grounds the intro in a recorded meeting.

## 4. Approval queue (1 min): `/approvals`

- Reasoning chain: signal → pain hypothesis → value (from the seller's proof library) → question → CTA.
- Guardrails: numbers grounded, no unverifiable claims, verified signal, length, CTA, personalized, reachable.
- **Edit** the body to "we cut incidents by 73%" and save: `numbers_grounded` fails and **Approve is blocked**.
  Restore it, then approve, then mark ready. Say: "Ready means handed off to a sequencer. GTMOS never sends."

## 5. Automation you can trust (1.5 min)

- **Workflows**: each definition drawn as trigger → conditions → actions; the guarantees strip (idempotent,
  resumable, retries with backoff, dead letter).
- Open the run you just executed: step timeline, attempts, durations, outputs, correlation id, and the
  idempotency key (re-delivering the same event can't run it twice).
- Open a **dead-letter** run from history (labeled synthetic): the failing step, the exhausted attempts, the
  retry button (disabled for synthetic history).
- **Routing → simulator**: Enterprise NA, ICP 86, intent 72 → *Senior AE* wins over the territory rule
  ("lost: lower priority (30 vs 20)"). Switch region to **APAC** → *No routing rule matched*. That's the
  unowned account from step 1.

## 6. Did it work? (1.5 min)

- **Experiments → Funding-trigger vs generic**: deterministic hash assignment at the account level; treatment
  beats control on positive replies (**+11.6 pp, 95% CI +3.1 to +19.9, p = 0.008**), but meetings and
  opportunities are **not significant**. GTMOS refuses to claim more than the data supports.
- **Pipeline**: open deals by stage, velocity with its formula, stage-to-stage durations, attribution models
  side by side (first-touch vs last-touch vs linear vs U-shaped), and stuck accounts.

## 7. Is the machine healthy? (1.5 min)

- **Data Quality**: 11 rules; fix a duplicate-contact group with one click (merge, audited). Manual issues
  explain why they can't be auto-fixed.
- **Stack Inspector**: overall status, eight systems with evidence blocks, ranked automation opportunities
  (e.g. "Act on fresh buying signals automatically: 42 A/B accounts had a signal in 14 days with no outreach").
  Every number is a live query.
- **Copilot**: ask "Why did pipeline fall?" and open *How this was computed*: intent → approved metric →
  numbers. It never writes SQL.
- **Operations**: failure rates, dead letters, sync jobs (SIMULATED), webhook health, provider hit/error
  rates, correlation IDs.

## Closing (15 s)

"This is the infrastructure layer of GTM: explainable targeting, evidence-grounded AI with humans in the loop,
idempotent automation, and a system that audits itself. With credentials, the same boundaries talk to HubSpot,
PostHog and Claude."

## If something goes wrong

- Data looks different from this script → `make reset` (the dataset is deterministic relative to the day you
  seed it).
- A button seems unresponsive on first load in dev mode → wait for the page to finish compiling; production
  builds (`make up`) don't have this delay.
