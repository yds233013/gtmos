# Connecting GTMOS to a real HubSpot

Everything in the HubSpot adapter is implemented and unit-tested against `httpx.MockTransport`, but
**it has never run against a real portal** — no HubSpot account existed while it was built, and none was
created, because that needs a human to sign in. This document is the exact path from here to a working
live connection.

Nothing below costs money. It takes about twenty minutes.

> **Safety.** Do not point this at a production CRM you care about. Use a developer test account. GTMOS
> will not write anything until you set `HUBSPOT_LIVE_WRITES_ENABLED=true`, and even then it only writes
> its own `gtmos_*` properties plus name and domain on record creation.

---

## 1. Choose an environment

| Option | Cost | Good for | Caveats |
|---|---|---|---|
| **Developer test account** ← recommended | Free, 10 per standard account | Exactly this | Expires after 90 days with no API calls; cannot sync data with other accounts |
| Free standard account | Free | A real-ish portal | It is your actual CRM data; free-tier record caps are not published |
| Standard sandbox | **Enterprise only** | Mirroring production | Not available without an Enterprise subscription |

Create a test account from your standard HubSpot account: **Settings → Integrations → Developer test
accounts → Create test account**. A developer test account includes a 90-day trial of many Enterprise
features, which is more than enough.

> **Unverified:** HubSpot's docs do not state either way whether private-app **webhooks** are available
> in a developer test account. Private apps themselves are. If webhooks turn out to be unavailable
> there, use a free standard account for the inbound half and keep writes pointed at the test account.

## 2. Create a private app

In the target account: **Settings → Integrations → Private apps → Create a private app**.

Grant these scopes:

| Scope | Why |
|---|---|
| `crm.objects.companies.read` / `.write` | Account ↔ Company sync |
| `crm.objects.contacts.read` / `.write` | Contact sync |
| `crm.objects.deals.read` / `.write` | Opportunity ↔ Deal sync |
| `crm.schemas.companies.write` | Create the `gtmos_*` custom properties |
| `crm.schemas.contacts.write` | Same, on contacts |
| `crm.schemas.deals.write` | Same, on deals |
| `crm.objects.companies.sensitive.read` | Only if your portal marks any synced field sensitive |

Copy two values from the app:

- the **access token** (Auth tab) → `HUBSPOT_ACCESS_TOKEN`
- the **client secret** (Auth tab) → `HUBSPOT_WEBHOOK_CLIENT_SECRET`

Put them in `.env` at the repo root, which is git-ignored:

```bash
HUBSPOT_ACCESS_TOKEN=pat-na1-…
HUBSPOT_WEBHOOK_CLIENT_SECRET=…
HUBSPOT_LIVE_WRITES_ENABLED=false   # leave false until step 5
```

Restart the API so the settings are read.

## 3. Create the custom properties

GTMOS creates these itself, but do it explicitly the first time so you can see the result:

```bash
cd apps/api
uv run python -c "
from gtmos.config import get_settings
from gtmos.integrations.hubspot import RealHubSpotAdapter
s = get_settings()
print(RealHubSpotAdapter(s.hubspot_access_token.get_secret_value()).ensure_properties())
"
```

This creates, on **companies**:

| Property | Type | Notes |
|---|---|---|
| `gtmos_account_id` | string | **Must have "unique values" enabled.** This is the upsert key. |
| `gtmos_icp_score` | number | |
| `gtmos_score_grade` | string | |
| `gtmos_intent_score` | number | |
| `gtmos_account_tier` | string | |
| `gtmos_last_signal` | string | |
| `gtmos_next_best_action` | string | |
| `gtmos_last_scored_at` | datetime | |

Plus `gtmos_contact_id` and `gtmos_buying_role` on contacts, and `gtmos_opportunity_id` on deals.

**Verify `gtmos_account_id` is unique** in the HubSpot UI (Settings → Properties → the property → it
should say unique values). Three things make this the single most important step:

1. **`domain` is not unique in HubSpot.** The docs are explicit that companies created through the API
   are not deduplicated on domain. Upserting on it creates duplicates.
2. A HubSpot object supports **at most 10 unique properties**.
3. **The constraint cannot be added retroactively** — if you create the property without it and start
   writing, you have to start over with a new property name.

## 4. Dry run, still not writing

```bash
curl -s localhost:8010/api/v1/integrations/hubspot/reverse-etl/preview?limit=10 | jq
```

This shows exactly which records would be pushed and which fields would change, computed from the
payload hash, without calling HubSpot at all.

