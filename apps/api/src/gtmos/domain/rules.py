"""A tiny, safe condition language shared by routing rules and workflow conditions.

Conditions are data ({field, op, value}), never code. There is no eval(): an unknown operator or
field is a validation error, not an exploit.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Op = Literal["eq", "neq", "in", "not_in", "gte", "lte", "gt", "lt", "exists", "not_exists", "contains"]

OP_LABELS = {
    "eq": "=", "neq": "≠", "in": "in", "not_in": "not in", "gte": "≥", "lte": "≤", "gt": ">", "lt": "<",
    "exists": "is set", "not_exists": "is not set", "contains": "contains",
}


class Condition(BaseModel):
    field: str
    op: Op
    value: Any = None

    def describe(self) -> str:
        if self.op in ("exists", "not_exists"):
            return f"{self.field} {OP_LABELS[self.op]}"
        v = ", ".join(map(str, self.value)) if isinstance(self.value, list) else self.value
        return f"{self.field} {OP_LABELS[self.op]} {v}"


def resolve(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def evaluate(cond: Condition, ctx: dict[str, Any]) -> tuple[bool, Any]:
    actual = resolve(ctx, cond.field)
    v = cond.value
    op = cond.op
    if op == "exists":
        return actual is not None, actual
    if op == "not_exists":
        return actual is None, actual
    if actual is None:
        return False, actual
    try:
        match op:
            case "eq":
                ok = actual == v
            case "neq":
                ok = actual != v
            case "in":
                ok = actual in (v or [])
            case "not_in":
                ok = actual not in (v or [])
            case "gte":
                ok = actual >= v
            case "lte":
                ok = actual <= v
            case "gt":
                ok = actual > v
            case "lt":
                ok = actual < v
            case "contains":
                ok = v in actual
    except TypeError:
        ok = False
    return bool(ok), actual


def evaluate_all(conds: list[Condition], ctx: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    results = []
    all_ok = True
    for c in conds:
        ok, actual = evaluate(c, ctx)
        all_ok = all_ok and ok
        results.append({"condition": c.describe(), "field": c.field, "op": c.op, "expected": c.value,
                        "actual": actual, "passed": ok})
    return all_ok, results
