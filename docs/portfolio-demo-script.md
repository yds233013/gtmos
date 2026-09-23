# Portfolio demo script (≈3 minutes, recorded)

One story, told once: **a B2B AI company working out which accounts sales should focus on.** Nine beats,
one screen each. This is not a feature tour — if a page does not move the story forward, it does not
appear.

The **SAY** lines are the words to read aloud. Total spoken text: **437 words**, which is about
**2 minutes 55 seconds** at 150 words per minute. The timings below leave the remainder for pauses and
for the cursor to arrive.

---

## Before you record

- `make dev` (or `make up`) running; web on **http://localhost:3010**, API on **:8010**.
- `make reset` if the data has drifted. The dataset is deterministic relative to the day you seed it.
- Open these tabs in this order, so every cut is a tab switch rather than a page load:
  1. `/`
  2. `/signals`
  3. `/accounts/c5c23567-74a1-5483-bc14-224b4eb057e6`
  4. `/workflows/runs/911aed23-4489-4e2d-a6b5-da0045501f0e`
  5. `/routing`
  6. `/operations`
  7. `/experiments/provocative-subject`
- On tab 3, scroll so **Why this score** is in frame before you start; the tab strip
  (Overview / Signals / Buying committee / Research / Outreach / Activity / Automation & audit) is
  client-side, so you cannot deep-link to a tab — click it on camera.
- State to check before rolling: Kestrel Analytics is **A 98**, intent **96**, owner **Sam Okoro**,
  stage **Opportunity**, and the top of `/` shows it first under **Act now**.
- Browser at 1440px or wider. The **DEMO** banner stays visible the whole time — leave it in frame.

---

## Beat 1 · Kestrel Analytics appears

**[0:00–0:20]** · Open `/`. Point at the **Act now** table, top row.

> **SAY:** "This is GTMOS. We sell reliability tooling to AI companies, and the question is always the
> same: who should sales call today? Two thousand accounts, one seller, and one rep's morning to spend.
> Top of the list is Kestrel Analytics. Score of ninety-eight, intent ninety-six, and a signal from two
> hours ago."

*(52 words)*

---

## Beat 2 · Product and signal activity changes its context

**[0:20–0:40]** · Switch to `/signals`. The newest five rows are all Kestrel.

> **SAY:** "Here's where that came from. Three people at Kestrel connected a production integration,
> crossed the free-tier usage threshold, and viewed pricing — all in the last few hours. None of those
> alone means anything. Together they're a team adopting the product without ever talking to us."

*(45 words)*

---

## Beat 3 · GTMOS explains the score

**[0:40–1:02]** · Switch to the account tab. **Why this score** is already in frame. Hover the
**AI/ML hiring surge** row.

> **SAY:** "So the score moves. And it explains itself. Ninety-eight out of a hundred: fit thirty-five,
> intent twenty-five, timing thirteen, technical fifteen, engagement ten. Every point is a rule with
> evidence behind it. Fourteen open AI roles, seen six days ago, ninety-two percent confidence, decayed
> over a forty-five-day half-life — that's eight point eight points, not ten."

*(55 words)*

---

## Beat 4 · It crosses the qualification threshold

**[1:02–1:16]** · Same page. Scroll to **Recent signals** and point at *Product-qualified account*.

> **SAY:** "That crosses a line. Product-qualified at ninety against a threshold of fifty-five — and no
> single behaviour could have got there on its own, which is the whole point of the rule. Crossing it
> fires an event."

*(36 words)*

---

## Beat 5 · A workflow executes

**[1:16–1:36]** · Switch to the run tab
(`/workflows/runs/911aed23-4489-4e2d-a6b5-da0045501f0e`). Scroll the step timeline, then stop on
**Identity & idempotency**.

> **SAY:** "The event runs a workflow. Seven steps: enrich, rescore, buying committee, research, draft,
> route, sync. Eight hundred and sixty-eight milliseconds, every step's input and output stored. And an
> idempotency key — workflow, version, trigger type, event id — unique in Postgres. If that webhook
> arrives twice, this run does not happen twice."

*(50 words)*

---

## Beat 6 · Routing decides ownership