## 5. Enable writes, smallest possible scope

```bash
HUBSPOT_LIVE_WRITES_ENABLED=true   # in .env, then restart the API
```

Then sync **one account** rather than the whole list:

```bash
curl -s -X POST localhost:8010/api/v1/accounts/<account-id>/route   # optional: pick an owner first
curl -s -X POST localhost:8010/api/v1/integrations/hubspot/reverse-etl/run \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" | jq
```

Check in HubSpot that the company exists, the `gtmos_*` properties are populated, and **no other field
was touched**.

Then the contacts and deals, which also create associations:

```bash
curl -s -X POST localhost:8010/api/v1/integrations/hubspot/reverse-etl/contacts-deals \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" | jq
```

Verify in HubSpot that contacts are associated to their company and deals to theirs. GTMOS writes the
**primary** association types (1 for contact→company, 5 for deal→company), not the general ones
(279, 341) — so the contact's "primary company" field should be set, which is what territory and
reporting key off.

## 6. Inbound webhooks

In the private app: **Webhooks → Create subscription**. Subscribe to `company.propertyChange` for the
properties you care about (start with `name`, `domain`, `lifecyclestage`).

The target URL must be publicly reachable. For local development:

```bash
# any tunnel works; this is not an endorsement and costs nothing on the free tier
ngrok http 8010
# then set the webhook target to https://<your-subdomain>.ngrok-free.app/api/v1/webhooks/hubspot
```

### What GTMOS expects

- A **JSON array** of event objects, not a single object. GTMOS keys deduplication on the sorted set of
  member `eventId` values precisely because of this, and because `attemptNumber` increments on every
  retry — an idempotency key derived from the raw body would treat each retry as a new event. (This was
  a real bug, fixed in Phase 3.)
- Signature verification: GTMOS prefers `X-HubSpot-Signature-v3` (HMAC, with a 5-minute replay window)
  and falls back to `X-HubSpot-Signature` **v1** (a plain SHA-256 of `clientSecret + body`, hex, with no
  timestamp). **Private apps are documented to use v1**, so the fallback is the path you will actually
  exercise. The Operations page shows which scheme verified each delivery, because v1 has no replay
  protection and that is worth seeing.

### Verify

```bash
# change a company name in the HubSpot UI, then:
curl -s "localhost:8010/api/v1/webhooks/events?source=hubspot&limit=5" | jq '.items[] | {status, signature_status, idempotency_key}'
```

You should see `signature_status: "valid (v1; no replay window — deduped on event id instead)"`.

Then **change it again and watch HubSpot retry**, or replay the same delivery: the second should record
`duplicate: true` rather than creating a second event.

## 7. What to expect to go wrong

Ranked by how often it actually happens:

1. **Signature mismatch.** Almost always because the body was re-serialised before hashing. GTMOS hashes
   the raw bytes FastAPI gives it. If you proxy through something that reformats JSON, it will break.
2. **429s.** Private apps are rate limited per 10 seconds and per day. GTMOS retries 429 and 5xx with
   exponential backoff, bounded at 3 rounds. Note that HubSpot does **not** document a `Retry-After`
   header on CRM 429s, so the backoff is GTMOS's own.
3. **A property that will not create.** Usually a missing schema scope, or a name colliding with an
   existing property.
4. **The record id you get back is not the one you sent.** Merged records resolve to the surviving
   record, so the response id can differ. GTMOS stores what HubSpot returns.
5. **Datetime rejections** on date-typed properties, which expect midnight UTC.

## What is still not implemented

Being explicit, because a setup guide that implies completeness is worse than none:

- **No reconciliation job.** GTMOS compares the payload hash against *what it last sent*, not against
  what HubSpot currently holds. If someone edits a `gtmos_*` field in the CRM, GTMOS will not notice
  until the computed value changes. `external_records.remote_updated_at` exists in the schema but is
  never read or written.
- **No conditional writes.** There is no optimistic-concurrency check against the remote record's
  `updatedAt`, so a rep editing mid-sync can be overwritten within the fields GTMOS owns.
- **Inbound changes are never applied**, only logged. Applying them needs a manual field-edit path that
  writes `field_provenance`, and no endpoint does that yet.
- **One webhook delivery is stored as one row**, not fanned out per event in the array. Correct for the
  current no-op handler, wrong once a handler does per-event work.
- **Deleted and merged records** are not specially handled.

All of these are listed again in `docs/crm-sync-design.md` with the design for fixing them.
