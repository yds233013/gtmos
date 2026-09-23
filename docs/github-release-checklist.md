# GitHub release checklist

A pre-flight list for making this repository public, ordered so that nothing irreversible happens
before the thing that would have changed it.

Two items are irreversible and they are the reason for the ordering: **rewriting history** must happen
before the first push or not at all, and **making the repository public** publishes every commit,
every author email and every blob in the pack to anyone who clones it, including blobs no current file
points at. Everything else can be undone.

Each item is marked **[automatable]**, with the exact command, or **[needs you]** for the things that
only happen in a browser. Commands assume the repository root.

The release commands themselves are in §9. **They have not been run.**

---

## 1 · Decide before you type anything

### 1.1 Commit identity · [needs you]

- [ ] Read [`git-identity-review.md`](git-identity-review.md) and act on its recommendation.

That document settles the question and this one will not repeat it. The single thing to take from it
here: **it must be resolved before the push, not after**, because the only remedy that does not depend
on a GitHub account setting is a history rewrite, and a rewrite after publication changes every SHA in
a history other people may already have.

The tooling agrees with its conclusion — `gh auth status` reports `yds233013` as the active account,
and `git-filter-repo` is installed locally should the rewrite path ever be needed.

### 1.2 Repository weight · [automatable] · **decide before the first push**

```bash
git count-objects -vH | grep size-pack
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob" && $4 ~ /screenshots/ {s+=$3; n++} END {print n, "blob versions,", s, "bytes"}'
```

- [ ] Accept the clone size, or shrink it now.

Measured today: `.git` is **61 MB**, of which **60.3 MB is 84 versions of eighteen screenshots** that
have been recaptured several times. The working tree's current screenshots are 7.3 MB. Every clone
pulls all 84 versions forever.

61 MB is not a problem — it is a fifteen-second clone. But it is the kind of thing that can only be
fixed with `git filter-repo`, and only before the push. If it is going to be accepted, accept it
deliberately here and stop thinking about it. If the screenshots should live outside git history
instead, that decision belongs now, in the same breath as §1.1, since both are history rewrites and
should be one operation if they happen at all.

### 1.3 Branch name · [automatable]

```bash
git branch --show-current
```

- [ ] Confirm `main`.

Currently `main`, which matches GitHub's default and needs no change. Renaming after the push means
re-pointing the default branch in settings and breaking any link that already used the old name.

---

## 2 · Clean the working tree

### 2.1 `git status` · [automatable]

```bash
git status --short
git stash list
```

- [ ] Working tree clean, nothing stashed that should have been committed.

Currently **`M README.md`** — an uncommitted 315-insertion, 369-deletion rewrite. That is not a stray
edit; it is a substantial change that needs to be reviewed and committed or discarded before anything
else in this list is meaningful, because §3 and §4 are checks *of the README*.

### 2.2 No secrets or local files are tracked · [automatable]

```bash
git ls-files --error-unmatch .env 2>&1   # must report "did not match"
git check-ignore -v .env
git ls-files | grep -iE '\.env$|\.pem$|\.key$|/node_modules/|/\.next/|target/|test-results/'
```

- [ ] `.env` untracked and ignored; nothing from the last line.

Verified clean today: `.env` is not known to git, and the `.gitignore` covers `.env*`, `*.pem`,
`*.key`, `node_modules/`, `.next/`, `warehouse/target/` and `test-results/`.

### 2.3 No machine-specific paths · [automatable]

```bash
git grep -nI '/Users/\|/home/[a-z]' -- . | grep -v '<user>'
```

- [ ] No output.

Verified clean today. The one remaining `/Users/` string is the deliberately generalised
`/Users/<user>/gtmos` placeholder in `phase4-baseline.md`.

---

## 3 · README state

### 3.1 Every relative link resolves · [automatable]

```bash
grep -oE '\]\(([a-zA-Z0-9._/-]+)\)' README.md | sed -E 's/^\]\(//;s/\)$//' \
  | sort -u | while read -r p; do [ -e "$p" ] || echo "MISSING: $p"; done
```

- [ ] No output.

**This currently fails.** The uncommitted README rewrite adds links to five documents that do not
exist:

```
docs/60-second-demo.md
docs/gtmos-course.md
docs/interview-drill.md
docs/portfolio-demo-script.md
docs/technical-demo.md
```

