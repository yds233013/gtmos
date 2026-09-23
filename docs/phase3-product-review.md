# Phase 3 product review

Done the way a product review is actually useful: by driving the running application in a real
browser, as a GTM buyer would, rather than by reading the code that renders it. Every finding below
came from looking at a page, not from grepping for a pattern.

The review covered the command center, the integrations index and its per-provider drilldown, the
approval queue, operations, and the account detail. Console was clean on every page — no errors, no
React warnings, no failed requests.

---

## What holds up

**The integrations page is the strongest new surface.** It resists the thing every integrations page
does wrong. There is no "Connected" state anywhere, because the four boundaries are connected to four
genuinely different degrees, and one green badge would have flattened that into a lie. Instead there
are two independent axes — *mode* (what the running configuration does) and *verification* (how much
of it has ever actually happened) — with a legend that explains them before the cards, and an
explicit **Real service never reached** badge on the three that have not. The phrasing "1 of 4" for
real services reached is the single most honest number in the product.

**The drilldown earns its click.** `/integrations/n8n` shows an error rate of 21.7% next to a
`Degraded` pill and then lists the individual deliveries with signature status, attempt count,
processing time and a correlation id per row. That is the shape of a page an on-call engineer would
actually open, and the correlation id is what makes it more than decoration.

**Operations labels its own synthetic history.** Every seeded run in the dead-letter table carries a
`HISTORY (synthetic)` badge. A portfolio project that quietly presents generated history as
production history is a project whose numbers you cannot trust; tagging the rows costs a column and
buys the whole page credibility.

**The approval detail shows its work.** The Kestrel call-prep draft lists the evidence it drew on by
id — the product-qualified account, the pricing views, the integration connection, the funding round
— above a Decision panel that states approval is blocked while a guardrail fails. The banner at the
top of the queue says plainly that GTMOS never sends messages and that marking a draft Ready hands it
to a human. Nothing here implies an autonomous sender.

## Findings, and what was done about them

### 1 · A green health pill sitting on a red failure strip · Fixed

On the integrations index, HubSpot showed `Healthy` in green and, three inches below, a red
`Last failure 8d ago: 503 Service Unavailable (simulated)`. Both were correct — health is computed
over the 7-day window and that failure fell outside it — but nothing on the card said so, and at a
glance the card contradicted itself. A reader resolves that contradiction by distrusting the green.

The failure strip now checks the failure's age against the window: inside it, the strip stays red;
outside it, the strip renders in muted tone and says *"older than the 7-day window, so it does not
affect health."* The fix is in `apps/web/src/components/integrations/integration-card.tsx`.

### 2 · Six truncated stat descriptions · Fixed

The stat row runs six columns wide, which left every description trailing off mid-word:
"Anything else has never tal…", "Contract exercised, no acco…", "HubSpot · n8n · PostHog · C…". A
truncated label is worse than a short one, because the reader cannot tell whether the hidden half
changes the meaning. The descriptions were rewritten short enough to survive the measure, with the
full sentence moved to the cell's `hint` so nothing was lost.

### 3 · The approval queue does not group by person · Open, deliberate

The queue showed four pending drafts for the same contact — Elena Park, VP of AI at Kestrel
Analytics — two of them identically titled `CALL PREP`. Each one is individually correct: separate
workflow runs produced them, and the golden flow has been run repeatedly against the same seeded
account. But a rep opening this queue sees the same name four times and starts skimming, which is
exactly the failure mode the approval queue exists to prevent.

The right fix is to collapse drafts by contact with the newest expanded and the rest behind a count,
and to suppress a new draft of the same type for the same contact inside a cooling-off window — the
same reasoning that makes the PQL fire once per account per week (`domain/pql.py`). It is not built,
because it is a queue-design change rather than a bug, and building it late in a phase without a
test for the suppression window would be the wrong trade. Recorded here rather than quietly left.

### 4 · Doc references render as paths, not links · Open, accepted

Cards cite `docs/research/hubspot.md` in monospace rather than as a hyperlink. There is no repository
URL configured anywhere in the project and inventing one would be worse than the plain path, which is
at least copy-pasteable into an editor. It becomes a one-line change the moment the repo has a
canonical home.

## What was checked and found nothing

- **Console.** No errors, warnings or failed network requests on any page visited.
- **The demo banner is on every page.** `DEMO · Synthetic demo data · CRM simulated · AI deterministic
  demo mode · No external messages are ever sent` is part of the shell, not per-page decoration, so
  there is no route where the boundary could be missed.
- **No fabricated liveness.** Nothing observed claims a connection, a send, or a vendor call that has
  not happened. The one place the product says "Live" is n8n, which genuinely runs.
- **Mobile.** Checked separately at 412x915 with no horizontal overflow and a single `h1` per page.
