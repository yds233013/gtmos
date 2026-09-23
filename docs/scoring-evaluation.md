# Scoring evaluation

This document answers three questions about the GTMOS account score:

1. Is it a model? (No. It is a hand-weighted heuristic, and the difference matters.)
2. Does it rank accounts better than chance? (Weakly, and the honest number is smaller than the
   flattering one.)
3. What would have to change to make it a real model, and what would that cost?

The numbers come from `python -m gtmos.backtest`, which is reproducible from the seed. The current
output is committed at [`scoring-backtest.md`](./scoring-backtest.md); the API serves the same report
at `GET /api/v1/analytics/scoring-evaluation`. **The dataset is simulated.** Nothing here is evidence
about real-world conversion; it is evidence that the evaluation machinery works and is not flattering
itself.

---

## 1. Heuristic, not a model

| | GTMOS score today | A predictive model |
| --- | --- | --- |
| Weights | Set by hand in the ICP definition (Fit 35, Intent 25, Timing 15, Technical 15, Engagement 10) | Learned from labelled outcomes |
| Fitting | None. No training set, no loss function, no holdout | Fit on a training split, tuned on validation, reported on test |
| Explanation | Exact: every point traces to a named rule with evidence | Approximate: SHAP or coefficients, and only for the features the model saw |
| Failure mode | Wrong *opinions* — a weight nobody re-examined | Wrong *fit* — drift, leakage, class imbalance, spurious features |
| Changing it | Edit the ICP, re-score, diff | Retrain, revalidate, re-deploy, monitor |

The score is deliberately the first column. On a new territory with no outcome history there is nothing
to learn from, and a heuristic a revenue leader can argue with beats a model nobody can interrogate.
The product never calls it AI, ML or a prediction; `docs/gtm-concepts.md` and the UI call it a
rules-based score.

That choice has a cost, and this document is the bill: a heuristic that is never evaluated is just an
opinion with a number attached.

## 2. Method

**Population.** Accounts that were ever contacted and are not grade X. An uncontacted account cannot
book a meeting, so including the untouched majority would measure which accounts reps chose to work —
a decision the score itself drove — rather than which accounts convert. Grade X accounts are exclusions
(sanctioned country, excluded industry, below the employee floor), not low rankings, so they are
reported separately.

**Outcomes.** Two binary labels from stage history: the account ever reached `meeting`, and the account
ever reached `opportunity`. Stage transitions are used rather than activity counts because they are the
same events the funnel reports, so the backtest and the funnel cannot disagree.

**Metrics.**

- **AUC** (Mann-Whitney form, ties counted as half): the probability a converting account outranks a
  non-converting one. 0.5 is a coin flip. Reported with a Hanley–McNeil 95% interval, because an AUC
  without an interval is a number pretending to be a finding.
- **Conversion by bucket** — equal-count bins from the top of the list down, plus conversion by grade,
  each with a Wilson interval and a lift against the base rate. Buckets under 30 accounts are flagged;
  a 33% conversion rate on six accounts is not a fact.
- **Precision@K** — what a rep actually experiences: work the top 50/100/250/500 accounts, how many
  convert, versus what shuffling the list would have given.

**Score variants.** The same outcomes are evaluated against three nested slices of the score, which is
the whole point of the exercise:

| Variant | Components | Leakage |
| --- | --- | --- |
| Structural | Fit + Technical | None. Firmographics and technographics, all known before first contact. |
| Pre-engagement | + Timing + Intent | Low. Signals are external events, except signals GTMOS itself caused (a webinar we ran), which V1 does not separate out. |
| Total | + Engagement | **Leaks by construction.** Engagement points are awarded for replies and meetings; "booked a meeting" is the outcome. |

## 3. Results

From the committed backtest, on the contacted cohort (n = 1,212, 139 meetings, base rate 11.5%):

