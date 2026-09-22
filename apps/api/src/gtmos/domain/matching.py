"""Lead-to-account matching and identity normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com",
    "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "yandex.com", "zoho.com", "mail.com",
    "fastmail.com", "hey.com", "qq.com", "163.com",
})

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_NAME_SUFFIXES = re.compile(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|gmbh|plc|sa|ag)\b\.?")


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
    if not name:
        return ""
    n = name.lower()
    n = _NAME_SUFFIXES.sub("", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return " ".join(n.split())


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
