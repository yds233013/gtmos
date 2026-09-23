# Final résumé entry

Everything below is verifiable in this repository. No business outcome is claimed anywhere, because
the system has no customers, no production traffic and no real data.

---

## The entry

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

---

## One-line project description

> Built GTMOS, an AI-native GTM control plane — product signals to enrichment to explainable
> scoring to routing to idempotent workflows to CRM reverse ETL — with an evaluation layer
> honest enough to report that its own scoring model is not yet distinguishable from chance.

---

## GitHub repository description

> An AI-native GTM control plane: product signal → enrichment → explainable scoring → routing →
> idempotent workflow → CRM reverse ETL → analytics. FastAPI, Postgres, Next.js, dbt, n8n. One of
> four integrations is verified by execution, the honest scoring AUC is 0.537, and the repo leads
> with both. Synthetic data only; it has never sent a message.

(346 characters.)

---

## LinkedIn project description

> GTMOS is a GTM control plane I built to understand where revenue systems actually break. It
> connects product signals, enrichment, CRM state and custom decision logic, then decides which
> accounts deserve attention, who owns them, and what may be said to them — with the deterministic
> parts (scoring, routing, workflow conditions, experiment statistics) as pure functions under test
> and generation confined to prose over an evidence pack the system already holds.
>
> The part I would point at first is the evaluation. The scoring model's leakage-free AUC is 0.537
> on synthetic data, with an interval that includes 0.5, and the repository says so before it says
> anything flattering. One of four integrations is verified by execution; the other three carry a
> badge saying the real service has never been reached. 504 automated tests, 19 dbt models, 40
> tables, 2,006 synthetic accounts. It has never sent an email to anyone.

---

## If an interviewer asks why there are only two bullets

Say it straight: the project has around twenty things in it that would each make a passable bullet,
and a list of twenty passable bullets says the author could not tell which two mattered. The two
that made it are the ones I would defend under pressure — a correctness property proved by a test
designed to fail the plausible wrong implementation, and a measurement that returned a bad answer
which I published rather than reframed. Everything else — the enrichment merge policy, the routing
SLAs, the kill switches, the warehouse, the prompt-injection fix — is a better conversation than a
line, and I would rather be asked about them than have skimmed past them. Then offer one: "the
third bullet, if you want it, is the prompt-injection hole that my own new integration opened."
