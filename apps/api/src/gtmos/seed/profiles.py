"""Deterministic synthetic company universe.

`company_universe()` always returns the same companies for the same size. The seed loads them into
the CRM with realistic gaps (missing employee counts, stale tech stacks), and the *simulated*
enrichment providers answer lookups from this same universe. Enrichment in demo mode therefore
fills real gaps with the "true" values instead of inventing new ones, and it stays reproducible.

All domains use the reserved `.example` TLD (RFC 2606) so no generated record can collide with a real
company or email address.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache

SEED = 20260921

PREFIXES = [
    "Arc",
    "Atlas",
    "Aurora",
    "Basalt",
    "Beacon",
    "Birch",
    "Bolt",
    "Brightline",
    "Cadence",
    "Canopy",
    "Cinder",
    "Cobalt",
    "Copper",
    "Cortex",
    "Crest",
    "Delta",
    "Driftwood",
    "Ember",
    "Evergreen",
    "Falcon",
    "Fathom",
    "Fern",
    "Flint",
    "Forge",
    "Gable",
    "Garnet",
    "Glacier",
    "Granite",
    "Halcyon",
    "Harbor",
    "Helio",
    "Hollow",
    "Indigo",
    "Ion",
    "Juniper",
    "Keystone",
    "Lattice",
    "Ledger",
    "Lumen",
    "Maple",
    "Meridian",
    "Mesa",
    "Monarch",
    "Mosaic",
    "Nimbus",
    "Northwind",
    "Nova",
    "Oak",
    "Onyx",
    "Orbit",
    "Osprey",
    "Palisade",
    "Paragon",
    "Pebble",
    "Pinnacle",
    "Prism",
    "Quarry",
    "Quill",
    "Radiant",
    "Redwood",
    "Ridge",
    "Rook",
    "Sable",
    "Sage",
    "Sequoia",
    "Signal",
    "Slate",
    "Solstice",
    "Sparrow",
    "Spruce",
    "Stratus",
    "Summit",
    "Tandem",
    "Tern",
    "Thistle",
    "Tidal",
    "Timber",
    "Topaz",
    "Tundra",
    "Umber",
    "Vale",
    "Vantage",
    "Vector",
    "Verdant",
    "Vireo",
    "Wander",
    "Willow",
    "Wren",
    "Zenith",
    "Zephyr",
]
QUALIFIERS = ["Group", "Technologies", "Global", "Digital", "Studio", "One"]
SUFFIXES = [
    "Labs",
    "AI",
    "Systems",
    "Data",
    "Cloud",
    "Analytics",
    "Software",
    "Works",
    "Stack",
    "Health",
    "Pay",
    "Security",
    "Logic",
    "Metrics",
    "Robotics",
    "Networks",
    "Dynamics",
    "Intelligence",
    "Platforms",
    "IO",
]

INDUSTRIES: list[tuple[str, float, float]] = [
    # (industry, weight, AI-maturity mean)
    ("AI/ML Platforms", 0.11, 0.85),
    ("Developer Tools", 0.12, 0.7),
    ("Data Infrastructure", 0.10, 0.72),
    ("B2B SaaS", 0.18, 0.55),
    ("Fintech", 0.09, 0.55),
    ("Healthtech", 0.07, 0.5),
    ("Cybersecurity", 0.07, 0.55),
    ("E-commerce Software", 0.06, 0.45),
    ("Martech", 0.06, 0.45),
    ("Manufacturing", 0.04, 0.2),
    ("Retail", 0.03, 0.25),
    ("Media", 0.03, 0.3),
    ("Logistics", 0.02, 0.25),
    ("Education", 0.01, 0.2),
    ("Government", 0.005, 0.15),
    ("Nonprofit", 0.005, 0.1),
]

REGIONS: list[tuple[str, float, list[tuple[str, str]]]] = [
    (
        "NA",
        0.55,
        [
            ("US", "San Francisco"),
            ("US", "New York"),
            ("US", "Seattle"),
            ("US", "Austin"),
            ("US", "Boston"),
            ("US", "Chicago"),
            ("CA", "Toronto"),
            ("US", "Denver"),
            ("CA", "Vancouver"),
        ],
    ),
    (
        "EMEA",
        0.28,
        [
            ("GB", "London"),
            ("DE", "Berlin"),
            ("FR", "Paris"),
            ("NL", "Amsterdam"),
            ("SE", "Stockholm"),
            ("IE", "Dublin"),
            ("IL", "Tel Aviv"),
            ("CH", "Zurich"),
        ],
    ),
    ("APAC", 0.12, [("SG", "Singapore"), ("AU", "Sydney"), ("IN", "Bengaluru"), ("JP", "Tokyo")]),
    ("LATAM", 0.05, [("BR", "São Paulo"), ("MX", "Mexico City"), ("AR", "Buenos Aires")]),
]

LLM_STACK = [
    "OpenAI",
    "Anthropic",
    "LangChain",
    "LlamaIndex",
    "Pinecone",
    "Weaviate",
    "pgvector",
    "Hugging Face",
    "vLLM",
    "Ray",
    "MLflow",
    "Weights & Biases",
]
PLATFORM_STACK = [
    "Kubernetes",
    "Snowflake",
    "Databricks",
    "Datadog",
    "AWS SageMaker",
    "Vertex AI",
    "Kafka",
    "Terraform",
]
OTHER_STACK = [
    "Salesforce",
    "HubSpot",
    "Segment",
    "Stripe",
    "React",
    "PostgreSQL",
    "Redis",
    "GitHub Actions",
    "Okta",
    "Zendesk",
]
INCUMBENTS = ["LangSmith", "Arize", "Datadog LLM Observability"]

FUNDING_BY_SIZE = [
    (100, ["Seed", "Series A"]),
    (400, ["Series A", "Series B"]),
    (1500, ["Series B", "Series C"]),
    (5000, ["Series C", "Series D+", "Public"]),
    (10**9, ["Series D+", "Public", "Private Equity"]),
]


@dataclass(frozen=True)
class CompanyProfile:
    index: int
    name: str
    domain: str
    industry: str
    employee_count: int
    employee_growth_12m: float
    country: str
    region: str
    city: str
    founded_year: int
    funding_stage: str
    total_funding_usd: int | None
    annual_revenue_usd: int
    technologies: tuple[str, ...]
    ai_team_size: int
    ai_open_roles: int
    ai_maturity: float  # latent 0..1; drives signals and conversion so analytics have real structure
    description: str
    tags: tuple[str, ...] = field(default=())


def segment_for(employees: int | None) -> str | None:
    if employees is None:
        return None
    if employees >= 2000:
        return "strategic"
    if employees >= 500:
        return "enterprise"
    if employees >= 100:
        return "mid_market"
    return "smb"


def _pick_weighted[T](rng: random.Random, items: list[tuple[T, float]]) -> T:
    total = sum(w for _, w in items)
    x = rng.random() * total
    acc = 0.0
    for item, w in items:
        acc += w
        if x < acc:
            return item
    return items[-1][0]


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-").replace("--", "-")


FLAGSHIP = CompanyProfile(
    index=0,
    name="Kestrel Analytics",
    domain="kestrel-analytics.example",
    industry="AI/ML Platforms",
    employee_count=850,
    employee_growth_12m=0.42,
    country="US",
    region="NA",
    city="San Francisco",
    founded_year=2017,
    funding_stage="Series C",
    total_funding_usd=182_000_000,
    annual_revenue_usd=96_000_000,
    technologies=(
        "OpenAI",
        "Anthropic",
        "LangChain",
        "Pinecone",
        "Kubernetes",
        "Snowflake",
        "Datadog",
        "LangSmith",
        "PostgreSQL",
        "React",
    ),
    ai_team_size=64,
    ai_open_roles=14,
    ai_maturity=0.95,
    description=(
        "Kestrel Analytics builds an analytics platform for revenue teams and recently launched "
        "Kestrel Copilot, an AI agent that answers questions over customer data."
    ),
    tags=("flagship",),
)


def _make_profile(rng: random.Random, index: int, used: set[str]) -> CompanyProfile:
    attempts = 0
    while True:
        attempts += 1
        name = f"{rng.choice(PREFIXES)} {rng.choice(SUFFIXES)}"
        if attempts > 25:  # the base name space is nearly exhausted: add a qualifier
            name = f"{name} {rng.choice(QUALIFIERS)}"
        slug = _slug(name)
        if slug not in used and name != FLAGSHIP.name:
            used.add(slug)
            break
    industry, maturity_mean = _pick_weighted(rng, [((i, m), w) for i, w, m in INDUSTRIES])
    region, places = _pick_weighted(rng, [((r, p), w) for r, w, p in REGIONS])
    country, city = rng.choice(places)
    employees = int(min(max(rng.lognormvariate(6.0, 1.15), 15), 40_000))
    maturity = min(max(rng.gauss(maturity_mean, 0.18), 0.0), 1.0)
    growth = round(rng.gauss(0.12 + 0.25 * maturity, 0.14), 3)
    funding_stage = next(rng.choice(stages) for cap, stages in FUNDING_BY_SIZE if employees < cap)
    total_funding = (
        None
        if funding_stage in ("Public", "Private Equity")
        else int(employees * rng.uniform(60_000, 220_000) // 1_000_000 * 1_000_000) or 2_000_000
    )
    revenue = int(employees * rng.uniform(90_000, 260_000) // 1_000_000 * 1_000_000) or 1_000_000

    n_llm = max(0, min(len(LLM_STACK), round(rng.gauss(maturity * 5, 1.2))))
    n_plat = max(0, min(len(PLATFORM_STACK), round(rng.gauss(1 + (employees > 300) * 2 + maturity, 1))))
    techs = rng.sample(LLM_STACK, n_llm) + rng.sample(PLATFORM_STACK, n_plat) + rng.sample(OTHER_STACK, 3)
    if maturity > 0.6 and rng.random() < 0.3:
        techs.append(rng.choice(INCUMBENTS))
    ai_ratio = max(0.0, rng.gauss(0.01 + 0.07 * maturity, 0.015))
    ai_team = int(employees * ai_ratio)
    ai_open = max(0, int(ai_team * max(rng.gauss(0.12 + 0.2 * maturity * max(growth, 0), 0.06), 0)))
    desc = f"{name} is a {industry.lower()} company based in {city} with roughly {employees:,} employees."
    return CompanyProfile(
        index=index,
        name=name,
        domain=f"{slug}.example",
        industry=industry,
        employee_count=employees,
        employee_growth_12m=growth,
        country=country,
        region=region,
        city=city,
        founded_year=rng.randint(1998, 2022),
        funding_stage=funding_stage,
        total_funding_usd=total_funding,
        annual_revenue_usd=revenue,
        technologies=tuple(sorted(set(techs))),
        ai_team_size=ai_team,
        ai_open_roles=ai_open,
        ai_maturity=round(maturity, 3),
        description=desc,
    )


@lru_cache(maxsize=4)
def company_universe(size: int = 2000) -> tuple[CompanyProfile, ...]:
    rng = random.Random(SEED)
    used = {_slug(FLAGSHIP.name)}
    profiles = [FLAGSHIP]
    for i in range(1, size):
        profiles.append(_make_profile(rng, i, used))
    return tuple(profiles)


@lru_cache(maxsize=4)
def registry(size: int = 2000) -> dict[str, CompanyProfile]:
    return {p.domain: p for p in company_universe(size)}
