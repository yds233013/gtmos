"""LLM provider boundary.

GTMOS works fully without an LLM: research and personalization have deterministic generators that
only restate evidence. When ANTHROPIC_API_KEY is set, `AnthropicResearchWriter` asks Claude to write
the brief as structured output that must cite evidence refs. The caller then runs the same citation
validation as for the demo generator, so uncited LLM claims are stripped exactly like any other.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from pydantic import BaseModel, Field

from gtmos.config import Settings
from gtmos.domain.research import SECTION_ORDER, SECTION_TITLES, Claim, Evidence

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The live provider failed or refused. Callers fall back to the deterministic generator."""


class ClaimOut(BaseModel):
    text: str
    evidence: list[str] = Field(description="Evidence refs like 'E3' that directly support the claim")
    hypothesis: bool = Field(description="True if this is an inference rather than a restated fact")


class ResearchOut(BaseModel):
    account_summary: list[ClaimOut]
    why_now: list[ClaimOut]
    relevant_signals: list[ClaimOut]
    likely_pain: list[ClaimOut]
    technical_context: list[ClaimOut]
    buying_committee: list[ClaimOut]
    potential_objections: list[ClaimOut]
    recommended_angle: list[ClaimOut]


class ResearchWriter(Protocol):
    name: str

    def write(self, account_name: str, seller: dict[str, str], evidence: list[Evidence]) -> dict[str, list[Claim]]: ...


SYSTEM_PROMPT = """You are an account researcher for a B2B sales team. You write research briefs that \
sellers rely on, so accuracy matters more than eloquence.

Rules:
- Use ONLY the numbered evidence provided. Every claim must cite one or more refs (e.g. "E3").
- Never introduce facts, numbers, names, customers or events that are not in the evidence.
- Pain points, objections and angles are inferences: mark them hypothesis=true and cite the evidence \
that motivates them.
- Be concise: 1-4 claims per section, one or two sentences each.
- If the evidence does not support a section, return an empty list for it rather than guessing."""


class AnthropicResearchWriter:
    def __init__(self, settings: Settings) -> None:
        import anthropic

        if settings.anthropic_api_key is None:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(), timeout=90.0, max_retries=2
        )
        self._model = settings.llm_model
        self.name = f"anthropic:{settings.llm_model}"

    def write(self, account_name: str, seller: dict[str, str], evidence: list[Evidence]) -> dict[str, list[Claim]]:
        import anthropic

        ev_json = json.dumps(
            [
                {
                    "ref": e.ref,
                    "kind": e.kind,
                    "label": e.label,
                    "detail": e.detail,
                    "source": e.source,
                    "confidence": e.confidence,
                }
                for e in evidence
            ],
            indent=1,
        )
        sections = "\n".join(f"- {k}: {SECTION_TITLES[k]}" for k in SECTION_ORDER)
        prompt = (
            f"Seller: {seller.get('name')}: {seller.get('product')}\n"
            f"Target account: {account_name}\n\nSections to write:\n{sections}\n\n"
            f"Evidence:\n{ev_json}"
        )
        try:
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=ResearchOut,
                output_config={"effort": "medium"},
                # Opus 5 may decline some requests; let the API re-route to the recommended fallback.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIStatusError as exc:
            log.warning(
                "LLM research failed: status=%s request_id=%s", exc.status_code, getattr(exc, "request_id", None)
            )
            raise LLMUnavailable(f"provider error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("provider unreachable") from exc
        if response.stop_reason == "refusal":
            raise LLMUnavailable("provider declined the request")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMUnavailable(f"no structured output (stop_reason={response.stop_reason})")
        return {k: [Claim(c.text, list(c.evidence), c.hypothesis) for c in getattr(parsed, k)] for k in SECTION_ORDER}


def get_research_writer(settings: Settings) -> ResearchWriter | None:
    """Returns a live writer when configured, else None (use the deterministic generator)."""
    if settings.llm_mode != "live":
        return None
    try:
        return AnthropicResearchWriter(settings)
    except LLMUnavailable:
        return None