Five dead links in the documentation index of a repository whose stated standard is that a reader
should not discover something the document could have said. Write the documents or remove the links;
do not publish with them. The same check across `docs/*.md` passes, so this is the only instance.

### 3.2 The README says what a visitor needs in the first screen · [needs you]

- [ ] Hero screenshot renders on github.com (relative image paths resolve differently on the rendered
      page than in an editor — check the actual page after §8).
- [ ] The demo-data disclaimer is above the fold. It currently is.
- [ ] The run instructions are correct for someone with nothing installed: `make setup`,
      `make dev-deps`, `make migrate && make seed`, `make dev`.
- [ ] Decide the provenance question raised in §7 of [`phase3-handoff.md`](phase3-handoff.md). It is a
      judgement call, it is flagged there rather than answered, and a reader who opens `git log` will
      form a view whether or not the README offers one.

### 3.3 Claimed numbers match generated files · [automatable]

```bash
make backtest && make docs-numbers && make llm-eval && git diff --stat docs/
```

- [ ] `git diff` is empty, or the prose is corrected to match.

The project's own rule, from `phase3-handoff.md` §4: if prose disagrees with a generated file, the
generated file is right. A review already found four rows of the README's honesty table contradicted
by the running app, three of them flattering. Re-running the generators is the cheap way not to
repeat that.

---

## 4 · LICENSE

### 4.1 [automatable]

```bash
cat LICENSE && head -3 LICENSE
```

- [ ] Present, correct type, correct year and name.

**A LICENSE exists**: MIT, `Copyright (c) 2026 Yash Shah`, full standard text, and the README's final
section points at it. Nothing to do.

MIT is the right choice here and the one-line reason is that a portfolio repository's job is to be
read and reused without anyone having to think about it — MIT is the licence a reader recognises
without reading, which is exactly the property you want on something whose purpose is to make a good
impression in ninety seconds. (If the intent were instead to prevent someone shipping this as their
own product, that is not a licensing problem; no permissive or copyleft licence solves it, and a
non-OSI licence would cost more attention than it buys.)

### 4.2 GitHub detects it · [needs you]

- [ ] After §8, the repository sidebar shows "MIT license" rather than "View license".

GitHub's detector needs the file at the root named `LICENSE` or `LICENSE.md` with unmodified text.
Both hold.

---

## 5 · Screenshots

### 5.1 They exist and are referenced · [automatable]

```bash
ls docs/screenshots/*.png | wc -l
grep -c 'screenshots/' docs/screenshots.md
for f in $(grep -oE 'screenshots/[0-9a-z-]+\.png' docs/screenshots.md README.md | sort -u); do
  [ -e "docs/$f" ] || echo "MISSING: $f"
done
```

- [ ] 18 files, every reference resolves.

### 5.2 They show the current app · [needs you]

- [ ] Every caption in [`screenshots.md`](screenshots.md) describes the image above it.
- [ ] No screenshot contains a real name, a real domain that is not `.example`, a browser tab from
      another site, a local filesystem path in a URL bar, or a devtools panel.
- [ ] The mobile shot (`18-mobile-overview.png`) is still representative.

Captions were recaptured at `3f3e5e4`. If any UI changed since — including anything added by
[`public-demo-safety.md`](public-demo-safety.md) P2, which adds a read-only banner to every page —
**the screenshots are stale and must be recaptured after the deploy, not before.** This is why
screenshots sit after the deployment decision and before the public flip.

---

## 6 · Secret scan

Both scans below were run today and both are clean. They are listed anyway because the thing they
protect against is a commit made between now and the push.

### 6.1 HEAD · [automatable]

```bash
git grep -nIE 'sk-ant-[A-Za-z0-9_-]{20,}|pat-(na|eu)[0-9]?-[0-9a-f-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|phc_[A-Za-z0-9]{40}|-----BEGIN [A-Z ]*PRIVATE KEY-----' HEAD -- .
```

- [ ] No output.

### 6.2 Full history — every blob ever committed · [automatable]

This is the one that matters, because a secret deleted in a later commit is still in the pack and
still published.

```bash
git rev-list --objects --all | awk '{print $1}' \
  | git cat-file --batch-check='%(objectname) %(objecttype) %(rest)' \
  | awk '$2=="blob"{print $1}' \
  | git cat-file --batch \
  | grep -anE 'sk-ant-[A-Za-z0-9_-]{20,}|pat-(na|eu)[0-9]?-[0-9a-f-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|phc_[A-Za-z0-9]{40}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
```

