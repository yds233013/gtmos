# Lead-to-account matcher evaluation

This document reports how accurate the lead-to-account matcher in `apps/api/src/gtmos/domain/matching.py`
is, and — more importantly — why the previous version of that claim did not mean what it said.

Everything here is reproducible without a database, a network call or an API key:

```
cd apps/api && uv run pytest tests/unit/test_matching_evaluation.py -q
```

The data is in `apps/api/src/gtmos/domain/matching_fixtures.py`. **It is synthetic and hand-labelled by
one person — me.** Section 8 says what that costs.

---

## 1. The number this replaces, and why it was not a number

The matcher used to report **precision 0.960, recall 0.923** on a labelled fixture of 36 cases. Both
figures were in-sample. The fuzzy-name threshold, 0.86, had been chosen by looking at that same fixture
and picking a value that sat above its highest-scoring known negative. So the fixture answered a question
it had already been shown the answer to.

That is not a rounding problem, it is a category problem. A threshold fitted to a set and then measured on
it produces an upper bound on performance, not an estimate of it, and no amount of care in the labelling
fixes that. The second problem compounds the first: 36 cases cannot distinguish 0.96 from 0.89. The 95%
Wilson interval around 24 correct matches out of 25 runs from 0.80 to 0.99. Three decimal places on a
sample that small is decoration.

So the claim was replaced rather than repaired.

## 2. Method

**Dataset.** 219 labelled cases against a 47-account synthetic CRM. Each case is a `Lead` (email, company
name, website, product group key — any subset), the account key a competent RevOps person would say it
belongs to, `None` if the right answer is "no account", and a one-sentence written justification of that
label. The justification is stored with the case, not in a commit message: if a label is wrong, the
argument to attack is right there in `why`.

**Split.** Every case is assigned to `dev` or `test` by `blake2b(case_id) % 100 < 50`. A hash of the case
id, not `random.shuffle`, for one reason: a shuffle can be re-rolled until the numbers improve, and nobody
reading the result can tell whether it was. The assignment is a property of the case, identical on every
machine, and adding a case cannot move an existing one across the line. Result: **103 dev / 116 test**.

|  | cases | positive (an account is correct) | negative (`None` is correct) |
| --- | ---: | ---: | ---: |
| Development | 103 | 78 | 25 |
| **Held-out** | **116** | **81** | **35** |
| Total | 219 | 159 | 60 |

**Metrics.** A match to the wrong account counts twice — once as a false positive, once as a false
negative — because it has two victims: an account that acquired a lead that is not theirs, and an account
that never heard about its own lead. Precision is `tp / (tp + fp)`, recall is `tp / (tp + fn)`, and both
carry 95% Wilson intervals from `domain/experiments.py`. F1 has no closed-form binomial interval (it is a
ratio of two proportions sharing a numerator), so its interval is a 2,000-draw percentile bootstrap over
cases, with a fixed seed so it is reproducible rather than drifting per run.

**Tuning rule, fixed before the curve was drawn.** Maximise **F0.5** — precision weighted twice as heavily
as recall — and break ties toward the higher threshold. The asymmetry is the whole argument of section 6.

## 3. What is in the dataset, and what is deliberately not

The 219 cases are grouped into 29 families, each a distinct way a lead arrives or a matcher fails:

| family | n | dev | test | family | n | dev | test |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| exact_domain | 30 | 15 | 15 | brand_label_only | 6 | 1 | 5 |
| exact_name_freemail | 14 | 8 | 6 | cctld_brand | 6 | 1 | 5 |
| legal_suffix | 14 | 6 | 8 | subsidiary | 6 | 1 | 5 |
| near_miss_name | 14 | 9 | 5 | bare_brand | 6 | 2 | 4 |
| name_typo | 11 | 7 | 4 | group_key | 6 | 5 | 1 |
| unknown_company | 10 | 5 | 5 | freemail_only | 6 | 3 | 3 |
| near_duplicate_exact | 10 | 6 | 4 | role_address | 5 | 1 | 4 |
| subdomain | 8 | 2 | 6 | typo_domain_only | 5 | 3 | 2 |
| website_field | 8 | 3 | 5 | typo_domain_with_name | 5 | 3 | 2 |
| alias_name | 8 | 3 | 5 | genuinely_ambiguous_name | 4 | 1 | 3 |
| cjk_name | 7 | 5 | 2 | shared_corporate_domain | 4 | 0 | 4 |
| name_noise | 7 | 3 | 4 | malformed_email | 4 | 2 | 2 |
| | | | | *(5 more families of 3)* | 15 | 8 | 7 |