| Variant | AUC (meeting) | 95% CI |
| --- | ---: | :---: |
| Structural | 0.537 | 0.485–0.589 |
| Pre-engagement | 0.553 | 0.501–0.606 |
| Total | 0.593 | 0.540–0.645 |

**Read the first row, not the third.** The total score looks meaningfully better than chance, but
+0.056 of that AUC is circularity: accounts that replied scored higher *because* they replied. The
structural score — the part that is usable for prospecting, before anyone has been contacted — has an
interval that includes 0.5. **On this dataset the structural score is not distinguishable from random
at the 95% level.** The report says so in its own warnings rather than leaving the reader to notice.

Conversion by grade is nonetheless ordered correctly:

| Grade | Accounts | Meetings | Rate | 95% CI | Lift |
| --- | ---: | ---: | ---: | :---: | ---: |
| A | 6 | 2 | 33.3% | 9.7%–70.0% | 2.91× |
| B | 160 | 28 | 17.5% | 12.4%–24.1% | 1.53× |
| C | 448 | 54 | 12.0% | 9.4%–15.4% | 1.05× |
| D | 598 | 55 | 9.2% | 7.1%–11.8% | 0.80× |

A's interval is enormous — six accounts, 9.7% to 70.0%. **B versus D is the only comparison here that
survives contact with a confidence interval**, and the opportunity outcome puts A (16.7%) and B (15.6%)
within a rounding error of each other. The integration test only asserts ordering across bands with at
least 100 accounts, because asserting it on six would be a coin flip dressed as a regression test.

### Why the structural number is so weak

Two effects, pulling in opposite directions, and neither is fixable by better arithmetic:

- **Range restriction.** The demo's outbound motion only contacts accounts above a propensity floor,
  which is correlated with fit. The score is therefore graded on the list it selected: the low-fit tail
  that would make it look good was never worked. This biases the AUC *down*.
- **Targeting feedback.** Measured across all 1,957 non-excluded accounts instead, structural AUC rises
  to 0.553 — but now every uncontacted account counts as a failure, and they went uncontacted partly
  because the score said so. This biases the AUC *up*.

The truth lies between 0.537 and 0.553, and neither number is a causal claim. **The only unbiased
design is a holdout: contact a random sample of accounts regardless of score, and compare conversion
across score bands.** GTMOS does not run one, because the demo sends no email. In production this is
a standing 5% randomised holdout on the target list, refreshed quarterly — the same discipline the
experiments page applies to messaging, applied to targeting.

## 4. Grade thresholds

The bands were originally A ≥ 80, B ≥ 65, C ≥ 50 — round numbers chosen before anyone looked at the
score distribution. The distribution says the 99th percentile is 72, because a score near 100 requires
an account to max fit, technical, intent, timing *and* engagement simultaneously, which essentially
never happens. Grade A held **one account in 2,006**: a band with no list in it.

Bands exist to drive action — A: work today, B: sequence, C: nurture, D: leave alone — so the
boundaries now come from the distribution and from how much a team can actually work:

| | Old (80/65/50) | New (72/58/45), as they stand today |
| --- | --- | --- |
| A | 1 account (0.05%) | 8 accounts (0.4%) — a day's list |
| B | 64 (3.2%) | 204 (10.2%) — a quarter's list |
| C | 571 (28.5%) | 639 (31.9%) |
| D | 1,321 (65.9%) | 1,106 (55.1%) |

The "New" column is the **current** distribution, regenerated from `docs/scoring-backtest.md`, not the
distribution at the moment the thresholds were chosen. It has moved since: adding disqualifying signals
roughly halved grade A, because a penalty can drop an account out of a band. Saying so matters more than
the numbers do — the thresholds were set against one distribution and are being reported against another,
and a table that quietly showed the old figures would be hiding exactly that.

The shape is what the change was for: a workable A list, and a B list a team can sequence.

