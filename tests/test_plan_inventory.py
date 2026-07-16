"""Tests for ``sase plan list`` inventory classification and filtering."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sase.main.plan_inventory import build_plan_inventory, plan_inventory_to_json
from tests._plan_inventory_helpers import (
    append_plan_notification as _append_plan_notification,
    archived_plan as _archived_plan,
    live_agent as _live_agent,
    response_dir as _response_dir,
    set_plan_tier as _set_plan_tier,
    write_agent_meta as _write_agent_meta,
    write_sharded_agent_meta as _write_sharded_agent_meta,
)


def test_build_plan_inventory_classifies_proposed_approved_and_rejected(
    tmp_path: Path,
) -> None:
    proposed_plan = _archived_plan("proposed.md", minutes_ago=30)
    approved_plan = _archived_plan("approved.md", minutes_ago=20)
    rejected_plan = _archived_plan("rejected.md", minutes_ago=10)
    response_dir = _response_dir(tmp_path, "proposed")
    _append_plan_notification(
        "abcdef12-plan-notification",
        proposed_plan,
        response_dir,
        minutes_ago=4,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613120000",
        {
            "plan_approved": True,
            "plan_action": "tale",
            "plan_path": str(approved_plan),
            "name": "approved-agent",
            "llm_provider": "openai",
            "model": "gpt-5",
        },
        minutes_ago=2,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(),),
    ):
        inventory = build_plan_inventory()
    payload = plan_inventory_to_json(inventory)

    assert payload["summary"] == {
        "proposed": 1,
        "approved_shown": 1,
        "rejected_shown": 1,
        "total_archived_proposals": 3,
    }
    assert payload["proposed"][0]["id_prefix"] == "abcdef12"
    assert payload["proposed"][0]["agent"] == "planner"
    assert payload["proposed"][0]["project"] == "demo-project"
    assert payload["proposed"][0]["provider_model"] == "anthropic/claude-sonnet"
    assert payload["proposed"][0]["title"] == "Proposed"
    assert payload["approved"][0]["action"] == "tale"
    assert payload["approved"][0]["agent"] == "approved-agent"
    assert payload["approved"][0]["provider_model"] == "openai/gpt-5"
    assert payload["approved"][0]["title"] == "Approved"
    assert payload["rejected"][0]["plan_path"].endswith("/rejected.md")
    assert payload["rejected"][0]["title"] == "Rejected"
    assert "inferred from archived proposal" in str(payload["rejected"][0]["note"])
    assert str(rejected_plan) in payload["rejected"][0]["plan_path"].replace(
        "~/.sase", str(Path(os.environ["SASE_HOME"]).expanduser())
    )


def test_inventory_dedupes_approved_by_plan_path_and_applies_limits() -> None:
    shared_plan = _archived_plan("shared.md", minutes_ago=50)
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613110000",
        {
            "plan_approved": True,
            "plan_action": "approve",
            "plan_path": str(shared_plan),
        },
        minutes_ago=40,
    )
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613140000",
        {
            "plan_approved": True,
            "plan_action": "epic",
            "plan_path": str(shared_plan),
        },
        minutes_ago=1,
    )
    for index in range(12):
        plan = _archived_plan(f"approved-{index:02d}.md", minutes_ago=80 + index)
        _write_agent_meta(
            "demo",
            "workflow-plan",
            f"2026061313{index:02d}00",
            {
                "plan_approved": True,
                "plan_action": "epic",
                "plan_path": str(plan),
            },
            minutes_ago=10 + index,
        )
    for index in range(12):
        _archived_plan(f"rejected-{index:02d}.md", minutes_ago=20 + index)

    inventory = build_plan_inventory(limit=10)
    payload = plan_inventory_to_json(inventory)

    approved_paths = [row["plan_path"] for row in payload["approved"]]
    shared_rows = [
        row
        for row in payload["approved"]
        if str(row["plan_path"]).endswith("/shared.md")
    ]
    assert len(payload["approved"]) == 10
    assert len(set(approved_paths)) == 10
    assert shared_rows == [
        {
            "timestamp": shared_rows[0]["timestamp"],
            "age": shared_rows[0]["age"],
            "action": "epic",
            "agent": "-",
            "project": "demo",
            "provider_model": "-",
            "plan_path": shared_rows[0]["plan_path"],
            "title": "Shared",
            "tier": "-",
            "meta_path": shared_rows[0]["meta_path"],
        }
    ]
    assert len(payload["rejected"]) == 10
    assert all(
        not str(row["plan_path"]).endswith("/rejected-11.md")
        for row in payload["rejected"]
    )

    unlimited_payload = plan_inventory_to_json(build_plan_inventory(limit=0))
    assert len(unlimited_payload["approved"]) == 13
    assert len(unlimited_payload["rejected"]) == 12
    assert unlimited_payload["summary"]["limit"] == 0


def test_inventory_limit_never_hides_proposed_rows(tmp_path: Path) -> None:
    plans = [
        _archived_plan(f"proposed-{index}.md", minutes_ago=index + 1)
        for index in range(2)
    ]
    for index, plan in enumerate(plans):
        _append_plan_notification(
            f"{index:08d}-plan-notification",
            plan,
            _response_dir(tmp_path, f"proposed-{index}"),
            minutes_ago=index + 1,
            agent_timestamp=f"2026061312{index:02d}00",
        )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(
            _live_agent(raw_suffix="20260613120000"),
            _live_agent(raw_suffix="20260613120100"),
        ),
    ):
        payload = plan_inventory_to_json(build_plan_inventory(limit=1))

    assert len(payload["proposed"]) == 2
    assert payload["summary"]["proposed"] == 2


def test_inventory_includes_day_sharded_approved_plan() -> None:
    legacy_plan = _archived_plan("legacy-approved.md", minutes_ago=180)
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613090000",
        {
            "plan_approved": True,
            "plan_action": "approve",
            "plan_path": str(legacy_plan),
        },
        minutes_ago=180,
    )
    sharded_plan = _archived_plan("sharded-approved.md", minutes_ago=2)
    _write_sharded_agent_meta(
        "demo",
        "workflow-plan",
        "20260617070000",
        {
            "plan_approved": True,
            "plan_action": "tale",
            "plan_path": str(sharded_plan),
        },
        minutes_ago=2,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    approved_paths = [str(row["plan_path"]) for row in payload["approved"]]
    assert any(path.endswith("/sharded-approved.md") for path in approved_paths)
    assert any(path.endswith("/legacy-approved.md") for path in approved_paths)
    rejected_paths = [str(row["plan_path"]) for row in payload["rejected"]]
    assert all(not path.endswith("/sharded-approved.md") for path in rejected_paths)


def test_inventory_tier_filter_and_json_breakdown() -> None:
    epic = _archived_plan("approved-epic.md", minutes_ago=2)
    tale = _archived_plan("rejected-tale.md", minutes_ago=3)
    _set_plan_tier(epic, "epic")
    _set_plan_tier(tale, "tale")
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {
            "plan_approved": True,
            "plan_action": "epic",
            "plan_path": str(epic),
        },
        minutes_ago=1,
    )

    payload = plan_inventory_to_json(build_plan_inventory(tiers=("epic",)))

    assert [row["tier"] for row in payload["approved"]] == ["epic"]
    assert payload["rejected"] == []
    assert payload["summary"]["tier_filter"] == ["epic"]
    assert payload["summary"]["by_tier"] == {"tale": 0, "epic": 1}


def test_inventory_status_filter_is_a_json_view_not_collection_change() -> None:
    approved = _archived_plan("approved.md", minutes_ago=3)
    _archived_plan("rejected.md", minutes_ago=2)
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {
            "plan_approved": True,
            "plan_action": "approve",
            "plan_path": str(approved),
        },
        minutes_ago=1,
    )

    payload = plan_inventory_to_json(
        build_plan_inventory(statuses=("rejected", "rejected"))
    )

    assert "proposed" not in payload
    assert "approved" not in payload
    assert len(payload["rejected"]) == 1
    assert str(payload["rejected"][0]["plan_path"]).endswith("/rejected.md")
    assert payload["summary"] == {
        "proposed": 0,
        "approved_shown": 1,
        "rejected_shown": 1,
        "total_archived_proposals": 2,
        "status_filter": ["rejected"],
    }


def test_inventory_status_and_tier_filters_compose() -> None:
    epic = _archived_plan("approved-epic.md", minutes_ago=2)
    _set_plan_tier(epic, "epic")
    _write_agent_meta(
        "demo",
        "workflow-plan",
        "20260613150000",
        {
            "plan_approved": True,
            "plan_action": "epic",
            "plan_path": str(epic),
        },
        minutes_ago=1,
    )

    payload = plan_inventory_to_json(
        build_plan_inventory(
            limit=25,
            statuses=("approved",),
            tiers=("epic",),
        )
    )

    assert set(payload) == {"summary", "approved"}
    assert [row["tier"] for row in payload["approved"]] == ["epic"]
    assert payload["summary"]["status_filter"] == ["approved"]
    assert payload["summary"]["tier_filter"] == ["epic"]
    assert payload["summary"]["limit"] == 25


def test_inventory_keeps_malformed_historical_plan_with_null_title() -> None:
    valid = _archived_plan("valid.md", minutes_ago=2, title="Readable history")
    malformed = _archived_plan("malformed.md", minutes_ago=1)
    malformed.write_text("---\ntitle: [unterminated\n---\n# Broken\n", encoding="utf-8")

    payload = plan_inventory_to_json(build_plan_inventory())

    rejected = {Path(str(row["plan_path"])).name: row for row in payload["rejected"]}
    assert rejected[valid.name]["title"] == "Readable history"
    assert rejected[malformed.name]["title"] is None
    assert rejected[malformed.name]["tier"] == "-"