**[1:36–1:52]** · Switch to `/routing`. Expand the top row of **Recent decisions** (Kestrel Analytics,
*1 conflict*).

> **SAY:** "Step six picks the owner. Two rules matched. The high-intent strategic rule won on priority
> — twenty beats thirty — and the loser is recorded with the reason. Sam already owned it, so nothing
> moved: ownership is respected unless a rule says otherwise."

*(41 words)*

---

## Beat 7 · CRM sync happens

**[1:52–2:15]** · Switch to `/operations`. Scroll to **Reverse ETL · HubSpot companies**, with the
**SIMULATED** badge in frame.

> **SAY:** "Then it writes to the CRM. Only fields GTMOS owns — the gtmos-underscore ones. Name and
> domain on create, never on update, so a reverse-ETL push can't overwrite a rep's correction. Eight
> hundred and fifty companies considered, all unchanged, so nothing was written. And it says SIMULATED,
> because this adapter has never touched a real portal."

*(55 words)*

---

## Beat 8 · Did the strategy work?

**[2:15–2:35]** · Switch to `/experiments/provocative-subject`. The red verdict banner is at the top;
scroll just enough to show the **Guardrails** table underneath.

> **SAY:** "Does any of it work? Here's a subject-line test. The treatment wins replies by sixteen
> percentage points, p below nought point nought nought one. And the recommendation is do not ship —
> unsubscribes went from zero to two point nine percent. Winning on replies while burning the sending
> domain isn't winning."

*(50 words)*

---

## Beat 9 · It is observable

**[2:35–3:00]** · Back to `/operations`, top of page (stat row and **Webhook health**).

> **SAY:** "And you can see all of it. Failure rates, dead letters, webhook health, sixty re-deliveries
> absorbed without reprocessing. One integration here has genuinely executed against a real tool. The
> page says so itself, rather than showing four green badges. Everything you just saw is synthetic data
> and nothing was ever sent to anyone."

*(53 words)*

---

## Word count

| Beat | Words |
| --- | ---: |
| 1 · Kestrel appears | 52 |
| 2 · Signal activity | 45 |
| 3 · Score explained | 55 |
| 4 · Threshold crossed | 36 |
| 5 · Workflow executes | 50 |
| 6 · Routing | 41 |
| 7 · CRM sync | 55 |
| 8 · Experiment | 50 |
| 9 · Observability | 53 |
| **Total** | **437** |

437 words ÷ 150 wpm ≈ **2 min 55 s** spoken.

---

## If something looks different

Every number above was read off the running app, and the demo dataset is a rolling window, so it moves.
Do not read a figure you have not just seen on screen — say what is there instead.

- **Kestrel is not first under *Act now*, or the score is not 98.** Run `make reset`. The ordering is
  by intent, and a reseed on a different day shifts the decay maths by a point or two. If it is close
  (A grade, high 90s), just say the number you can see.
- **The run URL 404s.** Run IDs are per-seed. Open `/workflows`, filter to **Succeeded**, and take the
  newest row labelled **EXECUTED** (not *HISTORY (synthetic)*) for Kestrel Analytics. Any
  seven-step *Funding signal → research → outreach draft* run tells the same story; the step count and
  duration in the SAY line will need updating.
- **The routing decision shows `assigned` rather than `kept owner`.** Then Kestrel was unowned when the
  router last ran. The point survives: say which rule won and why the other lost, and drop the sentence
  about respecting ownership.
- **Reverse ETL shows changes rather than 850 unchanged.** Something rescored since the last sync.
  That is a better demo, not a worse one — say "only the fields that actually changed get written".
- **`/operations` webhook counts differ.** Read the number on screen. The point is that re-deliveries
  are absorbed, not the exact count.
- **A button does nothing on first click in dev mode.** The page is still compiling. `make up` builds
  for production and does not do this.
- **You want to show a failure.** `/operations` → **Workflow runs needing attention** always has dead
  letters, but they are labelled **HISTORY (synthetic)** and their retry button is disabled. Say so if
  you point at them; do not imply the engine just produced them.

Nothing in this script sends anything. There is no send button to avoid.