- [ ] No output. (Runs in under a second on this repository; 1,416 objects.)

### 6.3 The local development secrets, by value · [automatable]

Pattern matching does not catch a locally generated random hex string. Search for the actual values:

```bash
grep -hoE '^[A-Z_]+=.+' .env | cut -d= -f2- | while read -r v; do
  [ ${#v} -ge 12 ] || continue
  git rev-list --objects --all | awk '{print $1}' | git cat-file --batch 2>/dev/null \
    | grep -qF "$v" && echo "LEAKED: a value from .env appears in git history"
done
```

- [ ] No output.

Clean today, which is consistent with `.env` having never been tracked.

### 6.4 If any scan hits · [needs you]

- [ ] Rotate the credential **first**, at the provider. Then rewrite history with `git filter-repo`.
      Never in the other order, and never at all after the push — a published secret is a compromised
      secret regardless of what the history says afterwards.

### 6.5 A third-party scanner, optionally · [automatable]

Neither `gitleaks` nor `trufflehog` is installed on this machine, so this is a genuine extra step
rather than a command to paste:

```bash
brew install gitleaks && gitleaks detect --source . --log-opts="--all"
```

- [ ] Optional. The three scans above cover the credential shapes this project could plausibly hold;
      a scanner adds breadth against shapes nobody thought of.

---

## 7 · The final test run

Last, because it is the thing you want green on the exact tree you are about to publish.

### 7.1 [automatable]

```bash
make check          # lint + typecheck + backend suite + frontend suite + next build
make e2e            # 25 Playwright cases, needs a running stack
make warehouse      # 19 dbt models + 113 tests
make golden-flow    # end-to-end scenario, 20 assertions
```

- [ ] All green.

Expected at the last recorded baseline: 465 backend passed (1 deliberate skip), 14 frontend, 25 e2e,
`PASS=132` from dbt (19 models **plus** 113 tests — not a test count), 20/20 golden flow.

**The trap, from `phase3-handoff.md` §5:** the integration suite *skips* rather than fails when
Postgres is unreachable, so a green exit code on a machine with no database proves nothing. Assert the
collected count:

```bash
cd apps/api && uv run pytest --collect-only -q 2>/dev/null | tail -1   # expect 465-ish collected
```

- [ ] Collected count matches, not just the exit code.

### 7.2 CI passes on the pushed tree · [automatable, after §9]

```bash
gh run watch
```

- [ ] `.github/workflows/ci.yml` is green on the first push. It runs ruff, mypy, pytest against a
      Postgres service, an `alembic upgrade head` from an empty schema, and the full frontend build.

---

## 8 · Deployment, and the safety work it depends on

### 8.1 Public-demo safety · [needs you] · **blocking**

- [ ] P0 (environment discipline) and P1 (the `READ_ONLY` edge check) from
      [`public-demo-safety.md`](public-demo-safety.md) are both in force **on the deployed instance**.
- [ ] **[automatable]** `apps/api/tests/integration/test_read_only.py` is green — eight cases,
      including one asserting the flag is off by default:
      `cd apps/api && uv run pytest tests/integration/test_read_only.py -q`

Non-negotiable before a URL goes in the repository description, because **24 mutating endpoints have
no route-level gate** in the best configuration the decorators support. P1's middleware is the only
thing standing between those and a stranger with `curl`. A link on a public README to an instance
anyone can vandalise is worse than no link.

### 8.2 Deploy · [needs you]

- [ ] Follow [`deployment-plan.md`](deployment-plan.md). Deploy from the **private** repository
      (§9 step 1) so the instance exists and is verified before anything is public.

### 8.3 Verify the deployed instance · [automatable]

```bash
DEMO=https://<your-demo-host>
curl -s "$DEMO/health/ready"                                  # {"status":"ok","checks":{"database":"ok"},...}
curl -s "$DEMO/api/v1/workspace" | grep -o '"llm_mode":"[a-z]*"'       # must be "demo"
curl -s "$DEMO/api/v1/workspace" | grep -o '"hubspot_mode":"[a-z]*"'   # must be "demo"
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$DEMO/api/v1/data-quality/scan"   # must be 403
curl -s -o /dev/null -w '%{http_code}\n' -X PUT  "$DEMO/api/v1/icp" -d '{}'         # must be 401 or 403
```

- [ ] Health is `ok`, both modes are `demo`, and both mutating probes are refused.

