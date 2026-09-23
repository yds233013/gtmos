# HubSpot API reference for GTM engineering

Researched 2026-09-22 against official sources only: `developers.hubspot.com`, `knowledge.hubspot.com`, and the HubSpot developer changelog. No HubSpot API was called. Every non-obvious claim carries a URL. Anything not verifiable from an official page is marked **UNCONFIRMED**.

---

## 0. Versioning context (read this first)

HubSpot moved to **date-based API versioning**. Source: <https://developers.hubspot.com/docs/developer-tooling/platform/versioning>

> "Starting from March 30th 2026, HubSpot's REST APIs follow a date-based version standard" (replacing `v1`/`v2`/`v3`/`v4`).

| Fact | Value | Source |
|---|---|---|
| API version path format | `/YYYY-MM/`, e.g. `/2026-03/`, `/2026-09/`; betas `/2026-09-beta/` | versioning page |
| Release cadence | "A new version of HubSpot's REST APIs and app developer platform is made generally available (GA) every 6 months in March and September." | versioning page |
| Support window | "18 months after a version originally went into GA, the version will be considered unsupported" | versioning page |
| Current version (as of 2026-09-22) | **2026.09** / `/2026-09/` (GA Sept 8, 2026) | versioning page; <https://developers.hubspot.com/changelog/introducing-date-based-api-versioning> |
| Supported | 2026.03, 2025.2 | versioning page |
| Legacy semantic versions | "All legacy APIs using semantic versions (e.g., v4, v3, v2, and v1) are still supported and available at their previous URLs." | versioning page |
| v4 associations sunset | "Current v4 APIs will be supported until March 2027, and will become unsupported with the release of `/2027-03/`." | <https://developers.hubspot.com/changelog/introducing-date-based-api-versioning> |

**Practical guidance:** the `/crm/v3/objects/...` and `/crm/v4/associations/...` paths still work and are the widest-compatibility choice today. The dated equivalents are `/crm/objects/2026-09/{objectTypeId}/...` and `/crm/associations/2026-09/...`. Path shapes below are given in the legacy semantic form with the dated form noted where confirmed.

