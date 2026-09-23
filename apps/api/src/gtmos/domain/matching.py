"""Lead-to-account matching and identity normalization.

Salesforce's Lead object has no foreign key to Account, so lead-to-account matching is fuzzy matching by
construction, and it fails silently: a mis-matched lead does not raise, it routes a VP at a target account
into an SDR queue while the named AE never hears about it. The waterfall in `match_lead_to_account` is
ordered by how much each key can be trusted, and it prefers returning nothing to returning a guess —
every tier is precision-first, ambiguity is an explicit non-answer, and rejected candidates come back with
the match so a human reviewing a queue can see what was considered.

The accuracy claim lives in `tests/unit/test_rules_pipeline_matching.py`, which scores the matcher against
a labelled fixture of hard cases and asserts a precision and recall floor.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "yandex.com",
        "zoho.com",
        "mail.com",
        "fastmail.com",
        "hey.com",
        "qq.com",
        "163.com",
    }
)

# Shared inboxes. They are valid company addresses, so they match on domain like any other, but they are
# not a person: the caller decides whether a role address may become a Contact.
ROLE_LOCAL_PARTS = frozenset(
    {
        "info",
        "sales",
        "support",
        "help",
        "admin",
        "hello",
        "contact",
        "team",
        "office",
        "marketing",
        "billing",
        "accounts",
        "careers",
        "jobs",
        "hr",
        "press",
        "legal",
        "privacy",
        "security",
        "noreply",
        "no-reply",
        "donotreply",
        "postmaster",
        "webmaster",
        "abuse",
        "enquiries",
        "inquiries",
    }
)

# Second-level registries: in "kestrel.co.uk" the registrable name is "kestrel", not "co". Not the full
# public-suffix list (that is a 15k-entry file with its own update cadence), just the ones a B2B list hits.
MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "co.jp",
        "or.jp",
        "ne.jp",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "com.br",
        "com.mx",
        "com.ar",
        "com.sg",
        "com.hk",
        "com.tr",
        "com.cn",
        "co.in",
        "co.za",
        "co.kr",
        "com.tw",
        "co.il",
    }
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
# Latin legal-form suffixes, stripped on word boundaries. "co" is here and "group" is not, deliberately:
# "Acme Co" and "Acme" are the same company, "Acme" and "Acme Group" are often a parent and a subsidiary.
_NAME_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|mbh|ag|plc|sa|sarl|srl|spa|bv|nv|"
    r"oy|oyj|ab|aps|kk|pte|pty|pvt)\b\.?"
)
# CJK legal forms carry no word boundary a \b regex can find, so they are removed as literal substrings.
_CJK_NAME_SUFFIXES = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "株式會社",
    "주식회사",
    "有限公司",
    "股份有限公司",
)


def normalize_domain(raw: str | None) -> str | None:
    """'https://www.Kestrel-Analytics.example/about' -> 'kestrel-analytics.example'."""
    if not raw:
        return None
    d = raw.strip().lower()
    d = re.sub(r"^[a-z]+://", "", d)
    d = d.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    d = d.removeprefix("www.")
    d = d.strip(".")
    return d if _DOMAIN_RE.match(d) else None


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    e = raw.strip().lower()
    return e if EMAIL_RE.match(e) else None


def is_valid_email(raw: str | None) -> bool:
    return bool(raw) and EMAIL_RE.match(raw.strip()) is not None  # type: ignore[union-attr]


def email_domain(email: str | None) -> str | None:
    e = normalize_email(email)
    return e.split("@", 1)[1] if e else None


def normalize_company_name(name: str | None) -> str:
    """'Kestrel Analytics, Inc.' / 'ケストレル株式会社' -> the comparable part of the name.

    Legal form is noise for identity: the same company is "Inc" in a CRM, "GmbH" on an invoice and nothing
    at all on a webinar form. Everything that is not a letter or a digit collapses to a single space, so
    punctuation and casing cannot create a duplicate. CJK is left otherwise intact: we have no tokenizer
    for it, and dropping characters we cannot segment would merge companies that are not the same.
    """
    if not name:
        return ""
    n = name.lower()
    for suffix in _CJK_NAME_SUFFIXES:
        n = n.replace(suffix, " ")
    n = _NAME_SUFFIXES.sub("", n)
    n = re.sub(r"[^a-z0-9぀-ヿ㐀-鿿가-힯]+", " ", n)
    return " ".join(n.split())


def is_role_address(email: str | None) -> bool:
    """info@, sales@, support@ … a shared inbox rather than a person."""
    e = normalize_email(email)
    return e is not None and e.split("@", 1)[0].split("+", 1)[0] in ROLE_LOCAL_PARTS


def registrable_domain(raw: str | None) -> str | None:
    """'mail.kestrel.co.uk' -> 'kestrel.co.uk'. The unit a company actually owns."""
    d = normalize_domain(raw)
    if d is None:
        return None
    parts = d.split(".")
    if len(parts) > 2 and ".".join(parts[-2:]) in MULTI_LABEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_brand(raw: str | None) -> str | None:
    """The registrable label without its suffix: 'kestrel.co.uk' and 'kestrel.com' both -> 'kestrel'.

    Country sites are usually the same company, but only usually — a brand label is a weak key and is used
    here only when exactly one account claims it.
    """
    reg = registrable_domain(raw)
    return reg.split(".", 1)[0] if reg else None


def name_similarity(a: str, b: str) -> float:
    """Similarity of two already-normalized company names, 0-1.

    Tokens are sorted before comparison so word order stops mattering ("Analytics Kestrel" vs "Kestrel
    Analytics"), and the comparison is then character-level so a typo or a plural costs a little rather
    than everything. The failure mode this shape accepts is that two companies sharing a long first token
    ("Acme Data" / "Acme Analytics") score higher than they deserve; the threshold is set above them.
    """
    if not a or not b:
        return 0.0
    sa, sb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return SequenceMatcher(None, sa, sb).ratio()


@dataclass(frozen=True)
class MatchResult:
    account_key: str | None  # the matched account's domain
    method: str  # group_key | email_domain | none
    confidence: float
    reason: str


def match_to_account(
    known_domains: set[str],
    email: str | None = None,
    group_domain: str | None = None,
) -> MatchResult:
    """Resolve an inbound person/event to an account domain.

    Priority: an explicit company group key (PostHog `$groups.company`) beats an inferred email domain.
    Free-mail domains never match an account, because gmail.com is not a company.
    """
    g = normalize_domain(group_domain)
    if g and g in known_domains:
        return MatchResult(g, "group_key", 0.98, f"Company group key '{g}' matches a known account.")
    d = email_domain(email)
    if d is None:
        return MatchResult(None, "none", 0.0, "No company key or valid email to match on.")
    if d in FREE_MAIL_DOMAINS:
        return MatchResult(None, "none", 0.0, f"'{d}' is a free-mail domain; cannot infer company.")
    if d in known_domains:
        return MatchResult(d, "email_domain", 0.9, f"Email domain '{d}' matches a known account.")
    # Subdomain of a known account domain (e.g. eu.kestrel.example -> kestrel.example)
    parts = d.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in known_domains:
            return MatchResult(parent, "email_domain", 0.8, f"'{d}' is a subdomain of known account '{parent}'.")
    return MatchResult(None, "none", 0.0, f"No account found for domain '{d}'.")


# The full lead-to-account waterfall ---------------------------------------------------------------------

# Tuned on the labelled fixture in tests/unit/test_rules_pipeline_matching.py, which makes the reported
# precision and recall in-sample. It is set above the highest-scoring known negative pair in that fixture
# ("Acme Data" vs "Acme Analytics"-shaped near-duplicates) rather than at the point that maximises F1,
# because a wrong account is more expensive than no account: a wrong one routes to the wrong rep silently.
FUZZY_NAME_THRESHOLD = 0.86
# Below this many characters a fuzzy score is noise: "Nexa" and "Nexo" are 75% similar and unrelated.
MIN_FUZZY_NAME_CHARS = 6
# Near-misses worth showing a human in a review queue, even though they were not matched.
NEAR_MISS_FLOOR = 0.60


@dataclass(frozen=True)
class Lead:
    """An inbound person before they belong to anything: a form fill, a signup, a list import."""

    email: str | None = None
    company_name: str | None = None
    website: str | None = None
    group_domain: str | None = None  # an explicit company key from the source (PostHog `$groups.company`)


@dataclass(frozen=True)
class AccountRef:
    """The bits of an account the matcher compares against. `key` is whatever the caller identifies it by."""

    key: str
    name: str
    domain: str | None = None
    aliases: tuple[str, ...] = ()  # DBA names, former names, acquired brands — as the CRM records them


@dataclass(frozen=True)
class RejectedCandidate:
    account_key: str
    method: str
    score: float
    reason: str


@dataclass(frozen=True)
class LeadMatch:
    account_key: str | None
    # exact_domain | registrable_domain | subdomain | brand_domain | company_name | fuzzy_name | ambiguous | none
    method: str
    confidence: float
    reason: str
    rejected: tuple[RejectedCandidate, ...] = field(default_factory=tuple)
    review_required: bool = False  # ambiguous, or matched below the confidence a human should not check


@dataclass(frozen=True)
class _Indexed:
    account: AccountRef
    domain: str | None
    registrable: str | None
    brand: str | None
    names: tuple[str, ...]  # normalized name plus normalized aliases


def _index(accounts: Sequence[AccountRef]) -> list[_Indexed]:
    out = []
    for a in accounts:
        names = tuple(
            dict.fromkeys(
                n for n in (normalize_company_name(a.name), *(normalize_company_name(x) for x in a.aliases)) if n
            )
        )
        out.append(_Indexed(a, normalize_domain(a.domain), registrable_domain(a.domain), domain_brand(a.domain), names))
    return out


def _lead_domains(lead: Lead) -> tuple[list[tuple[str, str, float]], str | None]:
    """Domains the lead offers, best key first, plus a note if one was dropped for being free-mail.

    Free-mail is dropped rather than demoted. gmail.com is not a company, and a matcher that treats it as
    one produces an "account" containing every consumer lead the business has ever seen.
    """
    out: list[tuple[str, str, float]] = []
    note: str | None = None
    for raw, method, conf in (
        (lead.group_domain, "group_key", 0.98),
        (lead.website, "website", 0.95),
        (email_domain(lead.email), "email_domain", 0.92),
    ):
        d = normalize_domain(raw)
        if d is None:
            continue
        if d in FREE_MAIL_DOMAINS or (registrable_domain(d) or d) in FREE_MAIL_DOMAINS:
            note = f"'{d}' is a free-mail domain, so it was not used as a company key."
            continue
        out.append((d, method, conf))
    return out, note


def match_lead_to_account(lead: Lead, accounts: Sequence[AccountRef]) -> LeadMatch:
    """Resolve a lead to one account, or to nothing, with the method and the candidates it turned down.

    The waterfall, strongest key first:

    1. **Exact domain.** The lead's company key, website or email domain equals an account's domain.
    2. **Registrable domain.** Same after stripping `www.`, subdomains and country second-level suffixes,
       so `mail.kestrel.co.uk` reaches `kestrel.co.uk`.
    3. **Subdomain.** `eu.kestrel.example` under a known `kestrel.example`.
    4. **Brand label across TLDs.** `kestrel.de` to `kestrel.example`, but only when exactly one account
       claims that label — this is the weakest domain key and the easiest to get wrong.
    5. **Normalized company name**, including aliases (DBA and acquired-brand names).
    6. **Fuzzy company name** above `FUZZY_NAME_THRESHOLD`.

    Two rules apply at every tier. A tier that produces more than one candidate returns no match with
    `method="ambiguous"` and flags the lead for review, because picking one of two equally good accounts is
    how a matcher quietly corrupts a CRM. And domains are never fuzzy-matched: one character separates
    competitors, so a typo'd domain is a miss by design and is handled, if at all, by the name tiers.
    """
    idx = _index(accounts)
    rejected: list[RejectedCandidate] = []
    domains, free_mail_note = _lead_domains(lead)

    def ambiguous(hits: list[_Indexed], method: str, detail: str) -> LeadMatch:
        keys = sorted(h.account.key for h in hits)
        return LeadMatch(
            None,
            "ambiguous",
            0.0,
            f"{detail} matches {len(keys)} accounts ({', '.join(keys)}). Matching one of them would be a coin flip.",
            tuple(RejectedCandidate(k, method, 0.0, "tied with another account on the same key") for k in keys),
            review_required=True,
        )

    for dom, source, conf in domains:
        reg = registrable_domain(dom)
        for tier, method, score, hits in (
            (1, "exact_domain", conf, [i for i in idx if i.domain and i.domain == dom]),
            (2, "registrable_domain", conf - 0.03, [i for i in idx if reg and i.registrable == reg]),
            (3, "subdomain", 0.85, [i for i in idx if i.domain and dom.endswith("." + i.domain)]),
        ):
            if len(hits) == 1:
                return LeadMatch(
                    hits[0].account.key,
                    method,
                    round(score, 2),
                    f"{source.replace('_', ' ')} '{dom}' {'equals' if tier == 1 else 'resolves to'} account domain "
                    f"'{hits[0].account.domain}'.",
                    tuple(rejected),
                )
            if len(hits) > 1:
                return ambiguous(hits, method, f"Domain '{dom}'")
        brand = domain_brand(dom)
        brand_hits = [i for i in idx if brand and i.brand == brand]
        if len(brand_hits) == 1:
            return LeadMatch(
                brand_hits[0].account.key,
                "brand_domain",
                0.78,
                f"'{dom}' and account domain '{brand_hits[0].account.domain}' share the brand label '{brand}' on "
                "different TLDs, and no other account claims it.",
                tuple(rejected),
                review_required=True,
            )
        if len(brand_hits) > 1:
            return ambiguous(brand_hits, "brand_domain", f"Brand label '{brand}'")

    name = normalize_company_name(lead.company_name)
    if not name:
        reason = "No company key, website or work email to match on."
        if domains:
            reason = f"Domain '{domains[0][0]}' matches no account, and the lead carries no company name."
        elif free_mail_note:
            reason = f"{free_mail_note} No company name to fall back on."
        return LeadMatch(None, "none", 0.0, reason, tuple(rejected))

    exact_name = [i for i in idx if name in i.names]
    if len(exact_name) == 1:
        via_alias = name not in (normalize_company_name(exact_name[0].account.name),)
        return LeadMatch(
            exact_name[0].account.key,
            "company_name",
            0.80 if not via_alias else 0.76,
            f"Company name '{lead.company_name}' normalizes to '{name}', which matches account "
            f"'{exact_name[0].account.name}'{' by alias' if via_alias else ''}. No usable domain key was available.",
            tuple(rejected),
        )
    if len(exact_name) > 1:
        return ambiguous(exact_name, "company_name", f"Company name '{name}'")

    scored = sorted(
        ((max(name_similarity(name, n) for n in i.names), i) for i in idx if i.names),
        key=lambda t: (-t[0], t[1].account.key),
    )
    best = scored[0] if scored else None
    if best and best[0] >= FUZZY_NAME_THRESHOLD and len(name) >= MIN_FUZZY_NAME_CHARS:
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if runner_up >= FUZZY_NAME_THRESHOLD:
            return ambiguous([s[1] for s in scored if s[0] >= FUZZY_NAME_THRESHOLD], "fuzzy_name", f"Name '{name}'")
        # Confidence tracks how far past the threshold the score is, capped below the exact-name tier: a
        # fuzzy match is never as good as an exact one, however similar the strings happen to be.
        conf = round(min(0.75, 0.55 + 0.3 * (best[0] - FUZZY_NAME_THRESHOLD) / (1 - FUZZY_NAME_THRESHOLD)), 2)
        rejected.extend(
            RejectedCandidate(i.account.key, "fuzzy_name", round(s, 3), "scored lower than the chosen account")
            for s, i in scored[1:4]
            if s >= NEAR_MISS_FLOOR
        )
        return LeadMatch(
            best[1].account.key,
            "fuzzy_name",
            conf,
            f"'{name}' is {best[0] * 100:.0f}% similar to '{best[1].names[0]}', over the "
            f"{FUZZY_NAME_THRESHOLD * 100:.0f}% bar, and the next best is {runner_up * 100:.0f}%.",
            tuple(rejected),
            review_required=True,
        )
    rejected.extend(
        RejectedCandidate(i.account.key, "fuzzy_name", round(s, 3), f"below the {FUZZY_NAME_THRESHOLD:.2f} name bar")
        for s, i in scored[:3]
        if s >= NEAR_MISS_FLOOR
    )
    detail = f" Closest was '{scored[0][1].names[0]}' at {scored[0][0] * 100:.0f}%." if scored else ""
    return LeadMatch(
        None,
        "none",
        0.0,
        f"No account matched '{name}' on domain or name.{detail}" + (f" {free_mail_note}" if free_mail_note else ""),
        tuple(rejected),
        review_required=bool(rejected),
    )