Legal forms span Inc, Ltd, LLC, GmbH, AB, ApS, Oyj, B.V., S.A., S.p.A., Pty Ltd, Pvt Ltd, Ltda, LLP,
株式会社, 주식회사 and 有限公司. Domains span `.co.uk`, `.com.au`, `.co.nz`, `.co.in`, `.com.br`, country
mirrors of the same brand, regional subdomains, typo'd domains and nineteen free-mail providers. The CRM
itself carries the collisions a real one accumulates: two accounts on one corporate domain, two accounts
with the same name, three brand labels claimed by two accounts each, and two pairs of near-duplicate names
(Acme Data / Acme Analytics, Kestrel Analytics / Kestrel Labs).

**The mix is adversarial and does not resemble production traffic.** In real inbound, the large majority of
leads arrive on a work email that matches an account domain exactly, and that family would dominate any
honest sample. Here it is 30 of 219. The numbers below are therefore a **floor measured on hard cases**,
not an estimate of the rate at which this matcher would be right on a real inbound stream. Weighting the
families by observed traffic would raise every figure and mean less.

## 4. Tuning, on the development split only

Threshold vs precision/recall on the 103 development cases. The held-out cases were not scored while this
table was produced.

| threshold | precision | recall | F1 | **F0.5** | tp | fp | fn |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.70 – 0.73 | 0.949 | 0.962 | 0.955 | 0.952 | 75 | 4 | 3 |
| 0.74 – 0.75 | 0.974 | 0.962 | 0.968 | 0.972 | 75 | 2 | 3 |
| 0.76 – 0.84 | 0.987 | 0.962 | 0.974 | 0.982 | 75 | 1 | 3 |
| **0.85 – 0.87** | **1.000** | **0.949** | **0.974** | **0.989** | 74 | 0 | 4 |
| 0.88 – 0.94 | 1.000 | 0.936 | 0.967 | 0.986 | 73 | 0 | 5 |
| 0.95 – 0.96 | 1.000 | 0.910 | 0.953 | 0.981 | 71 | 0 | 7 |
| 0.97 | 1.000 | 0.885 | 0.939 | 0.975 | 69 | 0 | 9 |
| 0.98 | 1.000 | 0.833 | 0.909 | 0.962 | 65 | 0 | 13 |

Three things this curve says that an asserted threshold cannot.

- **Loosening the bar buys errors, not matches.** Every step down from 0.85 to 0.70 costs false positives
  and returns exactly one extra true match. The fuzzy tier is not leaving recall on the table; below the
  bar there is nothing there but near-duplicates.
- **The choice is a plateau, not a point.** 0.85, 0.86 and 0.87 make *identical* decisions on all 103
  development cases. The data localises the threshold to an interval and no further, and the selection
  rule's upward tie-break — take the value that guesses least — is what picked one.
- **The old value was defensible.** Re-derived honestly, the threshold moved **0.86 → 0.87**, which on this
  evidence is no change at all. The problem with the old number was never that it was wrong. It was that
  it was unfalsifiable.

## 5. Held-out results

Scored once, at the shipped threshold of 0.87, on the 116 cases tuning never saw.

