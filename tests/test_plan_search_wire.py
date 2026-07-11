"""Wire-parity tests for the plan-search dataclasses.

Locks the dict shape emitted by the Rust ``PlanSearchMatchWire``/``PlanWire``
serde serialization (``crates/sase_core/src/plan/wire.rs``) to the Python
dataclasses, including defensive handling of missing/``None`` fields. The
conversion is exercised through the public ``plan_search_matches_from_list``
entry point the facade uses.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.plan_search.model import Plan, PlanSearchMatch
from sase.plan_search.wire import plan_search_matches_from_list

# The exact field set the Rust serde output carries for each wire struct. A
# rename on either side breaks this, which is the point.
PLAN_WIRE_KEYS = {
    "source",
    "kind",
    "path",
    "relpath",
    "name",
    "title",
    "status",
    "created_at",
    "prompt_link",
    "summary",
    "body",
    "frontmatter",
}
PLAN_SEARCH_MATCH_WIRE_KEYS = {"plan", "matched_fields", "score"}


def _plan_payload() -> dict[str, Any]:
    return {
        "source": "repo",
        "kind": "tale",
        "path": "/abs/sdd/plans/202606/auth_token_refresh.md",
        "relpath": "plans/202606/auth_token_refresh.md",
        "name": "auth_token_refresh",
        "title": "Refresh auth tokens on 401",
        "status": "wip",
        "created_at": "2026-06-18T21:29:20",
        "prompt_link": "sdd/prompts/202606/auth.md",
        "summary": "Retry the request once after refreshing the auth token.",
        "body": "# Refresh auth tokens on 401\n\nRetry the request...",
        "frontmatter": {
            "create_time": "2026-06-18 21:29:20",
            "status": "wip",
        },
    }


def _convert_one(match: dict[str, Any]) -> PlanSearchMatch:
    matches = plan_search_matches_from_list([match])
    assert len(matches) == 1
    return matches[0]


def test_dataclass_fields_match_wire_keys() -> None:
    """The dataclasses carry exactly the fields the wire shape carries."""
    match = _convert_one({"plan": _plan_payload(), "matched_fields": [], "score": 0.0})
    assert set(asdict(match).keys()) == PLAN_SEARCH_MATCH_WIRE_KEYS
    assert set(asdict(match.plan).keys()) == PLAN_WIRE_KEYS


def test_full_payload_round_trips() -> None:
    match = _convert_one(
        {
            "plan": _plan_payload(),
            "matched_fields": ["title", "body"],
            "score": 110.0,
        }
    )
    assert match.matched_fields == ["title", "body"]
    assert match.score == 110.0
    assert match.plan == Plan(
        source="repo",
        kind="tale",
        path="/abs/sdd/plans/202606/auth_token_refresh.md",
        relpath="plans/202606/auth_token_refresh.md",
        name="auth_token_refresh",
        title="Refresh auth tokens on 401",
        status="wip",
        created_at="2026-06-18T21:29:20",
        prompt_link="sdd/prompts/202606/auth.md",
        summary="Retry the request once after refreshing the auth token.",
        body="# Refresh auth tokens on 401\n\nRetry the request...",
        frontmatter={
            "create_time": "2026-06-18 21:29:20",
            "status": "wip",
        },
    )


def test_missing_optional_fields_degrade_to_empty() -> None:
    """A partial/local payload (no frontmatter, blank fields) does not raise."""
    match = _convert_one(
        {
            "plan": {
                "source": "local",
                "kind": "local",
                "path": "/abs/.sase/plans/old_plan.md",
                "relpath": "old_plan.md",
                "name": "old_plan",
                "title": "Old Plan",
                "status": None,
                "created_at": "2026-01-01T00:00:00",
                "prompt_link": None,
                "summary": None,
                "body": "body",
                "frontmatter": None,
            },
            "matched_fields": [],
            "score": 1.0,
        }
    )
    assert match.plan.status == ""
    assert match.plan.prompt_link == ""
    assert match.plan.summary == ""
    assert match.plan.frontmatter == {}
    # Browse-mode matches carry no matched fields.
    assert match.matched_fields == []


def test_matches_from_list_preserves_order() -> None:
    first = _plan_payload()
    second = _plan_payload()
    second["name"] = "second"
    matches = plan_search_matches_from_list(
        [
            {"plan": first, "matched_fields": ["title"], "score": 100.0},
            {"plan": second, "matched_fields": ["name"], "score": 60.0},
        ]
    )
    assert [match.plan.name for match in matches] == [
        "auth_token_refresh",
        "second",
    ]
    assert [match.score for match in matches] == [100.0, 60.0]
