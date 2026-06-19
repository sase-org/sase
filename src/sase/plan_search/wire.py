"""Wire helpers for the Rust plan-search facade.

Converts the JSON-shaped dicts returned by the ``plan_search`` binding into the
:mod:`sase.plan_search.model` dataclasses. The dict shape mirrors the Rust
``PlanSearchMatchWire``/``PlanWire`` serde output (``crates/sase_core/src/plan/
wire.rs``); conversion is defensive about missing/``None`` fields so a stale or
partial payload degrades to empty strings rather than raising.
"""

from __future__ import annotations

from typing import Any

from sase.plan_search.model import Plan, PlanSearchMatch


def _str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return "" if value is None else str(value)


def _plan_from_dict(data: dict[str, Any]) -> Plan:
    raw_frontmatter = data.get("frontmatter") or {}
    return Plan(
        source=_str(data, "source"),
        kind=_str(data, "kind"),
        path=_str(data, "path"),
        relpath=_str(data, "relpath"),
        name=_str(data, "name"),
        title=_str(data, "title"),
        status=_str(data, "status"),
        created_at=_str(data, "created_at"),
        prompt_link=_str(data, "prompt_link"),
        summary=_str(data, "summary"),
        body=_str(data, "body"),
        frontmatter={
            str(key): "" if value is None else str(value)
            for key, value in dict(raw_frontmatter).items()
        },
    )


def _plan_search_match_from_dict(data: dict[str, Any]) -> PlanSearchMatch:
    return PlanSearchMatch(
        plan=_plan_from_dict(dict(data["plan"])),
        matched_fields=[str(field) for field in data.get("matched_fields", [])],
        score=float(data.get("score", 0.0)),
    )


def plan_search_matches_from_list(
    items: list[dict[str, Any]],
) -> list[PlanSearchMatch]:
    return [_plan_search_match_from_dict(item) for item in items]


__all__ = ["plan_search_matches_from_list"]