| metric | value | 95% interval | sample |
| --- | ---: | :---: | --- |
| **Precision** | **0.962** | **0.894 – 0.987** | 76 correct of **79 matches attempted** |
| **Recall** | **0.938** | **0.864 – 0.973** | 76 found of **81 leads with a correct account** |
| **F1** | **0.950** | **0.914 – 0.982** | bootstrap over **116 cases** |

Confusion matrix on the held-out split: 76 true matches, 3 false positives, 5 false negatives, 32 correct
abstentions. For comparison, on the development split the same threshold gives precision 1.000
(0.951 – 1.000, 74 matches) and recall 0.949 (0.875 – 0.980, 78 leads) — dev is the easier half, which is
exactly what you would expect from the half that chose the threshold, and exactly why it is not reported
as the result.

**Read the intervals, not the point estimates.** 116 cases buy a window about nine points wide on precision
and eleven on recall. This evaluation is consistent with a matcher whose true precision on this kind of
case is 0.90, and it cannot distinguish that matcher from one at 0.98. Anyone quoting "96% precision" from
this document is quoting the middle of a range they have not read.

The old in-sample pair was 0.960 / 0.923 and the new held-out pair is 0.962 / 0.938, so the optimism bias
appears to have been small. That comparison is not clean — different cases, different mix, different size
— and it should not be read as evidence that in-sample reporting was harmless. It is evidence that this
particular threshold was not heavily overfitted, which is luck about a one-parameter model, not method.

## 6. Error taxonomy

All eight held-out failures, classified. The column that matters is the last one.

| # | kind | case | what happened | acceptable? |
| --- | --- | --- | --- | --- |
| 1 | FP — brand label | `p@orion.de`, no company name | Matched Orion Manufacturing because one account claims the `orion` label. It is Orion Pharma. | **Flagged for review, so yes** |
| 2 | FP — brand label | `p@terraverde.co.uk` | Matched TerraVerde Analytics on the same reasoning. | **Flagged for review, so yes** |
| 3 | FP — legal-form collision | company name `QuantStack` | "QuantStack GmbH" normalizes to exactly `quantstack`, so a bare parent brand became an *exact* name match to a subsidiary. Applied without review. | **No — this is the one real defect** |
| 4 | FN — typo'd domain | `p@kestrel-analytcs.example` | Domains are never fuzzy-matched. One character separates two competitors. | **Yes, by design** |
| 5 | FN — typo'd domain | `p@terra-vrde.example` | Same. | **Yes, by design** |
| 6 | FN — punctuated legal form | `Aurora Labs BV` vs CRM's `Aurora Labs B.V.` | The suffix stripper is word-boundary based, so it removes `BV` but not `B.V.`, leaving `aurora labs` against `aurora labs b v` at 0.846 — just under the bar. | **No, but cheap to fix** |
| 7 | FN — punctuated legal form | `Molinari Impianti SpA` vs `S.p.A.` | Same defect, 0.850. | **No, but cheap to fix** |
| 8 | FN — holding suffix | `Northwind Logistics Group` | "Group" is deliberately never stripped, because a group is often a separate legal entity. Scores 0.864, just under. | **Arguable; the label is the weak part** |

Zero cases were attached to the *wrong real account*. Every false positive is a match that should have
been an abstention, not a swap between two live accounts — the failure mode that actually corrupts a CRM
did not occur on this data.

**The asymmetry.** In lead-to-account matching the two errors are not equally expensive. A false positive
attaches a lead to the wrong company: the wrong rep is notified, the wrong account's activity history is
polluted, the named owner of the real account never hears about their own inbound, and nothing raises — a
wrong match looks exactly like a right one from the outside. A false negative produces an unmatched lead
in a queue a human already reads. One is a silent error that costs a deal; the other is visible work. This
is why the threshold is tuned on F0.5 and why the waterfall abstains on every tie rather than picking.

**The mitigation the headline number hides.** Two of the three false positives set `review_required`,
because the brand-label tier flags every match it makes. Splitting the held-out matches by whether the
system would apply them unsupervised:

