"""Tests for matching pending plan proposals to live agents."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.main.plan_inventory import build_plan_inventory, plan_inventory_to_json
from tests._plan_inventory_helpers import (
    LIVE_AGENT_ROOT_TS as _LIVE_AGENT_ROOT_TS,
    append_plan_notification as _append_plan_notification,
    archived_plan as _archived_plan,
    live_agent as _live_agent,
    response_dir as _response_dir,
)


def test_plan_inventory_excludes_proposal_without_matching_live_agent(
    tmp_path: Path,
) -> None:
    plan = _archived_plan("orphan.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "orphan")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp="20260613130000",
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 0
    assert payload["summary"]["rejected_shown"] == 1
    assert str(payload["rejected"][0]["plan_path"]).endswith("/orphan.md")


def test_plan_inventory_matches_root_timestamp(tmp_path: Path) -> None:
    plan = _archived_plan("root.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "root")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_timestamp="20260613125900",
        agent_root_timestamp=_LIVE_AGENT_ROOT_TS,
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(raw_suffix=_LIVE_AGENT_ROOT_TS),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["id_prefix"] == "12345678"


def test_plan_inventory_matches_agent_name_with_timestamp(tmp_path: Path) -> None:
    plan = _archived_plan("named.md", minutes_ago=5)
    response_dir = _response_dir(tmp_path, "named")
    _append_plan_notification(
        "12345678-plan-notification",
        plan,
        response_dir,
        minutes_ago=5,
        agent_cl_name="other-cl",
        agent_name="planner",
    )

    with patch(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        return_value=(_live_agent(cl_name="demo-cl", agent_name="planner"),),
    ):
        payload = plan_inventory_to_json(build_plan_inventory())

    assert payload["summary"]["proposed"] == 1
    assert payload["proposed"][0]["agent"] == "planner"
