# Application positioning

Answers I can actually say out loud in a screening call, in the order they usually get asked.
Everything here is checkable against the repository.

---

## Why did I build GTMOS?

Because I kept reading GTM Engineer job descriptions and could not tell what the job was. Every one
of them listed the same four or five tools and then a sentence about "owning the go-to-market
systems", and I had no way to know whether that meant wiring webhooks or making decisions about
revenue. I do not have a revenue-operations career behind me, so I could not answer it from memory,
and I did not want to turn up to an interview with opinions I had read rather than tested.

The fastest way I know to understand a domain is to build the thing and find out where it hurts. So
I built the system a GTM team would actually run — signals in, a score, an owner, a workflow, the
CRM, and then the analytics that are supposed to say whether it worked. I expected the hard part to
be the integrations. It was not. The hard part was everything that had to have an opinion.

## What problem was I trying to understand?

The gap between four tools that are each good at their job and nobody owning what connects them.
Product analytics knows what users did. Enrichment knows who the company is. The CRM is where reps
work. An orchestrator moves bytes. None of them has a view on what a signal *means*, what an account
is worth, who should work it, or what may be said to them. In practice that gap is filled by a
spreadsheet, a CRM workflow nobody can test, and a scoring formula whose author has left the company.

What I wanted to understand was whether that layer is real engineering or just glue with a nicer
name. My conclusion is that it is real, and that the substance of it is not the pipeline — the
pipeline is a week — it is the policy. What happens when two enrichment providers disagree. Whether
a field a rep edited is yours to overwrite. Whether you are allowed to ship the message that won.
Those are decisions, they need to be explainable and diffable, and that is why they belong in code.

## Why GTM Engineering?

Two reasons, one honest and slightly selfish. The first: the feedback loop is short and the stakes
are legible. A scoring change lands and someone works a different list tomorrow; you find out
whether you were right. I have worked on systems where the consequence of a decision arrived two
quarters later filtered through six teams, and I did not enjoy it.

The second: the failure modes are the ones I find interesting. Duplicate delivery, conflicting
sources of truth, a sync loop, an audit trail that cannot attribute anything, a number that gets
quoted in a board deck three months after everyone forgot how it was computed. That is distributed
systems and data quality wearing a commercial hat.

I will say the obvious thing too: I have not carried a number, and I have never had to explain to a
rep why their list is wrong. That is the part of this job I would be learning on the way in.

## How does my SWE/data/AI background translate?

Directly in three places and awkwardly in one. Idempotency, transactional boundaries and the
distinction between the store of truth and the delivery mechanism — that is ordinary backend work,
and it is most of what makes a GTM system trustworthy. Postgres is the truth in GTMOS; Redis is
delivery; runs are rows first and enqueued after commit, with a sweeper for anything stuck. Nothing
about that is GTM-specific and all of it is why the system does not double-act on an account.

The data side shows up in refusing to quote a rate without an interval, and in knowing the
difference between a heuristic and a model. The AI side shows up mostly as restraint: generation
writes prose over an evidence pack the system already holds, citations are validated, and a model
never becomes a source of CRM truth.

The awkward part is domain instinct. I can tell you what a stage transition is; I cannot yet tell
you which ones a sales team fakes.

## Why not just use Clay?

I would use Clay. What Clay sells is the provider network — dozens of data vendors behind one row,
try them in order, pay only for the one that answers. You can write the waterfall mechanics in an
afternoon; you cannot negotiate forty data contracts in one. GTMOS implements a waterfall over three
simulated providers purely to prove I understand the mechanics, and in production those providers
would be deleted and Clay would be one input.

What Clay does not do is the part I kept: the merge policy. Clay will tell you provider B says
headcount is 900 while your record says 400. It will not tell you which to believe, and neither will
HubSpot, n8n or PostHog — I checked all four, and it is four "no". GTMOS refuses to overwrite a
manual lock at any confidence, refuses to resolve a material disagreement on confidence alone, and
raises a data-quality issue for a human instead. That is a small piece of code and it is where the
business logic actually lives.

## Why not just use HubSpot?