| | matches | correct | precision | 95% interval |
| --- | ---: | ---: | ---: | :---: |
| Applied without review | 65 | 64 | **0.985** | 0.918 – 0.997 |
| Held for human review | 14 | 12 | 0.857 | — |

The rate at which this matcher *silently* attaches a lead to the wrong company on held-out hard cases is
1 in 65, and that one is failure #3. That is the operationally meaningful figure, and it is still an
interval nine points wide.

**What I did not do.** Failures 6 and 7 are a two-line fix to `normalize_company_name` — collapse dotted
acronyms before stripping legal forms. Both cases landed in the held-out split; no development case
exercises punctuated legal forms at all. Fixing the normalizer *after* seeing them would convert the
held-out set into a second tuning set and this document back into the thing it replaced. The fix belongs
in the next change, measured against cases drawn after it. Leaving a known defect visible in a table is
cheaper than spending the only clean measurement in the repo on it.

## 7. Where the matcher's decisions came from

Method distribution over the 116 held-out cases: exact domain 28, company name 31, no match 28, brand
label 9, ambiguous (explicit abstention) 9, registrable domain 6, fuzzy name 5.

Note the last two numbers. **The fuzzy tier — the thing this whole document tunes — fires five times in
116 cases.** The threshold is worth getting right because its errors are expensive, not because it does
much work. Most of the matcher's accuracy comes from domain normalisation and exact name matching after
legal-form stripping, which are deterministic and were never in question. An interviewer should discount
the tuning accordingly; the interesting engineering is the waterfall's ordering and its willingness to
abstain, not the 0.87.

## 8. What this does and does not establish

**It establishes:**

- The matcher's behaviour on 116 deliberately hard cases it was not tuned against, with intervals.
- That the fuzzy threshold was chosen by a rule stated in advance, on data separated in advance, and that
  the rule's output is visible as a curve rather than asserted as a constant.
- That the matcher prefers abstaining to guessing: 32 of 35 held-out cases whose correct answer was "no
  account" got no account, and no lead was attached to a different live account.
- That the failure modes are known, named, and asserted case-by-case in a test, so a new one cannot appear
  without a red build.

**It does not establish:**

- **Anything about real data.** Every account, lead and label here is invented. A real CRM contains
  duplicate accounts nobody has merged, accounts whose "domain" is a parent company's, resellers, agencies
  filling in forms on behalf of clients, and personal domains that really are companies. None of that is
  in this set because I cannot label it honestly without seeing it.
- **Anything about production accuracy.** The family mix is adversarial by construction (section 3), so
  these numbers under-state performance on typical traffic by an unknown amount.
- **That the labels are right.** They encode one author's judgment about what should match. The
  `subsidiary` family is openly contestable — I labelled a country arm on the parent's own brand domain as
  the parent, and a differently-named subsidiary on its own domain as no match, and a different revenue
  team would draw that line elsewhere. `group_suffix` (failure #8) is the same problem, and `bare_brand`
  (failure #3) is arguably a labelling disagreement rather than a matcher defect: the CRM really does
  contain an account whose registered name minus its legal form is exactly "QuantStack". I counted it
  against the matcher because relabelling a case after seeing it fail is how in-sample reporting gets
  reinvented.
- **A difference between 0.87 and 0.85.** Nothing in this data distinguishes them.
- **Statistical significance of anything.** There is one arm and no comparison. The intervals describe
  sampling uncertainty on one estimate, not a test against an alternative.

**What would make it real**, in order of value per hour: label 500–1,000 rows of genuine inbound against a
genuine CRM, where the mix is observed rather than chosen; have a second person label an overlapping
sample and report inter-annotator agreement, which would put a number on how much of the remaining error
is disagreement rather than defect; then re-split and re-tune. Until that happens the honest summary is
one sentence: *on 116 hard synthetic cases it had not seen, the matcher attached 96% of its matches to the
right account (0.89–0.99) and found 94% of the matches available (0.86–0.97), and it flags the tier
responsible for most of its mistakes.*
