"""Enrichment providers.

Three SIMULATED providers answer from the deterministic demo universe (seed/profiles.py) with
provider-specific coverage, noise, confidence, cost and failure behavior, so waterfall mechanics
(fallbacks, low-confidence answers, errors) happen for real without any paid API. Their names say
"(simulated)" everywhere they are shown.

`ApolloOrganizationProvider` is an optional real adapter for Apollo's organization enrichment endpoint.
It is only registered when APOLLO_API_KEY is set, and it has not been exercised against the live API
in this repository (no credentials were available); treat it as an integration boundary to verify.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from gtmos.config import Settings
from gtmos.domain.enrichment import EnrichmentProvider, FieldValue, ProviderError
from gtmos.seed.profiles import CompanyProfile, registry


def _h(*parts: str) -> float:
    """Deterministic pseudo-random number in [0, 1) from string parts."""
    d = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(d[:12], 16) / float(16**12)


class _SimulatedProvider:
    key = ""
    name = ""
    supported_fields: frozenset[str] = frozenset()
    cost_per_lookup = 0.0
    is_simulated = True
    coverage = 1.0
    error_rate = 0.0

    def __init__(self, universe_size: int) -> None:
        self._universe_size = universe_size
        self.last_latency_ms = 0

    def _profile(self, domain: str) -> CompanyProfile | None:
        return registry(self._universe_size).get(domain)

    def lookup(self, domain: str, fields: list[str]) -> dict[str, FieldValue]:
        # Simulated latency is reported, not slept, so demos and tests stay fast.
        self.last_latency_ms = int(120 + _h(self.key, domain, "lat") * 900)
        if _h(self.key, domain, "err") < self.error_rate:
            raise ProviderError(f"{self.name}: upstream timeout (simulated)")
        p = self._profile(domain)
        if p is None or _h(self.key, domain, "cov") >= self.coverage:
            return {}
        out: dict[str, FieldValue] = {}
        for f in fields:
            v = self._value(p, f, domain)
            if v is not None:
                out[f] = v
        return out

    def _value(self, p: CompanyProfile, field: str, domain: str) -> FieldValue | None:  # pragma: no cover
        raise NotImplementedError


class DemoFirmographicsProvider(_SimulatedProvider):
    key = "demo_firmographics"
    name = "Firmographics DB (simulated)"
    supported_fields = frozenset(
        {
            "industry",
            "employee_count",
            "country",
            "region",
            "city",
            "founded_year",
            "funding_stage",
            "total_funding_usd",
            "annual_revenue_usd",
            "employee_growth_12m",
        }
    )
    cost_per_lookup = 1.0
    coverage = 0.82
    error_rate = 0.05

    def _value(self, p: CompanyProfile, field: str, domain: str) -> FieldValue | None:
        conf = round(0.86 + _h(self.key, domain, field) * 0.1, 2)
        if field == "employee_growth_12m":
            return FieldValue(p.employee_growth_12m, round(conf - 0.2, 2))
        return FieldValue(getattr(p, field), conf)


class DemoWebScanProvider(_SimulatedProvider):
    key = "demo_webscan"
    name = "Website & technographics scanner (simulated)"
    supported_fields = frozenset({"technologies", "employee_count", "industry", "city", "country", "region"})
    cost_per_lookup = 0.5
    coverage = 0.78
    error_rate = 0.02

    def _value(self, p: CompanyProfile, field: str, domain: str) -> FieldValue | None:
        if field == "technologies":
            return FieldValue(list(p.technologies), round(0.75 + _h(self.key, domain, "t") * 0.15, 2))
        if field == "employee_count":
            # Estimated from LinkedIn-style headcount ranges: noisy and lower confidence.
            noise = 1 + (_h(self.key, domain, "n") - 0.5) * 0.3
            return FieldValue(int(p.employee_count * noise), 0.55)
        if field == "industry":
            return FieldValue(p.industry, 0.68)
        return FieldValue(getattr(p, field), 0.7)


class DemoHiringProvider(_SimulatedProvider):
    key = "demo_hiring"
    name = "Job-postings index (simulated)"
    supported_fields = frozenset({"ai_open_roles", "ai_team_size", "employee_growth_12m"})
    cost_per_lookup = 0.75
    coverage = 0.7
    error_rate = 0.03

    def _value(self, p: CompanyProfile, field: str, domain: str) -> FieldValue | None:
        if field == "ai_open_roles":
            return FieldValue(p.ai_open_roles, 0.9)
        if field == "ai_team_size":
            return FieldValue(p.ai_team_size, 0.72)
        return FieldValue(p.employee_growth_12m, 0.8)


class ApolloOrganizationProvider:
    """Real adapter: GET https://api.apollo.io/api/v1/organizations/enrich?domain=... (API key header)."""

    key = "apollo"
    name = "Apollo organization enrichment"
    supported_fields = frozenset(
        {
            "industry",
            "employee_count",
            "city",
            "country",
            "founded_year",
            "annual_revenue_usd",
            "technologies",
            "total_funding_usd",
        }
    )
    cost_per_lookup = 1.0
    is_simulated = False
    URL = "https://api.apollo.io/api/v1/organizations/enrich"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._client = client or httpx.Client(timeout=15.0)
        self.last_latency_ms = 0

    def lookup(self, domain: str, fields: list[str]) -> dict[str, FieldValue]:
        start = time.perf_counter()
        try:
            r = self._client.get(
                self.URL, params={"domain": domain}, headers={"X-Api-Key": self._key, "Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"apollo: {exc.__class__.__name__}") from exc
        self.last_latency_ms = int((time.perf_counter() - start) * 1000)
        if r.status_code == 404:
            return {}
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"apollo: HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ProviderError(f"apollo: HTTP {r.status_code} (check API key / plan)")
        org: dict[str, Any] = (r.json() or {}).get("organization") or {}
        mapping = {
            "industry": org.get("industry"),
            "employee_count": org.get("estimated_num_employees"),
            "city": org.get("city"),
            "country": org.get("country"),
            "founded_year": org.get("founded_year"),
            "annual_revenue_usd": org.get("annual_revenue"),
            "total_funding_usd": org.get("total_funding"),
            "technologies": [t.get("name") for t in org.get("current_technologies") or [] if t.get("name")],
        }
        return {f: FieldValue(mapping[f], 0.8) for f in fields if mapping.get(f) not in (None, "", [])}


DEFAULT_WATERFALL: dict[str, list[str]] = {
    "industry": ["demo_firmographics", "apollo", "demo_webscan"],
    "employee_count": ["demo_firmographics", "apollo", "demo_webscan"],
    "technologies": ["demo_webscan", "apollo"],
    "ai_team_size": ["demo_hiring"],
    "ai_open_roles": ["demo_hiring"],
    "employee_growth_12m": ["demo_hiring", "demo_firmographics"],
    "funding_stage": ["demo_firmographics"],
    "total_funding_usd": ["demo_firmographics", "apollo"],
    "country": ["demo_firmographics", "demo_webscan"],
    "region": ["demo_firmographics", "demo_webscan"],
    "city": ["demo_firmographics", "demo_webscan"],
}
ENRICHABLE_FIELDS = list(DEFAULT_WATERFALL)


def build_providers(settings: Settings) -> dict[str, EnrichmentProvider]:
    providers: dict[str, EnrichmentProvider] = {
        "demo_firmographics": DemoFirmographicsProvider(settings.seed_accounts),
        "demo_webscan": DemoWebScanProvider(settings.seed_accounts),
        "demo_hiring": DemoHiringProvider(settings.seed_accounts),
    }
    if settings.apollo_api_key:
        providers["apollo"] = ApolloOrganizationProvider(settings.apollo_api_key.get_secret_value())
    return providers
