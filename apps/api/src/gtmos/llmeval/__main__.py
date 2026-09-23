"""python -m gtmos.llmeval [--json] [--out PATH]

Grades whichever research writer GTMOS is configured to use against the golden set. Touches no
database and makes no network call unless an LLM writer is explicitly enabled, which the demo never
does: with LLM_ENABLED unset this runs entirely against the deterministic generator.

Exit code 1 when any case fails, so it can gate a build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gtmos.config import get_settings
from gtmos.domain.llm_eval import run_suite
from gtmos.domain.llm_eval_cases import CASES
from gtmos.domain.research import generate_deterministic


def render(report: dict[str, Any]) -> str:
    lines = [
        "# Generated-content evaluation",
        "",
        f"Writer under test: **{report['writer']}**. {report['passed']} of {report['cases']} cases passed.",
        "",
        "| Case | Result | Claims | What it checks |",
        "| --- | :---: | ---: | --- |",
    ]
    for r in report["results"]:
        lines.append(
            f"| `{r['case']}` | {'pass' if r['passed'] else '**FAIL**'} | {r['claims']} | {r['expectation']} |"
        )
    lines += ["", "## Checks", "", "| Check | Passed | Failed |", "| --- | ---: | ---: |"]
    for name, counts in sorted(report["by_check"].items()):
        lines.append(f"| `{name}` | {counts['passed']} | {counts['failed']} |")

    failures = [(r, c) for r in report["results"] for c in r["checks"] if not c["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- **{r['case']} / {c['check']}** — {c['detail']}" for r, c in failures]

    lines += ["", "## Caveats", ""] + [f"- {c}" for c in report["caveats"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the configured research writer.")
    parser.add_argument("--json", action="store_true", help="emit the raw report instead of markdown")
    parser.add_argument("--out", type=Path, help="write to this file instead of stdout")
    args = parser.parse_args(argv)

    settings = get_settings()
    # The LLM writer is only ever graded when someone has deliberately turned it on. The harness does
    # not enable it, and the demo never does.
    writer_name = "deterministic"
    if settings.llm_enabled:
        writer_name = "deterministic (LLM_ENABLED is set, but this suite grades the deterministic path)"

    report = run_suite(CASES, generate_deterministic, writer_name)
    text = json.dumps(report, indent=2, default=str) if args.json else render(report)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