Same answer in a different direction: reps live in the CRM and rebuilding pipeline, tasks, sequences
and permissions is how you end up owning a CRM and losing. GTMOS never becomes where anyone works.

What it does not hand over is the judgement layer, for two reasons. The practical one is tiering —
scoring, workflows, routing rotation and most attribution sit behind Professional or Enterprise, and
score explanations and audit logs behind more again. The real one is that a CRM workflow is not
diffable, not unit-testable and not versioned, so a scoring change nobody can review is exactly the
artefact I was trying to replace.

So the write boundary is narrow and enforced rather than documented: update payloads contain
`gtmos_*` fields and nothing else, so a sync cannot overwrite a rep's edit, and inbound CRM changes
are logged and never applied, which breaks the sync loop deliberately instead of by luck.

## What did I learn?

The thing I did not expect: vendor reality is not in feature lists, and three separate load-bearing
facts contradicted the obvious assumption. HubSpot does not deduplicate API-created companies on
`domain`, so the upsert key has to be a custom unique property. Private apps sign webhooks with v1,
not v3, which means the most likely test environment would have failed every delivery and looked
like a broken integration rather than a wrong verifier. Association type ids 1 and 5 are the
*primary* variants; write only the general 279/341 and records look associated in the UI and behave
as orphans in a report.

The general lesson underneath those is the one I actually took: the interesting risk in this kind of
work is not the code you write, it is the assumption you inherited. Every one of those three would
have been found on day one against a real portal and cost a day to fix. Reading the documentation
properly is not glamorous and it is the whole job some weeks.

## What was hardest?

Honestly, deciding what the system was not allowed to claim. The code was the easy half.

The concrete version: the scoring evaluation. It is easy to write a backtest, and it is easy to
write one that flatters you. Separating the score into a structural part known before first contact
and the part contaminated by engagement, working out that the contacted-only population biases the
AUC down through range restriction while the all-accounts population biases it up through targeting
feedback, and then having to write that neither number is a causal claim and the only honest design
is a randomised holdout I cannot run because the system sends nothing — that took longer than the
engine it was measuring.

The second-hardest was accepting that a measurement can be correct and still not support the
sentence you wanted to write. The grade ladder is ordered correctly, and grade A has six accounts
with an interval from 9.7% to 70%, so it means almost nothing.

## What failed?

Several things, and the useful ones failed in ways I could not argue with.

The scoring model does not work. Structural AUC 0.537, interval 0.485–0.589 — not distinguishable
from a coin flip on this data. The flattering 0.593 variant is contaminated by construction, because
engagement points are awarded for the replies and meetings that are the outcome.

Worse, and I volunteer this one: when disqualifying signals were added the backtest got *worse*, and
I fixed the simulation rather than the score. Defensible — those signals were noise with no effect
on simulated outcomes — but I changed the world the thing was measured against, which is the classic
way to make a model look good. It is disclosed and the function is named.

Then a prompt-injection hole my own new integration opened: an account `industry` set to a sentence
containing an instruction produced a research brief repeating it, with a citation. An earlier
sanitiser had assumed firmographics were facts I owned.

Also: three of four integrations never reached a real vendor, and a draft's cited evidence is never
re-checked at approval, so a retracted signal leaves a message citing something that no longer
resolves. Found by accident, still open.

## What would I change with real company data?

Three things, in order.

First, connect HubSpot to an actual portal. Everything is built and documented and it needs twenty
minutes and a login; I am confident it would surface something the mocks did not, because the last
three times I checked an assumption against real documentation, the assumption lost.

Second, get outcome labels and run a randomised holdout — contact a small random sample regardless
of score and compare conversion across bands. Without it the score is graded on the list it selected
and no amount of better arithmetic fixes that. I would also build features as of the decision time
rather than as of today, which is the single hardest piece and the usual reason a model looks
excellent offline and dies live.

Third, I would expect the scoring weights to be wrong in a specific, learnable way, and I would want
the argument with a sales leader about which ones. That conversation is the input I cannot simulate,
and it is the main thing a synthetic dataset cannot give you.