The health endpoint is **`/health/ready`** — not `/health`, which does not exist. `/health/live` is the
liveness probe and does not touch the database.

- [ ] Every page loads. The three that carry the argument:
      `/integrations`, `/experiments/provocative-subject`, `/`.
- [ ] Recapture screenshots if the UI changed (§5.2).

---

## 9 · The release itself

> ## ⚠ NOT YET RUN — REQUIRES EXPLICIT AUTHORISATION
>
> **Nothing in this section has been executed.** No remote exists (`git remote -v` is empty), no
> repository has been created, nothing has been pushed. Step 1 creates a repository on GitHub and
> step 2 publishes 69 commits and every blob in a 61 MB pack. Step 6 makes all of it world-readable.
>
> Do not run any of it until §1 through §8 are ticked, and run it only on an explicit instruction to
> release.

The sequence deliberately creates the repository **private** and flips it public last, so the
irreversible step comes after the deployment has been verified.

```bash
# ── 0 · Confirm the active GitHub account and the local identity ───────────────────────────────
gh auth status
git config user.name && git config user.email
# Expect the account and the commit email that §1.1 settled on. Stop if they disagree.

# ── 1 · Create the remote, PRIVATE, and wire it up ─────────────────────────────────────────────
gh repo create gtmos \
  --private \
  --source=. \
  --remote=origin \
  --description "An AI-native revenue engine: explainable ICP scoring, enrichment waterfalls, signal detection, evidence-grounded outreach drafts for human approval, CRM sync and GTM analytics. FastAPI + Next.js + dbt, with a deterministic synthetic dataset. No message is ever sent."

# ── 2 · Push ───────────────────────────────────────────────────────────────────────────────────
git push -u origin main

# ── 3 · Watch CI go green before anyone can see it ─────────────────────────────────────────────
gh run watch

# ── 4 · Deploy from the private repository, then verify it (§8.3) ──────────────────────────────
#       Nothing to paste here; deployment-plan.md has the steps.

# ── 5 · Topics and homepage, while still private ───────────────────────────────────────────────
gh repo edit --add-topic gtm-engineering
gh repo edit --add-topic revenue-operations
gh repo edit --add-topic sales-engineering
gh repo edit --add-topic lead-scoring
gh repo edit --add-topic fastapi
gh repo edit --add-topic nextjs
gh repo edit --add-topic dbt
gh repo edit --add-topic postgresql
gh repo edit --add-topic sqlalchemy
gh repo edit --add-topic n8n
gh repo edit --add-topic hubspot
gh repo edit --add-topic python
gh repo edit --add-topic typescript
gh repo edit --add-topic portfolio-project

gh repo edit --homepage "https://<your-demo-host>"

# ── 6 · THE IRREVERSIBLE STEP · make it public ─────────────────────────────────────────────────
gh repo edit --visibility public --accept-visibility-change-consequences

# ── 7 · Confirm what the world now sees ────────────────────────────────────────────────────────
gh repo view --json name,visibility,description,homepageUrl,licenseInfo,repositoryTopics
```

Notes on the above, because two of them are easy to get wrong:

- `gh repo create --source=.` adds the remote itself. Do not also run `git remote add origin …`, or the
  push in step 2 fails on a duplicate remote.
- `--add-topic` takes one topic per invocation in current `gh`. Topics must be lowercase with hyphens;
  GitHub allows twenty. **Unverified:** whether the version of `gh` in use accepts a comma-separated
  list — the one-per-call form above works on every version and costs nothing.
- `--accept-visibility-change-consequences` is required for a non-interactive visibility change. It is
  a deliberate friction and it is there for the reason described at the top of this document.

---

## 10 · After the release

- [ ] **[needs you]** Pin the repository on the GitHub profile.
- [ ] **[needs you]** Add the demo URL and the repository link to the CV, and check that the CV's
      claims match [`resume.md`](resume.md) and the generated figures rather than memory.
- [ ] **[automatable]** Re-run the §8.3 probes a day later. A demo that was safe at deploy time and is
      not safe now is the failure mode a scheduled reseed (P3) exists to catch.
- [ ] **[needs you]** Watch the first week's traffic. If the instance is being hammered, apply P4 from
      `public-demo-safety.md`.
- [ ] **[needs you]** Decide whether to enable Dependabot. The repository currently has **no
      supply-chain scanning**, which it says about itself in the README's limitations. Turning it on
      is two clicks and removes the item.