The conversion ladder above was checked after the change and is monotonic for meetings. **That check is
in-sample**: the same accounts that set the bands validated them, so it is a sanity check, not evidence
of predictive power. Thresholds fitted to outcomes on the same data would be overfitting; these were
fitted to the *distribution*, with outcomes used only to confirm nothing is inverted.

### One thing the simulation had to get right

Disqualifying signals subtract points. When they were first added, the backtest got **worse** — grade A
fell to a 10% meeting rate, below grade D. That was an artefact, not a finding: the negative signals were
generated after the journeys, so they were pure noise added to the score with no corresponding effect on
the simulated outcomes. The score was being penalised for modelling risk correctly.

The fix was in the simulation, not the score: an account with a competitor already in production, or a
departed champion, or an unsubscribe on file, now genuinely engages less (`_negative_drag` in the seed),
with severity mirroring the score penalties. The ladder recovered to 33% / 17.5% / 12% / 9.2%.

This is worth stating plainly because it is the failure mode of every simulated evaluation: **you can
make a model look good by changing the world it is measured against.** The change here is defensible —
it makes the simulated world behave the way the real one does — but a reader should know it happened and
be able to find it. It is one function, and it is named.

## 5. Known weaknesses

1. **Scores are evaluated at their current value, not as of the moment of contact.** GTMOS stores score
   history, but the seed does not snapshot a score per touch, so the total-score variant is measured
   after the outcome it predicts. The structural variant is largely immune (firmographics barely move),
   which is another reason to read that row.
2. **No holdout, therefore no causal claim.** See above.
3. **Engagement points are in the product score at all.** They are useful for prioritising *follow-up*
   and harmful for evaluating *targeting*. A cleaner design splits the number into a fit score and an
   engagement score and never adds them; that is a V2 change with UI consequences.
4. **One workspace, one ICP version, simulated data.** No cross-territory validation, no drift tracking.
5. **The outcome is a stage transition**, which a human sets. Stage hygiene noise is measurement error
   the backtest cannot see.

## 6. What a predictive model would take

Not "add a model" — here is the actual bill:

- **Labels**: ~1,000+ contacted accounts with clean outcomes and dates, so training rows can be built
  as of a decision time rather than as of today. GTMOS's stage-transition history is the right shape;
  it needs volume and a point-in-time feature store, otherwise every feature leaks.
- **Features as-of-date**: firmographics and signals reconstructed at the moment of scoring. This is
  the single hardest piece and the usual cause of models that look excellent offline and fail live.
- **A holdout**, as above, or the model will learn to reproduce the targeting rules it was trained
  beneath.
- **Calibration, not just ranking**: a rep needs "22% chance of a meeting", which means a reliability
  curve and a Brier score alongside AUC.
- **Monitoring**: feature drift, score drift, and a scheduled re-evaluation. A model nobody re-measures
  decays silently, which is worse than a heuristic nobody re-measures, because it looks authoritative.
- **Explanation that survives a rep**: per-account reasons good enough to put in an email. Today the
  heuristic gives this for free; a model has to earn it back.

Given a new ICP and no history, the right build order is what GTMOS does now — heuristic first, measure
it honestly, and only reach for a model once the labels exist and the evaluation harness is already
trusted. The harness in `gtmos/domain/evaluation.py` is deliberately model-agnostic: it takes
(score, outcome) pairs, so the day the score becomes a model prediction, the same backtest grades it.

## 7. Reproducing this

```bash
make reset      # deterministic demo dataset
make backtest   # regenerates docs/scoring-backtest.md
```

The statistics are unit-tested against hand-computed cases in
`apps/api/tests/unit/test_evaluation.py` (perfect, inverted, all-tied and half-tied rankings; Wilson
and Hanley–McNeil intervals; precision@K against shuffling). The report's honesty properties — the
population, the leakage delta, the small-sample flags, the band sizes — are asserted in
`apps/api/tests/integration/test_scoring_evaluation.py` so they cannot regress quietly.
