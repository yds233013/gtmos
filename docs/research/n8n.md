# n8n — factual reference for the GTMOS integration

Research date: **2026-09-22**. Sources are `docs.n8n.io` (the `.md` variant of each page,
obtained by appending `.md` to the URL), the n8n GitHub releases feed, and the n8n source
tree on GitHub. Anything not confirmable from those is marked **UNCONFIRMED**.

Version context at time of writing: **current `stable` = 2.40.5** (released 2026-09-21);
`beta` also 2.40.5; `2.41.0` exists as a pre-release.
([releases](https://github.com/n8n-io/n8n/releases),
[install-with-docker](https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker.md)
states verbatim: "Current `stable`: 2.40.5 Current `beta`: 2.40.5").

Local Docker available: `Docker version 28.1.1, build 4eba377`.

---

## 0. Executive summary for this project

| Question | Answer |
|---|---|
| Image | `n8nio/n8n`, pinned — `n8nio/n8n:2.40.5` |
| Tags | `stable` / `beta` replaced `latest` / `next` in 2.0; n8n recommends pinning an exact version |
| Persistence | named volume mounted at `/home/node/.n8n` |
| Host access from container | `http://host.docker.internal:<port>` (Docker Desktop); on Linux add `--add-host=host.docker.internal:host-gateway` |
| Import | `n8n import:workflow --separate --input=<dir>` — **always imports deactivated** |
| Activation | 2.0 replaced active/inactive with **publish/unpublish**: `n8n publish:workflow --id=<ID>`, then **restart n8n** |
| Public API | `/api/v1`, header `X-N8N-API-KEY`; **not available during the free trial** |

---

## 1. Running locally with Docker

### 1.1 Image and tags

Official image: **`n8nio/n8n`** on Docker Hub.

n8n 2.0 renamed the release channels: "n8n has renamed the release channels from `latest` and
`next` to `stable` and `beta`… For now, n8n will continue to tag releases as `latest` and
`next`. These tags will be removed in a future major version." The same page's recommendation
is explicit: "Pin your n8n version to a specific version number, for example, `2.0.0`."
([v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes.md))

So: use `n8nio/n8n:2.40.5`. Do not use `:latest` — it is a tag on notice, and n8n ships a new
minor "most weeks"
([install-with-docker](https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker.md)).

n8n also publishes a separate **`n8nio/runners`** image. From 2.0 "the main `n8nio/n8n` Docker
image will no longer include the task runner for external mode"
([v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes.md)).

### 1.2 The documented `docker run`

Verbatim from
[install-with-docker](https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker.md)
(note: that page now carries an "This content is outdated" banner pointing at
[install-using-docker-compose](https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose.md)
as the recommended method — but it is still the only page with a canonical `docker run`):

```shell
docker volume create n8n_data

docker run -it --rm \
 --name n8n \
 -p 5678:5678 \
 -e GENERIC_TIMEZONE="<YOUR_TIMEZONE>" \
 -e TZ="<YOUR_TIMEZONE>" \
 -e N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true \
 -e N8N_RUNNERS_ENABLED=true \
 -v n8n_data:/home/node/.n8n \
 n8nio/n8n
```

Editor at `http://localhost:5678`.

**Required volume for persistence:** `/home/node/.n8n`. Even when using Postgres as the
database, the docs say to keep it: the directory "contains other important data like encryption
keys, instance logs, and source control feature assets."

**The command I would use for GTMOS** (pinned, host-reachable, cookie-safe on plain HTTP):

```shell
docker volume create n8n_data

docker run -d --name n8n \
  -p 5678:5678 \
  --add-host=host.docker.internal:host-gateway \
  -e GENERIC_TIMEZONE="UTC" \
  -e TZ="UTC" \
  -e N8N_SECURE_COOKIE=false \
  -e N8N_ENCRYPTION_KEY="<32+ random chars>" \
  -e N8N_WEBHOOK_URL="http://localhost:5678/" \
  -e N8N_DIAGNOSTICS_ENABLED=false \
  -v n8n_data:/home/node/.n8n \
  -v "$PWD/integrations/n8n:/workflows:ro" \
  n8nio/n8n:2.40.5
```

### 1.3 The `N8N_*` variables that matter

| Variable | Default | Meaning | Source |
|---|---|---|---|
| `N8N_HOST` | `localhost` | Host name n8n runs on | [deployment](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/deployment.md) |
| `N8N_PORT` | `5678` | HTTP port n8n runs on | same |
| `N8N_LISTEN_ADDRESS` | `::` | IP address n8n listens on | same |
| `N8N_PROTOCOL` | `http` | `http` or `https` | same |
| `N8N_PATH` | `/` | Sub-path n8n deploys to | same |
| `N8N_ENCRYPTION_KEY` | random, generated on first launch | Key used to encrypt credentials in the DB | same |
| `N8N_EDITOR_BASE_URL` | – | Public URL of the editor; also used in emails and SAML redirect | same |
| `N8N_USER_FOLDER` | `user-folder` | Where n8n creates `.n8n` | same |
| `N8N_SECURE_COOKIE` | `true` | Cookies only over HTTPS. **Set `false` for plain-HTTP localhost or you cannot log in.** | [security](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/security.md) |
| `N8N_SAMESITE_COOKIE` | `lax` | `strict` / `lax` / `none` | same |
| `GENERIC_TIMEZONE` | `America/New_York` | Instance timezone; matters for Schedule/Cron nodes | [timezone](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/timezone-and-localization.md) |
| `N8N_WEBHOOK_URL` | – | Base URL for **both** test and production webhooks behind a proxy | [endpoints](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/endpoints.md) |
| `WEBHOOK_URL` | – | **Deprecated from n8n 2.35.0**; alias of `N8N_WEBHOOK_URL`. "Still works, but n8n logs a deprecation warning on startup." | same |
| `N8N_ENDPOINT_WEBHOOK` | `webhook` | Production webhook path segment | same |
| `N8N_ENDPOINT_WEBHOOK_TEST` | `webhook-test` | Test webhook path segment | same |
| `N8N_ENDPOINT_WEBHOOK_WAIT` | `webhook-waiting` | Waiting-webhook path segment | same |
| `N8N_ENDPOINT_REST` | `rest` | Internal REST endpoint path | same |
| `N8N_ENDPOINT_HEALTH` | `healthz` | Health check path | same |
| `N8N_PAYLOAD_SIZE_MAX` | 16 MB effective | Max webhook payload | [Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook.md) |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | see note | Blocks `$env` in expressions and Code node | [security](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/security.md) |
| `NODE_FUNCTION_ALLOW_BUILTIN` | – | Allow-list of Node built-ins the Code node may `require()` | [enable modules in Code node](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/configuration-examples/enable-modules-in-code-node.md) |
| `N8N_DIAGNOSTICS_ENABLED` | `true` | Anonymous telemetry to n8n | [deployment](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/deployment.md) |

**Documentation conflict, flagged.** The v2.0 breaking-changes page says "The default value for
`N8N_BLOCK_ENV_ACCESS_IN_NODE` is now set to `true`"
([v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes.md)), while the
current environment-variable reference table still lists the default as `false`
([security](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/security.md)).
Which one is live in 2.40.5 is **UNCONFIRMED**. Set it explicitly to `false` if workflows read
`$env` — that is correct under either reading.

### 1.4 Task runners

`N8N_RUNNERS_ENABLED` is **no longer needed**. Verbatim:

> `N8N_RUNNERS_ENABLED` is deprecated from n8n 2.0. You no longer need to set it. It's still
> supported in n8n 1.x, where you must set it to `true` to enable task runners.
> — [install-with-docker](https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker.md)

From 2.0, task runners are on by default and "All Code node executions will run on task
runners." Two consequences worth knowing:

- `$evaluateExpression()` no longer works inside the Code node (secure mode disables evaluating
  strings as code); it returns `null` or errors. The escape hatch is
  `N8N_RUNNERS_INSECURE_MODE=true`, described as a temporary workaround.
- The Pyodide-based Python Code node is gone; native Python requires task runners in **external
  mode**, which requires the separate `n8nio/runners` image.

([v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes.md),
[set up task runners](https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners.md))

### 1.5 Other breaking changes in 2.x worth knowing

All from [v2.0 breaking changes](https://docs.n8n.io/changelog/v20-breaking-changes.md):

- **Active/inactive → publish/unpublish.** "The new workflow publishing system replaces the
  previous active/inactive toggle." Editing a workflow no longer changes what production runs
  until you publish.
- **Start node removed.** Replace with Manual Trigger / Execute Workflow Trigger.
- **`ExecuteCommand` and `LocalFileTrigger` disabled by default** (via `NODES_EXCLUDE`).
- **`N8N_RESTRICT_FILE_ACCESS_TO` now defaults** to `~/.n8n-files`.
- **MySQL/MariaDB dropped** as storage backends; Postgres or SQLite only.
- **Legacy SQLite driver removed**; `sqlite-pooled` is the default (`DB_SQLITE_POOL_SIZE`
  default `2`).
- **In-memory binary data mode removed**; `filesystem` (regular) / `database` (queue) / `s3`.
- **`n8n --tunnel` removed.** Use ngrok / localtunnel / Cloudflare Tunnel instead. Note this
  contradicts the still-published
  [webhook workflow-development](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/workflow-development.md)
  page, which still tells you to "run n8n in tunnel mode" on localhost. For GTMOS this does not
  matter: nothing on the public internet needs to reach the local n8n.
- **`N8N_CONFIG_FILES` removed**; **`QUEUE_WORKER_MAX_STALLED_COUNT` removed**.
- **`N8N_SKIP_AUTH_ON_OAUTH_CALLBACK`** default flips `true` → `false`.
- **dotenv upgraded** from 8.6.0 — backticks must be quoted, `#` starts a comment, multiline
  values now supported.
- **`update:workflow` CLI deprecated** in favour of `publish:workflow` / `unpublish:workflow`.

---

## 2. Reaching the host from inside the container (macOS / Docker Desktop)

Docker Desktop provides two special DNS names, documented on
[Docker Desktop networking how-tos](https://docs.docker.com/desktop/features/networking/networking-how-tos/):

| Name | Resolves to |
|---|---|
| `host.docker.internal` | the internal IP address of your host |
| `gateway.docker.internal` | the gateway IP of the Docker VM |

The docs' own example is a Python HTTP server on host port 8000 reached from an Alpine
container with `curl http://host.docker.internal:8000`.

So an n8n HTTP Request node targeting a FastAPI service on the Mac host at port 8010 uses:

```
http://host.docker.internal:8010
```

**Linux caveat.** `host.docker.internal` is a Docker Desktop convenience. On plain Docker
Engine you must map it yourself: the daemon "supports a special `host-gateway` value for the
`--add-host` flag for the `docker run` and `docker build` commands", which resolves
`host.docker.internal` to the host's gateway IP
([docker buildx build reference](https://docs.docker.com/reference/cli/docker/buildx/build/)).
In Compose that is:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Adding it on macOS is harmless and makes the compose file portable.

**If both n8n and the API run in the same Compose project**, prefer the service name
(`http://api:8000`) over `host.docker.internal` — no host round trip, no port publishing needed.

---

## 3. Workflow JSON

### 3.1 Shape

An exported workflow is a single JSON object. The authoritative field list is the public API's
OpenAPI schema, embedded in
[connect/n8n-api/workflow](https://docs.n8n.io/connect/n8n-api/workflow.md):

| Key | Type | Notes |
|---|---|---|
| `name` | string | Workflow name |
| `nodes` | array | The nodes (see below) |
| `connections` | object | "Connections between nodes, **keyed by source node name**" |
| `settings` | object | Execution/behaviour settings (see §7) |
| `pinData` | object, nullable | "Pinned sample data for nodes, keyed by node name" |
| `staticData` | string \| object \| null | "Data the workflow keeps between executions" |
| `meta` | object, **readOnly** | `onboardingId`, `templateId`, `instanceId`, `templateCredsSetupCompleted` |
| `versionId` | string, **readOnly** | "Current version identifier used for optimistic locking" |
| `versionCounter` | number | Monotonic version counter |
| `active` / `activeVersionId` | boolean / string | **readOnly** on create |
| `isArchived` | boolean, readOnly | 2.x archive state |
| `triggerCount` | integer, readOnly | "Number of active trigger nodes" |
| `nodeGroups` | array | Canvas frames: `{id, name, description?, nodeIds[]}` |
| `tags` | array | Tags |

Node object properties (exact names, from the same schema):

```
id, name, type, typeVersion, position, parameters, credentials,
disabled, notes, notesInFlow, webhookId,
executeOnce, alwaysOutputData,
retryOnFail, maxTries, waitBetweenTries,
continueOnFail (deprecated: "use onError instead"), onError,
customTelemetryTags, createdAt (readOnly), updatedAt (readOnly)
```

### 3.2 What is required for a clean import

`POST /api/v1/workflows` declares `required: ["name", "nodes", "connections", "settings"]`.
So a minimal importable workflow is:

```json
{
  "name": "GTMOS — PostHog relay",
  "nodes": [ ... ],
  "connections": { },
  "settings": { }
}
```

Practical rules that follow from the schema and the docs:

- `connections` is keyed by **source node name**, so node `name` values must be unique and must
  match the connection keys exactly. Renaming a node in a hand-edited JSON without updating
  `connections` silently orphans it.
- `id`, `active`, `versionId`, `createdAt`, `updatedAt`, `isArchived`, `triggerCount`, `meta`
  are marked `readOnly` on create — n8n assigns them. Leaving them in an exported file is
  fine; they are ignored or replaced.
- `settings` must be present, even as `{}`.
- Exported JSON **includes credential names and IDs**. n8n's own warning: "While IDs aren't
  sensitive, the names could be… HTTP Request nodes may contain authentication headers when
  imported from cURL. Remove or anonymize this information from the JSON file before sharing."
  ([export and import](https://docs.n8n.io/build/manage-workflows/export-and-import.md))
- Workflow and credential names are limited to **128 characters** ("but SQLite doesn't enforce
  size limits") ([CLI](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md)).

### 3.3 `typeVersion`

`typeVersion` is a number on each node that pins which version of that node type's behaviour
n8n loads. From
[node versioning](https://docs.n8n.io/connect/create-nodes/build-your-node/reference/versioning.md):

> - If a user builds and saves a workflow using version 1, n8n continues to use version 1 in
>   that workflow, even if you create and publish a version 2 of the node.
> - When a user creates a new workflow and browses for nodes, n8n always loads the latest
>   version of the node.

Consequences for hand-maintained workflow JSON:

- A `typeVersion` that is **too low** is safe and stable — you get the old parameter shape,
  forever, and n8n will not silently migrate you.
- A `typeVersion` that is **higher than the installed node supports** is the failure mode to
  worry about; behaviour in that case is **UNCONFIRMED** from the docs.
- Node code accesses it as `this.getNode().typeVersion`, and expressions expose `$nodeVersion`
  ([n8n metadata](https://docs.n8n.io/build/code-in-n8n/use-built-in-shortcuts/n8n-metadata.md)).
- Declarative-style nodes support only "light versioning", not full versioning.

---

## 4. Importing workflows

### 4.1 Routes

Four documented routes ([export and import](https://docs.n8n.io/build/manage-workflows/export-and-import.md)):
copy-paste on the canvas; the editor menu (**Download** / **Import from URL** / **Import from
File**); the **Server CLI**; and the public API / n8n CLI packages (`.n8np`).

Note n8n's current steer: "n8n recommends the [n8n CLI] over the Server CLI export and import
commands for new work. We plan to deprecated Server CLI export and import commands, though this
is not yet scheduled." The n8n CLI needs a **running instance and an API key** — which, on
self-hosted, means the public API, which is not available on a free trial (§9). For a local
pinned container, `import:workflow` is still the pragmatic route.

### 4.2 Server CLI syntax

```bash
n8n import:workflow --input=file.json
n8n import:workflow --separate --input=backups/latest/
```

Flags ([CLI](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md)):

| Flag | Meaning |
|---|---|
| `--input` | File, or directory when used with `--separate` |
| `--separate` | Imports `*.json` files from the directory given by `--input` |
| `--projectId` | Import into a project. Can't be used with `--userId` |
| `--userId` | Import to a user. Can't be used with `--projectId` |
| `--skipMigrationChecks` | Skip migration validation checks |
| `--activeState` | `false` (default, deactivates all imported workflows) or `fromJson` |

### 4.3 In Docker

The documented invocation pattern is:

```sh
docker exec -u node -it <n8n-container-name> <n8n-cli-command>
```

e.g. with the repo's `integrations/n8n` mounted read-only at `/workflows`:

```sh
docker exec -u node -it n8n n8n import:workflow --separate --input=/workflows
```

A one-shot variant that does not need the server up (Server CLI works with "No (most
commands)" — it talks to the database directly):

```sh
docker run --rm -v n8n_data:/home/node/.n8n \
  -v "$PWD/integrations/n8n:/workflows:ro" \
  --entrypoint n8n n8nio/n8n:2.40.5 \
  import:workflow --separate --input=/workflows
```

### 4.4 Does import activate the workflow? No.

Verbatim: "By default, `import:workflow` **deactivates every imported workflow**." The
`--activeState=fromJson` alternative "uses the `active` field from each JSON file" but is
**"only supported in multi-main & queue mode"** — i.e. not in a default single-container local
setup.

To activate, use the 2.x publish commands:

```bash
n8n publish:workflow --id=<ID>                       # publish current draft
n8n publish:workflow --id=<ID> --versionId=<VER_ID>  # publish a historical version
n8n unpublish:workflow --id=<ID>
n8n unpublish:workflow --all
```

`publish:workflow` deliberately has **no `--all`** flag. And critically:

> **Restart required** — These commands operate on your n8n database. If you execute them while
> n8n is running, the changes don't take effect until you restart n8n.

The deprecated `n8n update:workflow --id=<ID> --active=true` still exists but is on the way out.

The API equivalents are `POST /api/v1/workflows/{workflowId}/publish` and `/unpublish`
(`/activate` and `/deactivate` still exist, marked deprecated).

---

## 5. Webhook node

Docs: [Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook.md),
[workflow development](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/workflow-development.md),
[common issues](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/common-issues.md).

### 5.1 Path

Defaults to a random path to avoid collisions; can be set manually. Route parameters are
supported in these forms: `/:variable`, `/path/:variable`, `/:variable/path`,
`/:variable1/path/:variable2`, `/:variable1/:variable2`.

### 5.2 HTTP method

One of `DELETE`, `GET`, `HEAD`, `PATCH`, `POST`, `PUT`. One method per node by default; turn on
**Allow Multiple HTTP Methods** in the node **Settings** to accept several — the node then gets
**one output per method**.

**Max payload: 16 MB**, configurable when self-hosting via `N8N_PAYLOAD_SIZE_MAX`.

### 5.3 Response modes

The UI labels and the underlying JSON values:

| UI label | JSON `responseMode` | Behaviour |
|---|---|---|
| Immediately | `onReceived` | Returns the response code and the message **"Workflow got started"** |
| When Last Node Finishes | `lastNode` | Returns the data output from the last node executed |
| Using 'Respond to Webhook' Node | `responseNode` | Response is defined by the [Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook.md) node |
| Streaming response | streaming | Real-time streaming; needs streaming-capable nodes (e.g. AI Agent) |

The docs page gives only the UI labels. The JSON values are confirmed from the node's source
([`packages/nodes-base/nodes/Webhook/description.ts`](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/Webhook/description.ts)),
where `responseModeOptions` maps Immediately → `onReceived`, When Last Node Finishes →
`lastNode`, Using 'Respond to Webhook' Node → `responseNode`, plus `streaming`. The parameter
is `responseMode` and its **default is `onReceived`**. `responseCode` is hidden when
`responseMode` is `responseNode`.

With `lastNode`, **Response Data** selects the body: *All Entries* (array), *First Entry JSON*,
*First Entry Binary*, *No Response Body*. **Response Code** is customisable for every mode
except `responseNode`.

### 5.4 Test vs production URL — the thing that trips people up

Every Webhook node has two URLs:

| | Path prefix | Registered when | Data visible in editor |
|---|---|---|---|
| Test | `/webhook-test/<path>` | you click **Listen for Test Event** (or Execute workflow, if unpublished) | yes |
| Production | `/webhook/<path>` | you **publish** the workflow | no — view it under the **Executions** tab |

The prefixes come from `N8N_ENDPOINT_WEBHOOK` (`webhook`) and `N8N_ENDPOINT_WEBHOOK_TEST`
(`webhook-test`)
([endpoints](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/endpoints.md)).

Why it trips people: **the test webhook is only live for 120 seconds** after you press *Listen
for test event* — "The test webhook stays active for 120 seconds"
([workflow development](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/workflow-development.md)).
Outside that window `/webhook-test/...` 404s. And `/webhook/...` 404s until the workflow is
published — which, because import always imports deactivated (§4.4), is the default state of a
freshly imported workflow. The two failure modes look identical from curl and are the single
most common "my n8n webhook doesn't work" cause. Documentation and scripts should always state
which of the two prefixes they mean.

`N8N_WEBHOOK_URL` sets the base for **both** test and production URLs at once.

### 5.5 Raw body and headers

- **Raw Body** (node option): "Specify that the Webhook node will receive data in a raw format,
  such as JSON or XML." Available for any node configuration.
- **Binary Property** (node option): receive binary uploads; requires POST/PATCH/PUT.
- The incoming request is exposed to expressions as `$json` with the shape
  **`{ body, headers, params, query }`** — stated explicitly in the **Only Run If** option's
  documentation ("Use `$json` to access the request as `{ body, headers, params, query }`").
  So a header is `{{ $json.headers['x-gtmos-webhook-token'] }}`. **Lowercase** header names:
  n8n's HTTP layer lowercases header keys by default.
- **Only Run If** is worth knowing for a relay: an expression evaluated before the workflow
  runs; non-matching requests "receive a 200 response without creating an execution", and a
  failing expression logs a warning and **lets the request through** rather than blocking.
  Applies to both test and production URLs, after IP-allowlist and auth checks.

### 5.6 Securing it

Built-in auth methods: **Basic auth, Header auth, JWT auth, None**. Plus node options
**IP(s) Allowlist** (403 outside the list), **Ignore Bots**, **Allowed Origins (CORS)** (default
`*`).

From n8n 1.103.0, HTML responses to webhooks are automatically wrapped in a sandboxed
`<iframe>`; relative URLs and top-level-window JavaScript stop working inside them.

---

## 6. HTTP Request node

Docs: [HTTP Request](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest.md).

### 6.1 Authentication

Methods: `DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT`.

Two authentication families:

- **Predefined Credential Type** — reuses the credential of any built-in or community node;
  recommended by n8n where available.
- **Generic credentials** — Basic auth, Custom auth, Digest auth, **Header auth**, OAuth1 API,
  OAuth2 API, Query auth, Simplified Custom Auth.

For GTMOS's own bearer/HMAC scheme, **Header auth** (generic) is the right fit — it keeps the
secret in the credential store rather than in the workflow JSON.

### 6.2 Custom headers

**Send Headers** → either *Using Fields Below* (name/value pairs) or *Using JSON*. Body has
content types: Form URLencoded, Form-Data, JSON, n8n Binary File, Raw (with explicit
`Content-Type`).

Relevant option: **Lowercase Headers** — "Choose whether to lowercase header names (turned on,
default) or not."

### 6.3 Timeout

Node option **Timeout**, in **milliseconds**: "how long the node should wait for the server to
send response headers (and start the response body). The node aborts requests that exceed this
value for the initial response." Note the precise semantics — it is a *headers/first-byte*
timeout, not a total-request budget. The docs do not state a default; the node source sets
**300 000 ms (5 minutes)** when the option is unset
([`HttpRequestV3.node.ts`](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/HttpRequest/V3/HttpRequestV3.node.ts):
`// set default timeout to 5 minutes` / `requestOptions.timeout = 300_000;`). For a call into a
local FastAPI service, set this explicitly to something like 10 000 ms — 5 minutes of hanging is
not a useful failure mode.

### 6.4 Reading a non-2xx response body

Two node options under **Response**:

- **Never Error**: "By default, the node returns success only when the response returns with a
  2xx code. Turn this option on to return success regardless of the code returned." This is how
  you get the body of a 4xx/5xx instead of a thrown node error.
- **Include Response Headers and Status**: "By default, the node returns only the body. Turn
  this option on to return the full response (headers and response status code) as well."

Turn on **both** to branch on `statusCode` and read the error body — the standard pattern for
calling an API that returns structured errors (e.g. FastAPI's `{"detail": ...}` on 422).

**Response Format**: Autodetect (default) / File / JSON / Text.

Other useful options: **Batching** (*Items per Batch*, *Batch Interval* in ms), **Pagination**
(`$pageCount`, `$request`, `$response` with `$response.body`, `$response.headers`,
`$response.statusCode`), **Redirects** / *Max Redirects*, **Ignore SSL Issues**, **Proxy**
(overrides `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`), **Array Format in Query Parameters**.

### 6.5 Retry and error settings (node-level, any node)

These live on the **Settings** tab of every node
([work with nodes](https://docs.n8n.io/build/understand-workflows/workflow-components/work-with-nodes.md)):

| Setting | JSON field | Documented behaviour |
|---|---|---|
| Always Output Data | `alwaysOutputData` | Node returns an empty item even when it produced no data |
| Execute Once | `executeOnce` | Node runs once, using the first input item only |
| Retry On Fail | `retryOnFail` | "When an execution fails, the node reruns until it succeeds" |
| Max Tries | `maxTries` | number |
| Wait Between Tries | `waitBetweenTries` | milliseconds |
| On Error | `onError` | Stop Workflow / Continue / Continue (using error output) |

The current docs pages do **not** publish the numeric defaults or clamps for `maxTries` /
`waitBetweenTries`. They are in the engine source
([`packages/core/src/execution-engine/workflow-execute.ts`](https://github.com/n8n-io/n8n/blob/master/packages/core/src/execution-engine/workflow-execute.ts),
`getRetryParams`):

```ts
return [
    Math.min(5, Math.max(2, executionData.node.maxTries || 3)),
    Math.min(5000, Math.max(0, executionData.node.waitBetweenTries || 1000)),
];
```

So: **`maxTries` defaults to 3 and is clamped to [2, 5]; `waitBetweenTries` defaults to 1000 ms
and is clamped to [0, 5000] ms.** Setting `maxTries: 10` gives you 5. Setting
`waitBetweenTries: 30000` gives you 5 s. There is no exponential backoff, and no jitter — the
engine sleeps a fixed `waitBetweenTries` between attempts. A node resuming from a sub-workflow
error is deliberately excluded from retries.

### 6.6 `continueOnFail` vs `onError`

`continueOnFail` (boolean) is **deprecated in the public API schema**, annotated verbatim
`"use onError instead"` and `deprecated: true`
([workflow schema](https://docs.n8n.io/connect/n8n-api/workflow.md)). Current field is
`onError`, a string with the three documented behaviours:

| UI | `onError` value | Effect |
|---|---|---|
| Stop Workflow | `stopWorkflow` | "Halts the entire workflow when an error occurs, preventing further node execution." |
| Continue | `continueRegularOutput` | "Proceeds to the next node despite the error, using the last valid data." |
| Continue (using error output) | `continueErrorOutput` | "Continues workflow execution, passing error information to the next node" — adds a second, error output branch on the node |

The enum strings are not printed in the current docs, but are declared in the source
([`packages/workflow/src/interfaces.ts`](https://github.com/n8n-io/n8n/blob/master/packages/workflow/src/interfaces.ts)):

```ts
export type OnError = 'continueErrorOutput' | 'continueRegularOutput' | 'stopWorkflow';
```

mapping to Continue (using error output) / Continue / Stop Workflow respectively. In
`continueErrorOutput` mode "engine will try to read `item.error` or fallback to
`item.json.error` with allowed optional keys: message, details."

---

## 7. Error handling

### 7.1 Attaching an error workflow

Per-workflow, in **Workflow Settings → Error Workflow (to notify when this one errors)**
([configure workflow settings](https://docs.n8n.io/build/manage-workflows/configure-workflow-settings.md)).
In workflow JSON this is `settings.errorWorkflow`, documented in the API schema as "The ID of
the workflow that contains the error trigger node."

Procedure ([handle errors gracefully](https://docs.n8n.io/build/flow-logic/handle-errors-gracefully.md)):
create a workflow whose first node is the **Error Trigger**, save it, then select it in the
other workflow's settings. One error workflow can serve many workflows.

Three facts from [Error Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.errortrigger.md):

- "If a workflow uses the Error Trigger node, you don't have to publish the workflow."
- "If a workflow contains the Error Trigger node, by default, the workflow uses itself as the
  error workflow."
- "You can't test error workflows when running workflows manually. The Error Trigger only runs
  when an automatic workflow errors." — so you must publish and trigger for real to test.

Error workflow runs **do not count** towards paid-plan execution quotas
([understand executions](https://docs.n8n.io/build/understand-workflows/understand-executions.md)).

### 7.2 What the Error Trigger receives

```json
[
  {
    "execution": {
      "id": "231",
      "url": "https://n8n.example.com/execution/231",
      "retryOf": "34",
      "error": { "message": "Example Error Message", "stack": "Stacktrace" },
      "lastNodeExecuted": "Node With Error",
      "mode": "manual"
    },
    "workflow": { "id": "1", "name": "Example Workflow" }
  }
]
```

Always present except: `execution.id` and `execution.url` (need the execution to be saved in the
DB; absent if the error is in the main workflow's trigger node, since the workflow never
executes), and `execution.retryOf` (only on retries).

If the failure is in the **trigger** node, the payload is different — less `execution{}`, more
`trigger{}`:

```json
{
  "trigger": {
    "error": { "context": {}, "name": "WorkflowActivationError",
               "cause": {"message": "", "stack": ""},
               "timestamp": 1654609328787, "message": "", "node": { } },
    "mode": "trigger"
  },
  "workflow": { "id": "", "name": "" }
}
```

Use the [Stop And Error](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.stopanderror.md)
node to fail deliberately and send a custom message to the Error Trigger.

### 7.3 `$execution` and execution metadata in expressions

From [n8n metadata](https://docs.n8n.io/build/code-in-n8n/use-built-in-shortcuts/n8n-metadata.md)
and [execution cookbook](https://docs.n8n.io/build/code-in-n8n/cookbook/built-in-methods-and-variables-examples/execution.md):

| Expression | Meaning |
|---|---|
| `$execution.id` | Unique ID of the current execution |
| `$execution.mode` | `test` or `production` |
| `$execution.resumeUrl` | Webhook URL to resume a workflow waiting at a Wait node |
| `$execution.customData.set/setAll/get/getAll` | Custom execution data — **Code node only** |
| `$getWorkflowStaticData(type)` | Static workflow data; does not persist in test runs — publish and trigger to persist |
| `$nodeVersion` | `typeVersion` of the current node |
| `$("<node-name>").isExecuted` | Whether a node already ran |
| `$itemIndex` | Index of an item (not available in Code node) |

`$execution.customData` is searchable: you can filter executions by the custom data you set
([customize executions data](https://docs.n8n.io/build/understand-workflows/understand-executions/customize-executions-data.md)).
For a GTMOS relay this is the cheapest way to make a run findable by account domain.

### 7.4 Relevant `settings.*` keys

From the API workflow schema: `errorWorkflow`, `timezone`, `executionOrder`, `executionTimeout`,
`saveExecutionProgress`, `saveManualExecutions`, `saveDataErrorExecution`
(`DEFAULT`/`all`/`none`), `saveDataSuccessExecution` (same enum), `callerPolicy`
(`any`/`none`/`workflowsFromAList`/`workflowsFromSameOwner`, default the last),
`callerIds`, `redactionPolicy` (`none`/`non-manual`/`manual-only`/`all`),
`availableInMCP`, `timeSavedMode`, `timeSavedPerExecution`, `customTelemetryTags`.

---

## 8. Credentials

### 8.1 Storage and encryption

Credentials are "securely stored authentication information"
([create and edit credentials](https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials.md))
held **in the n8n database**, encrypted at rest.

> n8n creates a random encryption key automatically on the first launch and saves it in the
> `~/.n8n` folder. n8n uses that key to encrypt the credentials before they get saved to the
> database. If the key isn't yet in the settings file, you can set it using an environment
> variable, so that n8n uses your custom key instead of generating a new one.
> — [set a custom encryption key](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/configuration-examples/set-a-custom-encryption-key.md)

```bash
export N8N_ENCRYPTION_KEY=<SOME RANDOM STRING>
```

In queue mode the same key must be set on **all workers**. Practical consequence for Docker:
if you do not set `N8N_ENCRYPTION_KEY` and you lose the `/home/node/.n8n` volume, every stored
credential becomes unrecoverable. Set it explicitly and keep it out of the repo.

Key rotation exists from 2.x behind `N8N_ENV_FEAT_ENCRYPTION_KEY_ROTATION=true` — "One-way
change: take a full database backup first"
([rotate encryption keys](https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/rotate-encryption-keys.md)).

### 8.2 Export / import, and the security implication

Yes, both, via the Server CLI:

```bash
n8n export:credentials --all
n8n export:credentials --id=<ID> --output=file.json
n8n export:credentials --backup --output=backups/latest/
n8n export:credentials --all --decrypted --output=backups/decrypted.json
n8n import:credentials --input=file.json
n8n import:credentials --separate --input=backups/latest/
```

Default export keeps values encrypted — which means they are only importable into an instance
with the **same** `N8N_ENCRYPTION_KEY`. `--decrypted` exists precisely "to migrate from one
installation to another that has a different secret key", and carries n8n's own warning:

> **Sensitive information** — All sensitive information is visible in the files.

So `--decrypted` writes plaintext API keys and passwords to disk. Never run it into a repo
working tree, never into a directory covered by a bind mount you might commit, and delete the
output after use. ([CLI](https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md))

Separately: workflow exports embed credential **names and IDs** (not secrets) — see §3.2.

The public API also exposes credentials (§9), including
`GET /api/v1/credentials/schema/{credentialTypeName}`, which is the clean way to discover the
field names a credential type expects.

---

## 9. The public REST API

Docs: [n8n API](https://docs.n8n.io/connect/n8n-api.md),
[authentication](https://docs.n8n.io/connect/n8n-api/authentication.md),
[endpoint reference](https://docs.n8n.io/connect/n8n-api/api-reference.md).

### 9.1 Licensing gate — read this first

> **Feature availability** — The n8n API isn't available during the free trial. Please upgrade
> to access this feature.

That banner appears on both the API overview and the authentication page. It is phrased around
**trial**, not around self-hosted Community — whether a self-hosted Community instance with no
licence can mint an API key in 2.40.5 is **UNCONFIRMED** from the docs. Plan the GTMOS
integration so the public API is optional; the Server CLI needs no licence and no API key.

Two further gates that *are* explicit:

- **API key scopes are Enterprise-only**: "On Enterprise instances, you can limit which
  resources and actions an API key can access with scopes… Non-Enterprise API keys have **full
  access to all the account's resources and capabilities**." An API key on a non-Enterprise
  instance is, effectively, root.
- The API can be switched off entirely
  ([disable the public API](https://docs.n8n.io/deploy/host-n8n/configure-n8n/security/disable-the-public-api.md)).

### 9.2 Base path and auth

Base path: **`/api/v1`**. The OpenAPI `servers` block lists
`/api/v1` and `{url}/api/v1`. Spec title/version: `n8n Public API`, `1.1.1`.

Auth header: **`X-N8N-API-KEY`**. Created in **Settings → n8n API** with a label and an
expiration.

```shell
curl -X 'GET' \
 '<N8N_HOST>:<N8N_PORT>/<N8N_PATH>/api/v<version-number>/workflows?active=true' \
 -H 'accept: application/json' \
 -H 'X-N8N-API-KEY: <your-api-key>'
```

Locally that is `http://localhost:5678/api/v1/...`. Self-hosted instances also ship a built-in
API playground ([use an API playground](https://docs.n8n.io/connect/n8n-api/use-an-api-playground.md)).
Results are paginated ([pagination](https://docs.n8n.io/connect/n8n-api/pagination.md)).

### 9.3 Workflow endpoints

| Method | Path |
|---|---|
| GET | `/api/v1/workflows` |
| POST | `/api/v1/workflows` |
| GET | `/api/v1/workflows/{workflowId}` |
| PUT | `/api/v1/workflows/{workflowId}` |
| DELETE | `/api/v1/workflows/{workflowId}` |
| POST | `/api/v1/workflows/{workflowId}/publish` |
| POST | `/api/v1/workflows/{workflowId}/unpublish` |
| POST | `/api/v1/workflows/{workflowId}/activate` *(deprecated → `/publish`)* |
| POST | `/api/v1/workflows/{workflowId}/deactivate` *(deprecated → `/unpublish`)* |
| POST | `/api/v1/workflows/{workflowId}/archive` |
| POST | `/api/v1/workflows/{workflowId}/unarchive` |
| PUT | `/api/v1/workflows/{workflowId}/transfer` |
| GET | `/api/v1/workflows/{workflowId}/history` |
| GET | `/api/v1/workflows/{workflowId}/versions/{workflowVersionId}` |
| GET | `/api/v1/workflows/{id}/{versionId}` *(deprecated → `/versions/...`)* |
| GET / PUT | `/api/v1/workflows/{workflowId}/tags` |

`versionId` on the workflow object is "used for optimistic locking" — a `PUT` that carries a
stale `versionId` is the mechanism that stops two writers clobbering each other.

### 9.4 Execution endpoints

| Method | Path |
|---|---|
| GET | `/api/v1/executions` |
| GET | `/api/v1/executions/{executionId}` |
| DELETE | `/api/v1/executions/{executionId}` |
| POST | `/api/v1/executions/{executionId}/retry` |
| POST | `/api/v1/executions/{executionId}/stop` |
| POST | `/api/v1/executions/stop` |
| GET / PUT | `/api/v1/executions/{executionId}/tags` |

### 9.5 Credential endpoints

`GET|POST /api/v1/credentials`, `GET|PATCH|DELETE /api/v1/credentials/{credentialId}`,
`POST /api/v1/credentials/{credentialId}/test`,
`PUT /api/v1/credentials/{credentialId}/transfer`,
`GET /api/v1/credentials/schema/{credentialTypeName}`.

Other resource groups in `/api/v1`: audit, projects, folders, users, roles, variables, tags,
data tables, evaluation, insights, log streaming, source control, n8n packages, community
packages, promotions, node type policy
([endpoint reference](https://docs.n8n.io/connect/n8n-api/api-reference.md)).

---

## 10. Executions

### 10.1 Where they are stored

In the n8n database. `N8N_EXECUTION_DATA_STORAGE_MODE` (default **`database`**) also allows
`filesystem`, `s3`, `azure`; **`s3` and `azure` require a self-hosted Business or Enterprise
plan**. Filesystem mode writes under `N8N_STORAGE_PATH` (default `N8N_USER_FOLDER/storage`).
([executions env vars](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/executions.md))

Whether an execution is stored at all is controlled instance-wide by
`EXECUTIONS_DATA_SAVE_ON_ERROR` / `_ON_SUCCESS` (`all` | `none`, both default `all`),
`EXECUTIONS_DATA_SAVE_ON_PROGRESS` (default `false`) and
`EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS` (default `true`) — and per workflow by the equivalent
**Workflow Settings** toggles (`settings.saveDataErrorExecution` etc., §7.4).

### 10.2 Pruning

| Variable | Default | Meaning |
|---|---|---|
| `EXECUTIONS_DATA_PRUNE` | `true` | Delete past execution data on a rolling basis |
| `EXECUTIONS_DATA_MAX_AGE` | `336` | Age in **hours** before deletion (= 14 days) |
| `EXECUTIONS_DATA_PRUNE_MAX_COUNT` | `10000` | Max executions kept; `0` = no limit |
| `EXECUTIONS_DATA_HARD_DELETE_BUFFER` | `1` | Hours a finished execution must age before hard delete |
| `EXECUTIONS_DATA_PRUNE_HARD_DELETE_INTERVAL` | `15` | Minutes between hard deletes |
| `EXECUTIONS_DATA_PRUNE_SOFT_DELETE_INTERVAL` | `60` | Minutes between soft deletes |
| `EXECUTIONS_DATA_MAX_DISPLAY_SIZE` | `104857600` | Bytes (100 MB); larger executions have data omitted in the editor, execution detail **and public API** |

Pruning is on by default, so a demo run older than 14 days will have vanished. If a recording
must survive, export it or raise `EXECUTIONS_DATA_MAX_AGE`.

Related: `EXECUTIONS_TIMEOUT` (default `-1`, seconds), `EXECUTIONS_TIMEOUT_MAX` (`3600`),
`EXECUTIONS_MODE` (`regular` | `queue`), `N8N_CONCURRENCY_PRODUCTION_LIMIT` (`-1`),
`N8N_WORKFLOW_AUTODEACTIVATION_ENABLED` (`false`, unpublishes a workflow after
`N8N_WORKFLOW_AUTODEACTIVATION_MAX_LAST_EXECUTIONS` = `3` crashed executions).

### 10.3 Inspecting a failed run

- **Executions** tab inside a workflow, or the global **all executions** list — filter by
  status, workflow, and by custom `$execution.customData`
  ([view all executions](https://docs.n8n.io/build/understand-workflows/understand-executions/view-all-executions.md),
  [customize executions data](https://docs.n8n.io/build/understand-workflows/understand-executions/customize-executions-data.md)).
- **Debug in editor**: copy a past execution's data back onto the canvas to re-run it
  ([debug executions](https://docs.n8n.io/build/understand-workflows/understand-executions/debug-executions.md)).
- **`POST /api/v1/executions/{executionId}/retry`** re-runs it; the retry's Error Trigger
  payload then carries `execution.retryOf`.
- **Log streaming** to an external system
  ([stream logs](https://docs.n8n.io/administer/observe-and-log/stream-logs-to-external-systems.md)),
  and OpenTelemetry tracing
  ([trace executions](https://docs.n8n.io/deploy/host-n8n/keep-n8n-running/trace-executions-with-opentelemetry.md)).
- Production webhook runs show **nothing in the editor** — the Executions tab is the only view.

### 10.4 Quota counting (paid plans)

Only **production** executions count. Manual runs, sub-workflow executions (only the top-level
parent counts), error-workflow runs, polls that return no data, and malformed requests rejected
before the workflow starts do **not** count. A webhook counts once per inbound request that
activates the trigger, including an empty `{}` body.
([understand executions](https://docs.n8n.io/build/understand-workflows/understand-executions.md))

---

## 11. Gotchas that will bite this integration

1. **Import never activates.** `import:workflow` always deactivates; `--activeState=fromJson`
   needs multi-main/queue mode. Publish explicitly, then **restart the container** — CLI
   publish writes to the DB and a running n8n will not notice.
2. **`/webhook-test/` expires after 120 s** and `/webhook/` 404s until published. Always say
   which prefix a runbook means.
3. **`WEBHOOK_URL` is deprecated from 2.35.0.** Use `N8N_WEBHOOK_URL`; the old name still works
   but logs a startup deprecation warning.
4. **`N8N_RUNNERS_ENABLED` is deprecated from 2.0** and no longer needed. Setting it does not
   "silence a deprecation warning" — it is the setting that *is* deprecated.
5. **`N8N_SECURE_COOKIE=true` is the default**; on `http://localhost` you must set it to
   `false` or login fails.
6. **`N8N_ENCRYPTION_KEY`**: set it, or losing the volume loses every credential.
7. **Retry clamps**: `maxTries` ∈ [2,5] (default 3), `waitBetweenTries` ∈ [0,5000] ms
   (default 1000). Fixed delay, no backoff.
8. **`continueOnFail` is deprecated** in favour of `onError`
   (`stopWorkflow` / `continueRegularOutput` / `continueErrorOutput`).
9. **Executions prune at 14 days** by default.
10. **The public API is gated** ("isn't available during the free trial") and, off Enterprise,
    an API key has full account access.
11. **`export:credentials --decrypted` writes plaintext secrets to disk.**
12. **`N8N_BLOCK_ENV_ACCESS_IN_NODE` default is documented inconsistently** (§1.3) — set it
    explicitly.
