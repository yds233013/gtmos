"""ICP definition: the structured, versioned description of who we sell to.

The builder UI edits this object; the scoring engine consumes it. Nothing here is free text that
an LLM interprets. Every criterion is a deterministic rule with an explicit point budget.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from gtmos.domain.signals import SIGNAL_TYPES


class CategoryWeights(BaseModel):
    fit: float = 35
    intent: float = 25
    timing: float = 15
    technical: float = 15
    engagement: float = 10

    @model_validator(mode="after")
    def _sum_to_100(self) -> CategoryWeights:
        total = self.fit + self.intent + self.timing + self.technical + self.engagement
        if abs(total - 100) > 0.001:
            raise ValueError(f"category weights must sum to 100 (got {total:g})")
        if min(self.fit, self.intent, self.timing, self.technical, self.engagement) < 0:
            raise ValueError("category weights must be non-negative")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class SizeBand(BaseModel):
    min_employees: int = 100
    max_employees: int = 10000
    sweet_spot_min: int = 250
    sweet_spot_max: int = 5000
    hard_min_employees: int = 25  # below this the account is excluded outright

    @model_validator(mode="after")
    def _ordered(self) -> SizeBand:
        if not (
            self.hard_min_employees
            <= self.min_employees
            <= self.sweet_spot_min
            <= self.sweet_spot_max
            <= self.max_employees
        ):
            raise ValueError("size band must satisfy hard_min <= min <= sweet_min <= sweet_max <= max")
        return self


class TechnicalProfile(BaseModel):
    """What 'technically compatible' means for the seller's product."""

    ai_team_min: int = 10
    ai_team_strong: int = 50
    llm_stack: list[str] = Field(
        default_factory=lambda: [
            "OpenAI", "Anthropic", "LangChain", "LlamaIndex", "Pinecone", "Weaviate",
            "pgvector", "Hugging Face", "vLLM", "Ray", "MLflow", "Weights & Biases",
        ]
    )
    platform_stack: list[str] = Field(
        default_factory=lambda: [
            "Kubernetes", "Snowflake", "Databricks", "Datadog", "AWS SageMaker", "Vertex AI",
            "Kafka", "Terraform",
        ]
    )


class ICPDefinition(BaseModel):
    name: str = "Enterprise AI teams shipping LLM products"
    description: str = ""
    core_industries: list[str] = Field(default_factory=list)
    adjacent_industries: list[str] = Field(default_factory=list)
    size: SizeBand = Field(default_factory=SizeBand)
    primary_regions: list[str] = Field(default_factory=lambda: ["NA"])
    secondary_regions: list[str] = Field(default_factory=lambda: ["EMEA"])
    funding_stages: list[str] = Field(default_factory=list)  # informational; timing uses signals
    min_growth_rate: float = 0.05
    technical: TechnicalProfile = Field(default_factory=TechnicalProfile)
    buyer_personas: list[str] = Field(default_factory=list)
    # signal_type -> max points that signal type can contribute inside its category
    positive_signals: dict[str, float] = Field(default_factory=dict)
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_countries: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)
    weights: CategoryWeights = Field(default_factory=CategoryWeights)

    @field_validator("positive_signals")
    @classmethod
    def _known_signals(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(v) - set(SIGNAL_TYPES))
        if unknown:
            raise ValueError(f"unknown signal types: {', '.join(unknown)}")
        if any(p < 0 for p in v.values()):
            raise ValueError("signal points must be non-negative")
        return v

    @model_validator(mode="after")
    def _no_overlap(self) -> ICPDefinition:
        overlap = set(self.core_industries) & set(self.excluded_industries)
        if overlap:
            raise ValueError(f"industries cannot be both core and excluded: {sorted(overlap)}")
        return self


def default_icp() -> ICPDefinition:
    """The seller's (Sentinel AI) ICP: B2B software companies running LLMs/agents in production."""
    return ICPDefinition(
        name="Enterprise AI teams shipping LLM products",
        description=(
            "B2B software and technology companies with a meaningful AI/ML engineering org that are "
            "deploying LLM applications or agents to customers and need them to be reliable."
        ),
        core_industries=["AI/ML Platforms", "Developer Tools", "Data Infrastructure", "B2B SaaS"],
        adjacent_industries=["Fintech", "Healthtech", "Cybersecurity", "E-commerce Software", "Martech"],
        size=SizeBand(),
        primary_regions=["NA"],
        secondary_regions=["EMEA"],
        funding_stages=["Series B", "Series C", "Series D+", "Public"],
        min_growth_rate=0.05,
        buyer_personas=[
            "CTO", "VP Engineering", "Head of AI", "Head of ML", "ML Platform Lead",
            "Director of AI Infrastructure",
        ],
        positive_signals={
            "ai_hiring_surge": 9,
            "ai_product_launch": 8,
            "job_posting": 5,
            "tech_adoption": 4,
            "pricing_page_visit": 6,
            "funding_round": 7,
            "executive_hire": 5,
            "expansion": 2,
            "product_signup": 2,
            "teammate_invited": 2,
            "integration_activated": 2,
            "usage_threshold": 3,
            "website_visit": 1,
        },
        excluded_industries=["Government", "Nonprofit"],
        excluded_countries=["KP", "IR", "SY", "CU"],
        excluded_domains=[],
    )