One version-gated behaviour change worth flagging: starting with `/2026-09/`, "HubSpot will enforce admin-configured validation rules on all CRM API write paths" (<https://developers.hubspot.com/docs/developer-tooling/platform/versioning>, changelog). Writes that pass on `/crm/v3/` can therefore fail on `/2026-09/`.

Also note the **developer platform split**: docs are now divided into "developer platform" (new, project/`*-hsmeta.json`-based apps) and "legacy apps" (classic private apps and public apps configured in the UI). Legacy developer accounts were retired: "as of March 9, 2026, all legacy developer accounts were migrated to standard HubSpot accounts" (<https://developers.hubspot.com/docs/getting-started/account-types>).

---

## 1. CRM objects: companies, contacts, deals

### 1.1 Object type IDs

Source: <https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm>

| Object | Type ID | Object | Type ID |
|---|---|---|---|
| **Contacts** | **`0-1`** | Tasks | `0-27` |
| **Companies** | **`0-2`** | Notes | `0-46` |
| **Deals** | **`0-3`** | Meetings | `0-47` |
| Tickets | `0-5` | Calls | `0-48` |
| Products | `0-7` | Emails | `0-49` |
| Line items | `0-8` | Invoices | `0-53` |
| Quotes | `0-14` | Goals | `0-74` |
| Communications | `0-18` | Orders | `0-123` |
| Feedback submissions | `0-19` | Leads | `0-136` |
| Custom objects | `2-XXXXX` (per-account) | Carts | `0-142` |

The three headline IDs (`0-1` contacts, `0-2` companies, `0-3` deals) are confirmed. Endpoints accept either the object name (`contacts`) or the type ID (`0-1`) in the `{objectType}` path segment.

### 1.2 Endpoint base paths

| Object | Base path (v3) | Dated form |
|---|---|---|
| Contacts | `/crm/v3/objects/contacts` | `/crm/objects/2026-09/0-1` |
| Companies | `/crm/v3/objects/companies` | `/crm/objects/2026-09/0-2` |
| Deals | `/crm/v3/objects/deals` | `/crm/objects/2026-09/0-3` |

Single record: `/crm/v3/objects/{objectType}/{recordId}`. By unique property: `/crm/v3/objects/contacts/{value}?idProperty=email`. Batch: `/crm/v3/objects/{objectType}/batch/{create|read|update|upsert|archive}`.

Sources: <https://developers.hubspot.com/docs/reference/api/crm/objects/contacts>, `.../companies`, `.../deals`, <https://developers.hubspot.com/docs/guides/crm/using-object-apis>

### 1.3 Required properties on create

| Object | Required | Source |
|---|---|---|
| Contact | At least one of `email`, `firstname`, `lastname` | <https://developers.hubspot.com/docs/reference/api/crm/objects/contacts> |
| Company | At least one of `name` or `domain` (docs recommend always sending `domain`) | <https://developers.hubspot.com/docs/reference/api/crm/objects/companies> |
| Deal | "you should include the following properties in the request: `dealname`, `dealstage`, and if you have multiple pipelines, `pipeline`." | <https://developers.hubspot.com/docs/reference/api/crm/objects/deals> |

### 1.4 Commonly used properties (internal names)

Canonical machine-generated lists live at `https://developers.hubspot.com/docs/api-reference/latest/crm/objects/{contacts|companies|deals}/object-definition`. Spot-checked names:

**Contacts** — `email`, `firstname`, `lastname`, `phone`, `mobilephone`, `company` (free-text string, *not* a link to a company record), `website`, `jobtitle`, `lifecyclestage` (enumeration), `hs_lead_status` (enumeration), `hubspot_owner_id`, `createdate` (datetime), `lastmodifieddate` (datetime), `hs_object_id`.
KB: <https://knowledge.hubspot.com/properties/hubspots-default-contact-properties>

**Companies** — `name`, `domain`, `hs_additional_domains`, `industry`, `city`, `state`, `country`, `address`, `address2`, `numberofemployees` (number), `annualrevenue` (number), `description`, `about_us`, `lifecyclestage`, `hubspot_owner_id`, `createdate`, `hs_lastmodifieddate`, `hs_object_id`.
KB: <https://knowledge.hubspot.com/properties/hubspot-crm-default-company-properties>

**Deals** — `dealname` (string), `amount` (number), `dealstage` (enumeration), `pipeline` (enumeration), `closedate` (datetime), `dealtype` (enumeration), `deal_currency_code`, `hubspot_owner_id`, `createdate`, `hs_lastmodifieddate`, `hs_object_id`.
KB: <https://knowledge.hubspot.com/properties/hubspots-default-deal-properties>

> **UNCONFIRMED (minor):** the exact internal spelling of `hs_lead_status` and `lastmodifieddate` was not re-quoted verbatim from a fetched page in this pass (the object-definition page truncated). Both are long-standing and consistent with the KB labels, but verify against the object-definition endpoint before relying on them.

### 1.5 Record ID vs custom unique property

Source: <https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm>, <https://developers.hubspot.com/docs/guides/crm/using-object-apis>

- Every record has `hs_object_id` ("Record ID"), auto-generated, and it "should be treated as a string."
- Record IDs are unique **only within an object type** — a contact and a company can share the same numeric ID. Always carry the object type alongside the ID.
- > "For existing records, the Record ID is a default unique value that you can use to update the record via API, but you can also identify records using the `idProperty` parameter with a custom unique identifier property."
- Built-in alternate identifiers: contact `email`, company `domain`. Plus any custom property created with `hasUniqueValue: true`.

---

## 2. Custom properties

### 2.1 Creating a property

`POST /crm/v3/properties/{objectType}`
Sources: <https://developers.hubspot.com/docs/guides/api/crm/properties>, <https://developers.hubspot.com/docs/api-reference/crm-properties-v3/core/post-crm-v3-properties-objectType>

Required body fields: `name` (internal name), `label`, `type`, `fieldType`, `groupName`. "both `type` and `fieldType` values are required."
Optional: `description`, `options[]` (enumeration), `hasUniqueValue`, `hidden`, `formField`, `displayOrder`.

```json
{
  "groupName": "dealinformation",
  "name": "system_a_unique",
  "label": "Unique ID for System A",
  "hasUniqueValue": true,
  "type": "string",
  "fieldType": "text"
}
```

### 2.2 Valid `type` / `fieldType` combinations

Source: <https://developers.hubspot.com/docs/guides/api/crm/properties>

| `type` | Valid `fieldType` values |
|---|---|
| `string` | `text`, `textarea`, `file`, `html`, `phonenumber`, `calculation_equation` |
| `number` | `number`, `calculation_equation` |
| `date` | `date` |
| `datetime` | `date` |
| `enumeration` | `select`, `radio`, `checkbox`, `booleancheckbox`, `calculation_equation` |
| `bool` | `booleancheckbox`, `calculation_equation` |

Note the trap: **`datetime` properties also use `fieldType: "date"`** — the `fieldType` does not disambiguate date from datetime; `type` does.

Field-type-to-UI mapping: <https://knowledge.hubspot.com/properties/property-field-types-in-hubspot>. That page also notes "for certain field types, you can also edit the property's type or options after the property is created."

### 2.3 Property groups

| Operation | Endpoint |
|---|---|
| List groups | `GET /crm/v3/properties/{objectType}/groups` |
| Create group | `POST /crm/v3/properties/{objectType}/groups` — body `{ "name", "label", "displayOrder" }` |
| Update group | `PATCH /crm/v3/properties/{objectType}/groups/{groupName}` |

Source: <https://developers.hubspot.com/docs/api-reference/crm-properties-v3/groups/post-crm-v3-properties-objectType-groups> and sibling pages.

### 2.4 The "unique value" option (`hasUniqueValue`)

| Fact | Value | Source |
|---|---|---|
| Field | `hasUniqueValue: true` in the create-property body | properties guide |
| **Max per object type** | **10** — "create up to ten custom properties that require unique values" / "a maximum of 10 unique properties" | <https://knowledge.hubspot.com/records/deduplication-of-records>, <https://developers.hubspot.com/changelog/unique-properties-for-contacts> |
| **Cannot be added retroactively** | "Only net new properties can be set to contain a unique value" | <https://developers.hubspot.com/changelog/unique-properties-for-contacts> |
| Available on | contacts (added Sept 2023), companies, deals, tickets, custom objects | same changelog |
| **Not** available on | feedback submissions, marketing events, products | properties guide |
| Not supported in HubSpot forms for dedup | stated | dedup KB page |
| Cloning | a unique property's value is not copied to the clone (uniqueness is account-wide per object type) | dedup KB page |

> **UNCONFIRMED:** which `type` values other than `string`/`text` may carry `hasUniqueValue`. The docs show only the `string`/`text` example and do not enumerate a restriction list.

### 2.5 Is `domain` on companies enforced unique? **No.**

Confirmed. Source: <https://knowledge.hubspot.com/records/deduplication-of-records>

> "When a new company is added, HubSpot looks at the primary values for the Company domain name property to deduplicate companies."

but, critically:

> "companies created through API will not be deduplicated by the Company domain name property."

So domain-based deduplication is a **UI/import-time behaviour only**. Nothing stops `POST /crm/v3/objects/companies` from creating a second company with the same `domain`. Contacts by contrast: "When a new contact is added, HubSpot will look for a matching value in the Email property."

**Architectural consequence:** if you need idempotent company upserts, create a custom `hasUniqueValue` property (e.g. `gtm_company_key`) and use it as `idProperty`. Do not rely on `domain`.

Related: `hs_additional_domains` lets a company carry multiple domains (<https://knowledge.hubspot.com/records/add-multiple-domain-names-to-a-company-record>); it is not a uniqueness mechanism.

### 2.6 Internal name rules and limits

- **Immutable after creation:** "You cannot edit the property's object type or internal name." (<https://knowledge.hubspot.com/properties/create-and-edit-properties>)
- **Casing/characters:** every official CRM example uses `lowercase_with_underscores` (`favorite_food`, `system_a_unique`). An explicit rule ("must start with a letter; only lowercase a-z, 0-9, underscores") is documented for HubSpot *custom-event* properties, not restated on the CRM properties page. **UNCONFIRMED for CRM properties** — but write lowercase snake_case regardless.
- **Max internal-name length:** **UNCONFIRMED** — not stated in any fetched doc.
- **Max enumeration options:** **UNCONFIRMED** — neither the properties guide nor <https://knowledge.hubspot.com/properties/manage-enumeration-property-options> states a numeric cap.
- **Custom property count limits:** 1,000 per object type; 10,000 account-wide across all objects, via `GET /crm/v3/limits/custom-properties` (<https://developers.hubspot.com/docs/api-reference/crm-limits-tracking-v3/guide>). Caveat quoted there: "The `overallLimit` and by object `limit` values are distinct and separate, so the overall limit may not equal the sum of by object limits." Tier-specific ceilings below those hard maxima are **UNCONFIRMED**.

---

## 3. Batch APIs

### 3.1 Endpoints

| Operation | Path (v3) | Dated form |
|---|---|---|
| Create | `POST /crm/v3/objects/{objectType}/batch/create` | `POST /crm/objects/2026-09/{objectTypeId}/batch/create` |
| Read | `POST /crm/v3/objects/{objectType}/batch/read` | `.../batch/read` |
| Update | `POST /crm/v3/objects/{objectType}/batch/update` | `.../batch/update` |
| Upsert | `POST /crm/v3/objects/{objectType}/batch/upsert` | `.../batch/upsert` |
| Archive | `POST /crm/v3/objects/{objectType}/batch/archive` | `.../batch/archive` |

Source: <https://developers.hubspot.com/docs/guides/crm/using-object-apis>

### 3.2 Maximum batch size

> "Object API batch endpoints are limited to **100 inputs per request**. For example, create or retrieve up to 100 contacts per request."

Source: <https://developers.hubspot.com/docs/guides/crm/using-object-apis>. The contacts batch-upsert reference restates it: "Batch operations are limited to 100 records at a time." (<https://developers.hubspot.com/docs/api-reference/crm-contacts-v3/batch/post-crm-v3-objects-contacts-batch-upsert>)

### 3.3 `idProperty` semantics

- **Placement:** `idProperty` is a **field in the JSON request body**, not a query parameter, for the batch endpoints. For batch read it sits at the top level alongside `inputs`; for batch upsert it is set **per input**. (Confirmed on <https://developers.hubspot.com/docs/api-reference/crm-companies-v3/batch/post-crm-v3-objects-companies-batch-upsert> and the contacts upsert reference.) For **single**-record GET/PATCH it is a query parameter: `GET /crm/v3/objects/contacts/foo@bar.com?idProperty=email`.
- Batch read: "the unique identifier property used to identify records. You only need to use this parameter if retrieving by a custom unique identifier property."
- Batch upsert: "include the `idProperty` parameter to identify the unique identifier property you're using. Include that property's value as the `id`."
- Upsert semantics: "if the records already exist, they'll be updated and if the records don't exist, they'll be created."

Request shape:

```json
{
  "inputs": [
    {
      "id": "jane@example.com",
      "idProperty": "email",
      "properties": { "lifecyclestage": "lead" },
      "objectWriteTraceId": "row-0042"
    }
  ]
}
```

> **UNCONFIRMED:** behaviour when an `idProperty` value matches **zero** records in an *update* (as opposed to upsert) call, or matches **multiple** records. The docs do not state it. Since uniqueness is enforced for `hasUniqueValue` properties, a multi-match should be impossible for those; for `email`/`domain` it is not documented.

### 3.4 Partial success — **207, confirmed**

> "Responses will either be a **200** when batch updates are fully successful or a **207 Multi-Status** response when one or more of the batch operations fails."

Source: <https://developers.hubspot.com/changelog/simplifying-batch-update-response-codes-for-crm-v3-apis>. `207 Multi-Status` is also listed among common responses on <https://developers.hubspot.com/docs/api-reference/error-handling>.

So **batch upsert returns 207 (not 200) on partial failure.** Treat any non-200 2xx as "inspect the body."

**Important caveat for `batch/create`:** multi-status is **opt-in**. Per <https://developers.hubspot.com/docs/guides/crm/using-object-apis>:

> "For batch create actions, you can enable multi-status errors which tell you which records were successfully created and which were not."

Multi-status is enabled by "including a unique `objectWriteTraceId` value for each input in your request. The `objectWriteTraceId` can be any unique string that helps you identify which records succeeded or failed." Without it, a batch create with any failing row does **not** give you per-row results. **Always send `objectWriteTraceId` on batch create.**

### 3.5 Response shape

```json
{
  "status": "COMPLETE",
  "results": [ { "id": "...", "properties": { }, "createdAt": "...", "updatedAt": "...", "archived": false } ],
  "numErrors": 2,
  "errors": [
    {
      "status": "error",
      "category": "VALIDATION_ERROR",
      "message": "...",
      "context": { "objectWriteTraceId": ["row-0042"] },
      "subCategory": "..."
    }
  ],
  "requestedAt": "...",
  "startedAt": "...",
  "completedAt": "..."
}
```

- `status` enum: `PENDING`, `PROCESSING`, `CANCELED`, `COMPLETE`.
- `numErrors` = "The total number of errors that occurred during the operation."
- Timestamps are ISO 8601.
- "In the response, statuses are grouped so you can see which creates were successful and which failed."

Sources: <https://developers.hubspot.com/docs/api-reference/crm-objects-v3/batch/post-crm-v3-objects-objectType-batch-create>, <https://developers.hubspot.com/docs/api-reference/crm-companies-v3/batch/post-crm-v3-objects-companies-batch-upsert>

### 3.6 Batch limitations

- **Batch read cannot return associations.** "The batch endpoint **cannot** retrieve associations." / "this parameter is not supported in the batch read endpoint." (companies batch reference; using-object-apis)
- Batch **create** *does* accept an inline `associations` array per input.

---

## 4. Associations (v4)

Canonical guide: <https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide> (mirrors: `/docs/api-reference/crm-associations-v4/guide`, `/docs/guides/api/crm/associations/associations-v4`)

### 4.1 Endpoints

Swap `v4` → `2026-09` for the dated form.

| Purpose | Method & path |
|---|---|
| Create labeled association (single) | `PUT /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/{toObjectType}/{toObjectId}` |
| Create default/unlabeled (single) | `PUT /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/default/{toObjectType}/{toObjectId}` |
| Read associations of a record | `GET /crm/v4/objects/{fromObjectType}/{objectId}/associations/{toObjectType}` |
| Delete all associations between two records | `DELETE /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/{toObjectType}/{toObjectId}` |
| Batch create (labeled) | `POST /crm/v4/associations/{fromObjectType}/{toObjectType}/batch/create` |
| Batch create (default) | `POST /crm/v4/associations/{fromObjectType}/{toObjectType}/batch/associate/default` |
| Batch read | `POST /crm/v4/associations/{fromObjectType}/{toObjectType}/batch/read` |
| Batch archive (all) | `POST /crm/v4/associations/{fromObjectType}/{toObjectType}/batch/archive` |
| Batch archive specific labels | `POST /crm/v4/associations/{fromObjectType}/{toObjectType}/batch/labels/archive` |
| Label definitions | `GET/POST/PUT/DELETE /crm/v4/associations/{fromObjectType}/{toObjectType}/labels` |
| High-usage report | `GET /crm/associations/{version}/usage/high-usage-report/{userId}` |

Label definition reference: <https://developers.hubspot.com/docs/api-reference/crm-associations-schema-v4/definitions/put-crm-associations-v4-fromObjectType-toObjectType-labels>

### 4.2 HubSpot-defined association type IDs

Source (verified verbatim from the "Association type ID values" table): <https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide#association-type-id-values>

All of these use `associationCategory: "HUBSPOT_DEFINED"`.

| Type ID | Label (verbatim) |
|---|---|
| `1` | Contact to **primary** company |
| `279` | Contact to company |
| `2` | Company to **primary** contact |
| `280` | Company to contact |
| `931` | Billing contact to company |
| `930` | Company to billing contact |
| `4` | Contact to deal |
| `3` | Deal to contact |
| `5` | Deal to **primary** company |
| `341` | Deal to company |
| `6` | **Primary** company to deal |
| `342` | Company to deal |
| `15` | Contact to ticket |
| `16` | Ticket to contact |
| `25` | Primary company to ticket |
| `340` | Company to ticket |
| `26` | Ticket to primary company |
| `339` | Ticket to company |
| `27` | Deal to ticket |
| `28` | Ticket to deal |

> **This contradicts a very common assumption.** `1` and `2` are the **primary** company/contact types (legacy IDs that predate multi-company support); the *general, non-primary* types are `279`/`280`. Same for deals: `5`/`6` are primary, `341`/`342` are general. Using `1` when you meant "just associate them" silently sets the primary company.
>
> Contact↔Deal (`3`/`4`) has no primary variant — it is symmetric and unlabeled.

### 4.3 `associationCategory`

Enum: `HUBSPOT_DEFINED`, `USER_DEFINED`, `INTEGRATOR_DEFINED`.

- `HUBSPOT_DEFINED` — fixed system labels; cannot be edited or deleted.
- `USER_DEFINED` — custom labels created via the `/labels` endpoint.
- `INTEGRATOR_DEFINED` — appears in the enum but the guide gives no example and **UNCONFIRMED** whether it is functional.

Body shape for a labeled association (single `PUT`):

```json
[ { "associationCategory": "USER_DEFINED", "associationTypeId": 36 } ]
```

### 4.4 Primary and labels

> "If a record has more than one associated company, only one can be the primary company."

Other associations on the pair "can either be unlabeled or have custom association labels."

> **UNCONFIRMED:** the maximum number of associations per record per pair, and the maximum number of labels per pair. The guide points to a limits endpoint (<https://developers.hubspot.com/docs/api-reference/legacy/crm/associations/associations-schema/limits/create-associations-limits>) but no specific figure (e.g. the often-quoted 50,000) was surfaced. Do not cite a number without opening that page.

### 4.5 Batch sizes

| Endpoint | Limit |
|---|---|
| Batch read associations | 1,000 inputs per request body |
| Batch create associations | 2,000 inputs per request body |
| Batch archive | 100 unique `from` inputs per request |

Source: the associations guide (quoted: "Batch read associations: limited to 1,000 inputs per request body. Batch create associations: limited to 2,000 inputs per request body."). Note these differ from the **100**-input object batch limit — do not reuse the same chunk size.

> **UNCONFIRMED:** whether v4 batch association responses include `numErrors` / the same partial-success envelope as the object batch endpoints. The documented response shape is `{ "status": "COMPLETE", "results": [...], "startedAt": ..., "completedAt": ... }` with no `numErrors` surfaced.

### 4.6 Inline associations at create time

`POST /crm/v3/objects/{objectType}` accepts:

```json
{
  "properties": { "dealname": "Acme expansion" },
  "associations": [
    {
      "to": { "id": 9001 },
      "types": [ { "associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 341 } ]
    }
  ]
}
```

This works in `batch/create` too, and is the cheapest way to create a record plus its links in one call.

---

## 5. Rate limits

Source: <https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines>

### 5.1 Published limits

**Privately distributed apps (private apps):**

| Tier | Per 10 seconds | Per day |
|---|---|---|
| Free / Starter | 100 per app | 250,000 per account |
| Professional | 190 per app | 625,000 per account |
| Enterprise | 190 per app | 1,000,000 per account |
| With API Limit Increase add-on | 250 per app | +1,000,000 per increase (max 2) |

**Publicly distributed OAuth apps:** "Each HubSpot account that installs your app is limited to **110 requests every 10 seconds**" (excluding the CRM Search API). The API limit increase add-on does **not** apply to public apps.

Key scoping rule: **"All private apps in a HubSpot account collectively share the daily rate limit, but each private app will have its own separate burst limit."** (<https://developers.hubspot.com/changelog/increasing-our-api-limits>) — so splitting work across multiple private apps buys burst headroom but not daily headroom.

**CRM Search API is separately limited:** "The search endpoints are rate limited to **five requests per second per account**." (<https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm>) The 190/10s burst does not apply to it.

Max 20 private apps per account (<https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview>).

### 5.2 Response headers

| Header | Meaning |
|---|---|
| `X-HubSpot-RateLimit-Max` | Requests allowed per window |
| `X-HubSpot-RateLimit-Remaining` | Requests still available in the current window |
| `X-HubSpot-RateLimit-Interval-Milliseconds` | Window duration in ms |
| `X-HubSpot-RateLimit-Daily` | Daily allowance — **not returned for OAuth requests** |
| `X-HubSpot-RateLimit-Daily-Remaining` | Daily remaining — **not returned for OAuth requests** |

Source: usage-guidelines page. Historical `X-HubSpot-RateLimit-Secondly` / `-Secondly-Remaining` headers were **UNCONFIRMED** on the current page; do not depend on them.

### 5.3 429 behaviour

> "Any app or integration exceeding its rate limits will receive a `429` error response for all subsequent API calls."

The body follows the standard error envelope (§6) with `category: "RATE_LIMITS"`. The `policyName` field distinguishes which limit was hit (daily vs per-10-seconds).

> **UNCONFIRMED:** an exact verbatim 429 JSON body. No official page fetched showed one. Parse defensively: `status`, `message`, `errorType`, `category`, `policyName`, `correlationId` may each be absent.

Also: "Error requests should not exceed 5% of total daily requests" (usage-guidelines) — sustained error rates are themselves a policy violation.

### 5.4 `Retry-After` — **do not assume it is present**

This is the most commonly mis-assumed item. From <https://developers.hubspot.com/docs/api-reference/error-handling>, the only two verbatim mentions are:

- For **`477 Migration in Progress`**: "HubSpot will return a `Retry-After` response header indicating how many **seconds** to wait before retrying the request (typically up to 24 hours)."
- For **workflows** (HubSpot calling *your* endpoint): "workflows will automatically retry after receiving a 429 response, and will respect the `Retry-After` header if present. Note that the `Retry-After` value is in **milliseconds**."

**There is no official statement that a `Retry-After` header is returned on a standard CRM API `429`.** Treat it as: optional, absent by default, and **units differ by context** (seconds for 477; milliseconds in the workflow direction). Implement your own backoff and only use `Retry-After` opportunistically — and if you do, decide the unit from the status code, not from a global assumption.

---

## 6. Errors and retries

Source: <https://developers.hubspot.com/docs/api-reference/error-handling>

### 6.1 Standard error envelope

```json
{
  "status": "error",
  "message": "This will be a human readable message with details about the error.",
  "errors": [
    {
      "message": "discount was not a valid number",
      "code": "INVALID_INTEGER",
      "context": { "propertyName": ["discount"] }
    }
  ],
  "category": "VALIDATION_ERROR",
  "correlationId": "a43683b0-5717-4ceb-80b4-104d02915d8c"
}
```

| Field | Meaning |
|---|---|
| `status` | `"error"` |
| `message` | Human-readable summary |
| `errors[]` | Per-problem detail: `message`, `code`, `context` |
| `category` | e.g. `VALIDATION_ERROR`, `RATE_LIMITS`, `OBJECT_NOT_FOUND`, `MISSING_SCOPES` |
| `subCategory` | Finer-grained code, API-specific |
| `correlationId` | Unique per request; quote this in support tickets |

> **"the fields in the example response above should all be treated as optional"** — specific fields vary across APIs. Never hard-require any of them in your parser.

A full category→HTTP-status mapping table is **not** published.

### 6.2 Status codes

| Code | Meaning | Retryable |
|---|---|---|
| 200 | OK | — |
| 201 | Created | — |
| 207 | Multi-Status (mixed successes/failures) | No — inspect `errors[]`, retry only the failed rows |
| 400 | Bad request / validation | No |
| 401 | Unauthorized (invalid authentication) | No |
| 403 | Forbidden (insufficient permissions/scopes) | No |
| 404 | Not found | No |
| 414 | URI too long, or merge limit exceeded | No |
| 423 | Locked (rate limiting on bulk operations) | **Yes** |
| 429 | Too many requests | **Yes** |
| 477 | Migration in progress | **Yes** |
| 502 / 504 | Timeouts | **Yes** |
| 503 | Service unavailable | **Yes** |
| 521 / 522 / 523 / 524 / 525 / 526 | Server/connection issues | **Yes** (521, 523, 524 explicitly) |

Retryable set per the error-handling page: **423, 429, 477, 502, 503, 504, 521, 523, 524**.

### 6.3 Backoff guidance

HubSpot's published guidance is thin:

- For 502/504, 503, 521, 523, 524: "you should pause your requests for a few seconds, then retry."
- For 423 Locked: "you should include a delay of at least **2 seconds** between your API requests."
- For 477: honour `Retry-After` (seconds).

**There is no official exponential-backoff or jitter guidance.** Implement exponential backoff with full jitter yourself, cap concurrency, and keep the error rate under 5% of daily requests.

---

## 7. Webhooks

### 7.1 Which API, for which app type

Three distinct mechanisms exist today. Getting this wrong is an architecture-level mistake.

| Mechanism | Who can use it | Managed how |
|---|---|---|
| **Webhooks v3 API** (`/webhooks/v3/{appId}/...`) | **Legacy public apps only.** "The API endpoints and functionality in this article can only be used with legacy public apps." | REST API |
| **Private app webhooks** | Legacy private apps | **UI only** — no API |
| **New-platform webhooks** | Developer-platform (project) apps | `*-hsmeta.json` config file |
| **Webhooks Journal + Management v4 (beta)** | Apps with OAuth / client-credentials tokens | REST, pull-based |

Sources: <https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide>, <https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/create-and-edit-webhook-subscriptions-in-private-apps>, <https://developers.hubspot.com/docs/apps/developer-platform/add-features/configure-webhooks>, <https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide>

### 7.2 Webhooks v3 API endpoints (legacy public apps)

| Operation | Endpoint |
|---|---|
| Get/update delivery settings | `GET` / `PUT` `/webhooks/v3/{appId}/settings` |
| List / create subscriptions | `GET` / `POST` `/webhooks/v3/{appId}/subscriptions` |
| Update / delete a subscription | `PUT` / `DELETE` `/webhooks/v3/{appId}/subscriptions/{subscriptionId}` |
| Batch update subscriptions | `POST /webhooks/v3/{appId}/subscriptions/batch/update` |

### 7.3 Subscription types

Pattern `{object}.{event}`:

- **contact**: `contact.creation`, `contact.deletion`, `contact.merge`, `contact.restore`, `contact.propertyChange`, `contact.associationChange`, `contact.privacyDeletion`
- **company**: `company.creation`, `company.deletion`, `company.merge`, `company.restore`, `company.propertyChange`, `company.associationChange`
- **deal**: `deal.creation`, `deal.deletion`, `deal.merge`, `deal.restore`, `deal.propertyChange`, `deal.associationChange`
- **ticket**: `ticket.creation`, `ticket.deletion`, `ticket.merge`, `ticket.restore`, `ticket.propertyChange`, `ticket.associationChange`
- **product**: `product.creation`, `product.deletion`, `product.merge`, `product.restore`, `product.propertyChange`
- **line_item**: `line_item.creation`, `line_item.deletion`, `line_item.merge`, `line_item.restore`, `line_item.propertyChange`, `line_item.associationChange`
- **conversation**: `conversation.creation`, `conversation.deletion`, `conversation.privacyDeletion`, `conversation.propertyChange`, `conversation.newMessage`

`propertyChange` subscriptions take a `propertyName`; you create one subscription **per property**:

```json
{ "eventType": "company.propertyChange", "propertyName": "lifecyclestage", "active": true }
```

### 7.4 Payload shape — **a JSON array, confirmed**

> "You should expect to receive an **array of objects** in a single request. The batch size can vary, but will be under 100 notifications."

```json
[
  {
    "objectId": 1246965,
    "propertyName": "lifecyclestage",
    "propertyValue": "subscriber",
    "changeSource": "ACADEMY",
    "eventId": 3816279340,
    "subscriptionId": 25,
    "portalId": 33,
    "appId": 1160452,
    "occurredAt": 1462216307945,
    "eventType": "contact.propertyChange",
    "attemptNumber": 0
  }
]
```

| Field | Meaning (verbatim where quoted) |
|---|---|
| `objectId` | "The ID of the object that was created, changed, or deleted" |
| `eventId` | "The ID of the event that triggered this notification. **This value is not guaranteed to be unique**" |
| `subscriptionId` | "The ID of the subscription that triggered a notification" |
| `portalId` | "The customer's HubSpot account ID where the event occurred" |
| `appId` | "The ID of your application" |
| `occurredAt` | "When this event occurred as a **millisecond** timestamp" |
| `eventType` / `subscriptionType` | The subscription type string, e.g. `contact.propertyChange` |
| `attemptNumber` | "Starting at **0**, which number attempt this is" |
| `propertyName` | "Only sent for property change subscriptions" |
| `propertyValue` | "Only sent for property change subscriptions" |
| `changeSource` | "The source of the change" (e.g. `ACADEMY`, `CRM_UI`, `INTEGRATION`, `IMPORT`) |

Merge events add: `primaryObjectId` ("the ID of the merge winner"), `mergedObjectIds` ("an array of IDs that represent the records merged"), `newObjectId` ("the ID of the record created as result of merge"), `numberOfPropertiesMoved`.

Association-change events add: `associationType` (enum, e.g. `CONTACT_TO_COMPANY`, `COMPANY_TO_DEAL`), `fromObjectId`, `toObjectId`, `associationRemoved` (boolean), `isPrimaryAssociation`.

Conversation events add: `messageId`, `messageType` (`MESSAGE` or `COMMENT`).

Note the field name discrepancy: the v3 example payload uses **`eventType`**, while the subscription object and some docs refer to **`subscriptionType`**. Read both defensively.

### 7.5 Retry behaviour

> "HubSpot will attempt to re-send failed notifications **up to 10 times**."
> "These retries will be spread out over the next **24 hours**, with varying delays between requests. Individual notifications will have some randomization applied."

Retries are triggered by: connection failures, timeouts (**your endpoint taking longer than 5 seconds**), and HTTP 4xx or 5xx responses.

Return 2xx fast. Enqueue and process asynchronously — a 5-second budget is tight.

### 7.6 Throttling and concurrency

- "HubSpot sets a concurrency limit of **10 requests** when sending subscription event data."
- Configurable via `maxConcurrentRequests` in the settings object; "must be a number greater than five."
- "Each request can contain up to **100 events**."
- Private apps: "A limit of **1000 webhook subscriptions** applies per private app."

### 7.7 Ordering and duplicates — **neither is guaranteed**

> "HubSpot does not guarantee that you'll receive these notifications in the order they occurred."
> "HubSpot also does not guarantee that you'll only get a single notification for an event. Though this should be rare, it is possible that HubSpot will send you the same notification multiple times."

Use `occurredAt` to reconstruct sequence. Do **not** dedupe on `eventId` alone — the docs explicitly say it "is not guaranteed to be unique." Dedupe on a composite (`subscriptionId` + `objectId` + `propertyName` + `occurredAt`) and make handlers idempotent.

### 7.8 Webhooks Journal + Management v4 (beta) — the pull-based alternative

Source: <https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide>

> "these APIs provide a new subscription model and are **not** currently compatible with the previous version (v3) of the webhooks API."

| Endpoint | Purpose |
|---|---|
| `GET /webhooks-journal/journal/v4/earliest` | Earliest available offset |
| `GET /webhooks-journal/journal/v4/latest` | Latest offset |
| `GET /webhooks-journal/journal/v4/offset/{offset}/next` | Next page of events |
| `POST` / `GET` `/webhooks-journal/subscriptions/v4` | Create / list subscriptions |
| `DELETE /webhooks-journal/subscriptions/v4/{subscriptionId}` | Delete subscription |
| `DELETE /webhooks-journal/subscriptions/v4/portals/{portalId}` | Delete all for a portal |
| `POST /webhooks-journal/snapshots/v4/crm` | Request a full snapshot |

Subscription types: `OBJECT`, `ASSOCIATION`, `APP_LIFECYCLE_EVENT`. Actions: `CREATE`, `UPDATE`, `DELETE`, `MERGE`, `RESTORE`, `ASSOCIATION_ADDED`, `ASSOCIATION_REMOVED`, `SNAPSHOT`.

Event data is delivered as JSON inside a file at a signed URL, wrapped as `{ "offset": "<uuid>", "journalEvents": [...], "publishedAt": "..." }`. CRM object events carry `type`, `portalId`, `occurredAt`, `action`, `objectTypeId`, `objectId`, `propertyChanges`. Association events carry `fromObjectId`, `toObjectId`, `fromObjectTypeId`, `toObjectTypeId`, `associationTypeId`, `associationCategory`, `isPrimary`.

Rate limits: 100 req/s (journal), 50 req/s (subscriptions), 10 req/s (snapshots). Requires OAuth 2.0, including client-credentials tokens. Journal offsets give you **idempotent, ordered** processing — the main reason to prefer it over v3 push webhooks where it is available.

---

## 8. Webhook signature validation

Primary sources:
- <https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/request-validation> (current platform)
- <https://developers.hubspot.com/docs/guides/apps/authentication/validating-requests> (legacy apps)
- <https://developers.hubspot.com/changelog/introducing-version-3-of-webhook-signatures> (announced **Oct 25, 2021**)

### 8.1 Headers

| Header | Purpose |
|---|---|
| `X-HubSpot-Signature-v3` | The v3 signature (Base64) |
| `X-HubSpot-Request-Timestamp` | Milliseconds since epoch; **v3 only** |
| `X-HubSpot-Signature` | The v1 or v2 signature (hex) |
| `X-HubSpot-Signature-Version` | Indicates `v1` or `v2` |

All may be present on the same request for backward compatibility. Validate v3 if present.

### 8.2 v3 — the exact procedure

Verbatim steps from the changelog and the request-validation page:

1. > "Reject the request if the timestamp is older than **5 minutes**."
2. Decode the URI (see §8.3).
3. > "Create a **utf-8** encoded string that concatenates together the following: **requestMethod + requestUri + requestBody + timestamp**."
4. > "Create an **HMAC SHA-256** hash of the resulting string using the **application secret** as the secret for the HMAC SHA-256 function."
5. > "**Base64** encode the result of the HMAC function."
6. > "Compare the hash value to the signature, and if they're equal then this request has been verified as originating from HubSpot." Use "constant-time string comparison to guard against timing attacks."

Answering the specific questions:

| Question | Answer |
|---|---|
| What is signed? | `requestMethod` + `requestUri` + `requestBody` + `timestamp` — **no separators, no delimiters** |
| Exact order? | method, then URI, then body, then timestamp. Timestamp is **last**. |
| Hash? | HMAC-SHA256, keyed with the **app/client secret** |
| Encoding? | **Base64** (v3). v1/v2 are **hex**. |
| Timestamp header? | `X-HubSpot-Request-Timestamp`, **milliseconds** since epoch |
| Max age? | **5 minutes** — confirmed, stated on both the changelog and the current request-validation page |
| Body when absent? | The empty string (concatenate nothing) |

Reference implementation (Node.js, from the docs):

```javascript
const signatureHeader = headers["x-hubspot-signature-v3"];
const timestampHeader = headers["x-hubspot-request-timestamp"];

// 1. reject stale
if (Date.now() - Number(timestampHeader) > 5 * 60 * 1000) reject();

// 2-4. build + hash + encode
const rawString = `${method}${uri}${JSON.stringify(body)}${timestampHeader}`;
const hashedString = crypto
  .createHmac("sha256", process.env.CLIENT_SECRET)
  .update(rawString)
  .digest("base64");

// 5. constant-time compare
crypto.timingSafeEqual(Buffer.from(hashedString), Buffer.from(signatureHeader));
```

> **Production warning about the sample:** the docs' sample uses `JSON.stringify(body)`, which re-serializes an already-parsed body. That only matches if your JSON parser round-trips byte-for-byte (key order, whitespace, unicode escapes). **Capture and hash the raw request body bytes** as received. This is the single most common cause of signature mismatches and the docs do not call it out.

### 8.3 URI construction and percent-decoding

The URI must be the **full URL including protocol and host**, matching exactly what HubSpot requested, with query parameters in their original order.

The docs require **decoding** these percent-encoded characters in the request URI before hashing:

| Encoded | Decoded | Encoded | Decoded |
|---|---|---|---|
| `%3A` | `:` | `%29` | `)` |
| `%2F` | `/` | `%2A` | `*` |
| `%3F` | `?` | `%2C` | `,` |
| `%40` | `@` | `%3B` | `;` |
| `%21` | `!` | `%24` | `$` |
| `%27` | `'` | `%28` | `(` |

> "You do not need to decode the question mark that denotes the beginning of the query string."

Practical note: if your webhook endpoint is a plain path with no query string and no special characters (recommended), this table never bites you. Behind a proxy/load balancer, reconstruct the URI from `X-Forwarded-Proto` and `X-Forwarded-Host`, not from the internal request object — the protocol must match what HubSpot called.

### 8.4 v1 and v2 (for completeness)

| | v1 | v2 |
|---|---|---|
| Used for | Legacy CRM object events via the webhooks API (this includes **private app webhooks**) | Webhook actions in workflows; custom CRM cards / app cards |
| Source string | `clientSecret + requestBody` | `clientSecret + httpMethod + URI + requestBody` |
| Hash | SHA-256 (plain hash, **not** HMAC) | SHA-256 (plain hash, **not** HMAC) |
| Encoding | hex | hex |
| Header | `X-HubSpot-Signature` | `X-HubSpot-Signature` |
| Example source | `yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy[{"eventId":1,...}]` | `yyyyyyyy-...-yyyyyyyyyyyyGEThttps://www.example.com/webhook_uri` |
| Example digest | `232db2615f3d666fe21a8ec971ac7b5402d33b9a925784df3ca654d05f4817de` | `eee2dddcc73c94d699f5e395f4b9d454a069a6855fbfa152e91e88823087200e` |

v2 notes from the docs: "The URI used to build the source string must exactly match the original request, including the protocol"; query parameters must be in their original order; the source string must be UTF-8 encoded before hashing.

### 8.5 Private app webhooks specifically

Source: <https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/create-and-edit-webhook-subscriptions-in-private-apps>

> "HubSpot populates a `X-HubSpot-Signature` header with a SHA-256 hash that's built using your **private app's client secret** along with data from the request itself."

That is the **v1** scheme (`clientSecret + requestBody`, SHA-256, hex) — not HMAC, not Base64. The private app's client secret is found on the app's **Auth** tab.

> **UNCONFIRMED:** whether private app webhook deliveries *also* carry `X-HubSpot-Signature-v3` / `X-HubSpot-Request-Timestamp`. The changelog scoped v3 to "outgoing HubSpot requests to OAuth Apps." Write your verifier to prefer v3 when the header is present and fall back to v1, and log which path fired.

---

## 9. Private apps vs public apps vs OAuth

### 9.1 Private apps

Source: <https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview>

| Fact | Value |
|---|---|
| What it is | Single-account API access with a static, scoped access token |
| Create via | HubSpot UI → **Development → Legacy apps → Create legacy app → Private** (historically Settings → Integrations → Private Apps) |
| Who can create | "You must be a super admin to access private apps in your HubSpot account." |
| Auth header | `Authorization: Bearer <token>` |
| Token expiry | Tokens do **not** auto-expire; rotation is manual. Rotation recommended every 6 months, with immediate-revoke or 7-day-grace options. |
| Token introspection | `POST /oauth/v2/private-apps/get/access-token-info` |
| Max per account | **20** |
| Client secret | On the app's **Auth** tab (used for webhook signature validation) |

**Stated limitations (verbatim):**

> "Webhooks are supported in private apps, but subscriptions cannot be edited programmatically via an API, and must instead be edited in your private app settings. Private apps do not support custom timeline events, if you plan on building an app using custom timeline events, you should create a public app instead."

### 9.2 Answering the architecture question: can private apps use webhooks?

**Yes — but not via the Webhooks API.** This is an important nuance and the premise in most write-ups is half-wrong in both directions:

| Claim | Verdict |
|---|---|
| "Private apps cannot receive webhooks" | **False.** They can. Subscriptions cover CRM object events (contacts, companies, deals, tickets, products, line items) and conversations events. |
| "Private apps can manage webhooks via the Webhooks v3 API" | **False.** "Managing your private app's webhook subscriptions via API is not currently supported. Subscriptions can only be managed in your private app settings." And the v3 API guide states it "can only be used with legacy public apps." |
| "Private app webhook payloads are signed the same way" | **Partly false.** Private app webhooks are documented as using the **v1** `X-HubSpot-Signature` scheme with the private app client secret (see §8.5). |

**Architectural consequence:** if your integration must **provision** webhook subscriptions programmatically (per-customer onboarding, dynamic property lists, CI-managed config), a private app is the wrong shape — you need a public/OAuth app, or a developer-platform project app where webhooks live in a `*-hsmeta.json` file under version control. For a single-tenant internal GTM system where the subscription set is set up once by hand, a private app is fine.

Private app webhook subscription cap: **1000 per private app**. Concurrency: 10 requests.

### 9.3 Public apps / OAuth

- Public apps use the OAuth 2.0 authorization code flow, are installable into many accounts, and are the only path to the Webhooks v3 API, custom timeline events, and marketplace listing.
- Source: <https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/overview> — "If you plan to distribute your app to multiple accounts... your app must be built using OAuth authentication"; "OAuth is required for multiple accounts, while static auth access tokens are used for installing in a single account at a time."
- **Client credentials** tokens exist (`POST /oauth/2026-03/token`), but "client credential tokens aren't used to act on behalf of users" and are currently scoped to the webhooks journal API.
- Public app rate limit: 110 requests / 10 seconds per installing account, and the API limit increase add-on does not apply.

> **UNCONFIRMED:** the public-app access token TTL (commonly 30 minutes) and refresh-token semantics were not restated on the pages fetched. Check the OAuth token management reference (<https://developers.hubspot.com/docs/api-reference/latest/authentication/manage-oauth-tokens>) before building refresh logic.

### 9.4 Scopes

Source: <https://developers.hubspot.com/docs/apps/legacy-apps/authentication/scopes>. All of the following are listed as available to "Any account" (no tier gate).

| Need | Scope |
|---|---|
| Read contacts | `crm.objects.contacts.read` |
| Write contacts | `crm.objects.contacts.write` |
| Read companies | `crm.objects.companies.read` |
| Write companies | `crm.objects.companies.write` |
| Read deals | `crm.objects.deals.read` |
| Write deals | `crm.objects.deals.write` |
| Read property definitions (contacts) | `crm.schemas.contacts.read` |
| **Create/edit property definitions (contacts)** | `crm.schemas.contacts.write` |
| Read property definitions (companies) | `crm.schemas.companies.read` |
| **Create/edit property definitions (companies)** | `crm.schemas.companies.write` |
| Read property definitions (deals) | `crm.schemas.deals.read` |
| **Create/edit property definitions (deals)** | `crm.schemas.deals.write` |

Verbatim: `crm.schemas.companies.write` = "Create, delete, or make changes to property settings for companies." So **custom property creation needs `crm.schemas.{object}.write`, not `crm.objects.{object}.write`** — a frequent 403 cause.

Associations: reading/writing associations between two object types requires the object scopes for **both** sides.

**Webhook scopes:** there is no separate `webhooks` scope. Per <https://developers.hubspot.com/changelog/announcement-scopes-will-be-required-for-apps-using-webhooks-or-crm-extensions>, apps using webhooks must hold the scopes for the objects they subscribe to. The private app UI enforces this: "If you select an object type that requires scopes your app hasn't been authorized for, you'll be prompted to add those scopes to your app."

---

## 10. Free developer and test environments

Source unless noted: <https://developers.hubspot.com/docs/getting-started/account-types>

### 10.1 Developer accounts — retired

> "Developer accounts are a type of legacy account used for creating and managing legacy apps."
> "as of March 9, 2026, all legacy developer accounts were migrated to standard HubSpot accounts. None of your existing apps, developer test accounts, or keys were impacted."

App development now happens inside a standard HubSpot account. (Whether the legacy developer account itself held CRM records is **UNCONFIRMED** and now moot.)

### 10.2 Developer test accounts — free, 10 per account

| Fact | Verbatim / value |
|---|---|
| Quantity | "You can create up to **10 test accounts** per standard HubSpot account." |
| Cost | Free |
| Features | "a **90-day trial** of many enterprise features" |
| Expiry | "Developer test accounts will expire after **90 days** if no API calls are made to the account." |
| Data sync | "Test accounts **cannot sync data** with other accounts." |
| Workflow enrolment cap | "a maximum of **100,000 records** can be enrolled per day in workflows created in a developer test account" |

- **Private apps in test accounts:** supported — HubSpot documents building private apps with projects in developer test accounts for free. (Cited via developers.hubspot.com content; the exact page URL was not independently re-verified — treat as high confidence, not verbatim-cited.)
- **Webhooks in test accounts:** **UNCONFIRMED.** No official sentence found either way. Since test accounts get Enterprise-level trial features and private apps work there, private-app webhooks are very likely available, but verify before designing around it.
- Marketing email sending in test accounts is restricted to addresses added to the test account (**UNCONFIRMED** exact wording).

### 10.3 Free standard HubSpot account

- The private apps overview lists **Free, Starter, Professional, Enterprise** together in its rate-limit table and states only one gate: "You must be a super admin." There is no explicit sentence reading "private apps are available on the free tier," so treat all-tier availability as **highly likely but not verbatim-confirmed**.
- Free-plan record limits: <https://knowledge.hubspot.com/data-management/track-crm-data-limits> explicitly defers — "limits shown will depend on your HubSpot subscription" — and points to the HubSpot Product & Services Catalog as authoritative. Specific numeric free-tier caps are **UNCONFIRMED** on the two approved doc domains.

### 10.4 Sandboxes — Enterprise only

Source: <https://knowledge.hubspot.com/account-management/set-up-a-hubspot-standard-sandbox-account>

Standard sandboxes require an **Enterprise** subscription: Marketing Hub Enterprise, Sales Hub Enterprise, Service Hub Enterprise, Data Hub Enterprise, Content Hub Enterprise, Smart CRM Enterprise, or Revenue Hub Enterprise.

Sandbox creation copies "up to 5,000 of your most recently updated contacts" plus "up to 100 of their associated deals, companies, and tickets (per contact)."

Legacy standard sandboxes: "Legacy Standard Sandboxes will be sunset on **April 30, 2026**" (<https://developers.hubspot.com/changelog/legacy-standard-sandboxes-sunset-whats-changing-how-to-prepare-faq>) — already past as of today.

> **UNCONFIRMED:** exact number of sandboxes per Enterprise account; development-sandbox mechanics (CLI-created, schema-only sync).

### 10.5 What a free-account user can actually build

Feasible end to end at zero cost:

1. Create a **private app** in the free CRM (super admin required) — Settings → Integrations → Private Apps / Development → Legacy apps.
2. Grant `crm.objects.{contacts,companies,deals}.{read,write}` and `crm.schemas.{contacts,companies,deals}.write`.
3. Use the resulting non-expiring bearer token against `/crm/v3/objects/...`, `/crm/v3/properties/...`, `/crm/v4/associations/...`.
4. Configure **webhook subscriptions in the private app UI** and validate with the v1 `X-HubSpot-Signature` scheme using the app's client secret.
5. Spin up up to **10 free developer test accounts** (90-day Enterprise-feature trials) for destructive testing.

Not available on free: sandboxes (Enterprise), custom timeline events (public apps), programmatic webhook subscription management (public apps).

---

## 11. Gotchas a real integration gets wrong

### 11.1 Property internal names

- Internal names are **immutable**: "You cannot edit the property's object type or internal name." (<https://knowledge.hubspot.com/properties/create-and-edit-properties>) Pick carefully; a rename means a new property plus a backfill.
- All official examples use `lowercase_with_underscores`. The explicit character rule is documented for custom-event properties, not CRM properties — **UNCONFIRMED** for CRM, but write lowercase snake_case anyway.
- Property **labels** are what the UI shows; **internal names** are what the API takes. They diverge freely.

### 11.2 Enumerations: values, not labels

The properties guide defines `enumeration` as "A string representing a set of options, with options separated by a semicolon."

Multi-select append syntax, verbatim: "add a semicolon before the first value, and separate the values with semicolons without a space between." So `;optionA;optionB` appends, and the delimiter is `;` with **no spaces**.

> **UNCONFIRMED verbatim:** an explicit sentence reading "send the internal value, not the label." Option objects carry distinct `label` and `value` fields, and sending labels is a well-known failure mode, but no single official imperative sentence was found. Send `value`.

Read the allowed set from `GET /crm/v3/properties/{objectType}/{propertyName}` and map before writing. `dealstage` in particular takes an internal stage ID (often a numeric-looking string like `appointmentscheduled` or `1234567`), never the display name.

### 11.3 Date vs datetime — **midnight UTC is required for `date`**

Confirmed verbatim from <https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide>:

> "it is recommended to use the ISO 8601 complete date format. If you use the UNIX timestamp format, you must use an EPOCH millisecond timestamp (i.e. **the value must be set to midnight UTC for the date**)."

| Property `type` | Accepted formats |
|---|---|
| `date` | ISO 8601 `YYYY-MM-DD`, **or** epoch milliseconds aligned to `00:00:00.000Z` (e.g. `1652659200000` = `2022-05-16T00:00:00Z`) |
| `datetime` | ISO 8601 with time, or epoch milliseconds (any time of day) |

> **UNCONFIRMED:** the exact error returned for a non-midnight epoch sent to a `date` property. The quoted "must" implies rejection; commonly a 400 validation error. Normalize with `Math.floor(ts / 86400000) * 86400000` before writing.

Timezone trap: computing "midnight" in local time and converting shifts the date by a day for anyone west of UTC. Always floor in UTC.

### 11.4 Currency

- `deal_currency_code` is validated against the account's configured currencies: since **July 31, 2023**, "only the default currency or currencies established in the HubSpot account" are valid. (<https://developers.hubspot.com/changelog/deal-currenct-code-validation>, <https://developers.hubspot.com/docs/api-reference/settings-multicurrency-v3/guide>)
- `amount` is in the deal's currency; `hs_deal_amount_in_home_currency` holds the value converted to the account's home currency using the exchange rate configured in Settings. **UNCONFIRMED verbatim** — no official definition sentence was retrieved for that property; it is read-only/calculated in practice.
- Report and reconcile on the home-currency field, not `amount`, if deals span currencies.

### 11.5 Deleted records

- Normal delete → recycle bin, **90-day** restore window. Permanent (GDPR) delete bypasses the recycle bin and "it may take up to **30 days** to complete a permanent purge." (<https://knowledge.hubspot.com/privacy-and-consent/how-do-i-perform-a-gdpr-delete-in-hubspot>)
- A GDPR-deleted contact's email is blocklisted from re-add via UI/import, but **can still reappear via forms or the API**.
- `contact.privacyDeletion` and `conversation.privacyDeletion` webhook events fire for permanent deletes; `*.deletion` for normal ones; `*.restore` when un-deleted.
- **UNCONFIRMED verbatim:** the exact API surfacing of archived records (`archived=true` query parameter on list/read, 404 vs empty on GET). `archived=true` is the long-standing CRM v3 pattern but was not re-quoted from an official page in this pass.

### 11.6 Merged records — old IDs keep resolving

Confirmed verbatim from <https://developers.hubspot.com/changelog/updated-merge-functionality-for-contacts-and-companies>:

> "both of the previous IDs will point to the resulting merged record, so fetching any records using the original IDs will return the new merged record with the new ID."

So `GET /crm/v3/objects/contacts/{oldId}` does **not** 404 — it silently returns a record whose `hs_object_id` differs from the ID you asked for. Any code that assumes `response.id === requestedId` will corrupt your mapping table. Always reconcile on the returned `id`.

- `hs_merged_object_ids` stores the absorbed IDs (**UNCONFIRMED** verbatim).
- `*.merge` webhook events carry `primaryObjectId`, `mergedObjectIds`, `newObjectId`, `numberOfPropertiesMoved` — enough to repair a mapping table, if you subscribe to them.
- A "Primary ID Preservation for Merged Records" beta exists that keeps the surviving record's original ID rather than minting a new one (**UNCONFIRMED** status/availability) — behaviour may differ by portal.

### 11.7 Read-only and calculated properties

> "Calculation properties created via API cannot be edited within HubSpot. You can only edit these properties via the properties API." (<https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide>)

Calculated/rollup properties, `hs_object_id`, `createdate`, and `hs_lastmodifieddate` are not settable on records. A complete official list of read-only default properties was **not** found in one place — **UNCONFIRMED as a complete list**. Fetch `GET /crm/v3/properties/{objectType}` and filter on `modificationMetadata.readOnlyValue` / `calculated` to build the exclusion set at runtime.

### 11.8 Search API — the limits that actually bite

Source: <https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm>, corroborated by <https://developers.hubspot.com/changelog/increasing-our-api-limits>

| Limit | Verbatim |
|---|---|
| Rate | "The search endpoints are rate limited to **five requests per second per account**." |
| Page size | "The maximum number of supported objects per page is **200**." |
| Total results | "The search endpoints are limited to **10,000 total results** for any given query. Attempting to page beyond 10,000 will result in a **400** error." |
| Query size | "A query can contain a maximum of **3,000 characters**. If the body of your request exceeds 3,000 characters, a 400 error will be returned." |
| Indexing | "It may take a few moments for newly created or updated CRM objects to appear in search results." |
| Filters | Max 5 `filterGroups` × 6 filters each (18 total) |

The 10,000 cap is the classic full-sync failure. Work around it by sorting on `hs_lastmodifieddate` ascending and paging with a moving `>` filter rather than deep `after` offsets.

The indexing delay means **read-after-write via Search is not reliable**. Read back by ID.

### 11.9 `lastmodifieddate` vs `hs_lastmodifieddate`

Contacts expose **`lastmodifieddate`**; other standard objects (companies, deals, tickets, custom objects) use **`hs_lastmodifieddate`**. The contacts field name is directly confirmed in the official example response at <https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/guide>; the general "contacts are the exception" rule is **not stated as a single sentence on an official page** — **UNCONFIRMED** as a documented rule, though consistent with the object definitions. Incremental-sync code must branch on object type.

### 11.10 Other traps worth pinning

- **`0`/`1` vs `279`/`280`** for contact↔company associations (see §4.2). The low IDs set *primary*.
- **`objectWriteTraceId` is mandatory in practice** on `batch/create` if you want per-row error reporting (§3.4).
- **Object batch = 100, association batch create = 2,000, association batch read = 1,000, association batch archive = 100.** Four different chunk sizes.
- **Daily rate limit is shared across all private apps in an account**; burst is per app.
- **`idProperty` is a body field on batch endpoints, a query parameter on single-record endpoints.**
- **`type: "datetime"` still uses `fieldType: "date"`.**
- **The contact `company` property is free text**, not a link to a company record. Associations are the link.
- **Search rate limit (5/s) is separate from the 190/10s burst** and much tighter.

---

## Source index

| Topic | URL |
|---|---|
| Account types, test accounts | <https://developers.hubspot.com/docs/getting-started/account-types> |
| Understanding the CRM, object type IDs | <https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm> |
| Using object APIs, batch | <https://developers.hubspot.com/docs/guides/crm/using-object-apis> |
| Properties guide | <https://developers.hubspot.com/docs/guides/api/crm/properties>, <https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide> |
| Associations v4 guide + type IDs | <https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide> |
| Search API | <https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm> |
| Error handling | <https://developers.hubspot.com/docs/api-reference/error-handling> |
| Rate limits | <https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines> |
| Webhooks v3 (legacy public apps) | <https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide> |
| Webhooks journal v4 (beta) | <https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide> |
| Private app webhooks | <https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/create-and-edit-webhook-subscriptions-in-private-apps> |
| Request validation (current) | <https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/request-validation> |
| Request validation (legacy) | <https://developers.hubspot.com/docs/guides/apps/authentication/validating-requests> |
| Signature v3 changelog (2021-10-25) | <https://developers.hubspot.com/changelog/introducing-version-3-of-webhook-signatures> |
| Private apps overview | <https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview> |
| Scopes | <https://developers.hubspot.com/docs/apps/legacy-apps/authentication/scopes> |
| Auth overview (new platform) | <https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/overview> |
| API versioning | <https://developers.hubspot.com/docs/developer-tooling/platform/versioning> |
| Date-based versioning changelog | <https://developers.hubspot.com/changelog/introducing-date-based-api-versioning> |
| Batch 200/207 changelog | <https://developers.hubspot.com/changelog/simplifying-batch-update-response-codes-for-crm-v3-apis> |
| Unique properties for contacts | <https://developers.hubspot.com/changelog/unique-properties-for-contacts> |
| Deduplication of records | <https://knowledge.hubspot.com/records/deduplication-of-records> |
| Create and edit properties | <https://knowledge.hubspot.com/properties/create-and-edit-properties> |
| Property field types | <https://knowledge.hubspot.com/properties/property-field-types-in-hubspot> |
| Merge functionality changelog | <https://developers.hubspot.com/changelog/updated-merge-functionality-for-contacts-and-companies> |
| GDPR delete | <https://knowledge.hubspot.com/privacy-and-consent/how-do-i-perform-a-gdpr-delete-in-hubspot> |
| Standard sandboxes | <https://knowledge.hubspot.com/account-management/set-up-a-hubspot-standard-sandbox-account> |
| Custom property limits | <https://developers.hubspot.com/docs/api-reference/crm-limits-tracking-v3/guide> |
| API limits increase changelog | <https://developers.hubspot.com/changelog/increasing-our-api-limits> |
| Deal currency validation | <https://developers.hubspot.com/changelog/deal-currenct-code-validation> |
