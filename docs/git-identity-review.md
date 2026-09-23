# Git identity review

Short answer: **no history rewrite is necessary, and doing one would be the riskier choice.** The
attribution problem is almost certainly solvable by adding an email address to a GitHub account
settings page, which takes a minute and touches nothing in this repository.

## What is actually in the repository

```
$ git log --all --format='%an <%ae>' | sort | uniq -c
  68 yds2330 <yashshah2311@berkeley.edu>
```

Uniform across all 68 commits, author and committer alike. No mixed identities, no stray machine
defaults, nothing to reconcile. Local config matches:

```
user.name  = yds2330
user.email = yashshah2311@berkeley.edu
```

Both are inherited from the global config rather than set per-repository.

## The thing that is easy to get wrong

**GitHub attributes a commit to an account by the author *email*, not by the author *name*.**

The `%an` field — `yds2330` here — is a free-text display string. It has no relationship to any GitHub
account, it is not checked against anything, and two people can put the same string in it. GitHub
looks at `%ae`, compares it against the verified email addresses on every account, and links the
commit to whichever account owns that address.

The practical consequence: if `yashshah2311@berkeley.edu` is a **verified** email on the intended
account, every one of the 68 commits already attributes to that account, and has done since the day it
was written. The commit graph fills in retroactively. Nothing needs rewriting, because nothing is
wrong.

If that address is *not* on the account, the commits display the name string with no avatar and no
link, and they count toward nobody's contribution graph.

## What could and could not be checked from here

Both accounts are already authenticated in the local `gh` CLI, with the intended one active:

```
✓ Logged in to github.com account yds233013 (keyring)   ← active
✓ Logged in to github.com account yds2330   (keyring)
$ gh api user --jq .login
yds233013
```

So the intended account is confirmed as `yds233013`, and the tooling to talk to it already exists.

**What could not be checked:** whether `yashshah2311@berkeley.edu` is a verified email on it. Reading
`/user/emails` needs the `user` scope, which the stored token does not carry. Adding it means
`gh auth refresh -s user`, which is a re-authorisation — not something to do unprompted, and not
necessary, because the answer is one click away in the browser.

## Recommendation, in order of preference

**1 · Verify the email on the account.** GitHub → *Settings → Emails* on `yds233013`. If
`yashshah2311@berkeley.edu` is listed and verified, **stop — there is nothing to fix.** If it is not,
add it and confirm the verification mail. All 68 commits attribute the moment it is verified.

One consideration: adding an address makes it visible under *Settings → Emails*, and GitHub can expose
it on public commits regardless, since a public repository publishes author emails in its git objects.
That is inherent to publishing a git history, not a consequence of this step. If the address should not
be public, the answer is to stop using it as the commit email going forward — which is the next item —
rather than to leave the history unattributed.

**2 · Set the identity explicitly for this repository**, so future commits do not depend on whatever
the global config happens to be:

```bash
git config user.name  "Yash Shah"          # or the preferred display name
git config user.email "<the verified address on yds233013>"
```

The display name is worth changing regardless. `yds2330` reads as a handle for the *other* account,
which is exactly the confusion this review exists to remove; the account's own profile name is
"Yash Shah".

**3 · Rewriting history: do not, unless the email genuinely cannot be added.** `git filter-repo
--mailmap` would rewrite all 68 commits, change every SHA, and break every commit link in the phase
documents and commit messages that reference one. It is the correct tool if — and only if — the
address cannot go on the account, for example because it is a university address that is being lost.
In that case the rewrite must be run before any push, never after. It has not been run, because this
document's whole point is that it is probably unnecessary, and an irreversible rewrite performed on a
guess is the worst available outcome.

## Summary

| | |
|---|---|
| Current author name | `yds2330` (a display string; GitHub ignores it for attribution) |
| Current author email | `yashshah2311@berkeley.edu` |
| Intended account | `yds233013` — confirmed as the active `gh` login |
| Do the existing commits attribute correctly? | **Yes, if that email is verified on the account.** Could not be checked from here without a token re-authorisation. |
| Is a history rewrite necessary? | **Almost certainly not.** |
| Safest action | Check *Settings → Emails*; add and verify the address if missing; set a per-repository `user.name`/`user.email` for future commits. |
