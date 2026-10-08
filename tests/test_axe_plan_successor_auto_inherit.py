"""Tests for plan-chain successor auto-state inheritance (inherit_mode).

Phase and land workers run under ``%auto:tale``. The in-process coder after
plan approval and the feedback replanner seed from the predecessor's live
``agent_meta.json``: a ``%auto:tale`` planner's successor keeps ``:tale``,
and an ``A`` toggle-off before approval leaves the successor with no auto.
"""

import json
from pathlib import Path

import pytest

from sase.axe import run_agent_exec_plan as plan_mod
from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.agent_meta import (
    live_plan_successor_meta,
    plan_successor_auto_relationships,
)
from sase.axe.run_agent_helpers import create_followup_artifacts
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import (
    patch_plan_deps,
    run_plan_approval,
    write_plan_file,
)
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

pytestmark = pytest.mark.usefixtures(patch_plan_deps.__name__)

TALE_LIVE_META = {
    "suffix": ".plan",
    "auto_approve_argument": "tale",
    "auto_approve_plan_action": "tale",
    "plan": True,
}


def _write_live_meta(state, meta: dict) -> None:
    Path(state.current_artifacts_dir, "agent_meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )


def test_live_plan_successor_meta_inherits_tale_keys(tmp_path) -> None:
    """A stale snapshot gains the live ``:tale`` keys."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "agent_meta.json").write_text(
        json.dumps(TALE_LIVE_META), encoding="utf-8"
    )

    seeded = live_plan_successor_meta(live_dir, {"model": "default"})

    assert seeded["auto_approve_argument"] == "tale"
    assert seeded["auto_approve_plan_action"] == "tale"
    assert plan_successor_auto_relationships(seeded) == {
        "auto_approve_argument": "tale",
        "auto_approve_plan_action": "tale",
    }


def test_live_plan_successor_meta_toggle_off_strips_stale_keys(tmp_path) -> None:
    """Live absence removes stale snapshot keys, including their absence."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "agent_meta.json").write_text(
        json.dumps({"suffix": ".plan"}), encoding="utf-8"
    )

    seeded = live_plan_successor_meta(
        live_dir,
        {
            "model": "default",
            "approve": True,
            "auto_approve_argument": "tale",
            "auto_approve_plan_action": "tale",
        },
    )

    assert "approve" not in seeded
    assert "auto_approve_argument" not in seeded
    assert "auto_approve_plan_action" not in seeded
    assert plan_successor_auto_relationships(seeded) == {}


def test_live_plan_successor_meta_drops_legacy_plan_action(tmp_path) -> None:
    """A legacy ``"plan"`` action never carries to the successor."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "auto_approve_argument": "plan",
                "auto_approve_plan_action": "plan",
            }
        ),
        encoding="utf-8",
    )

    seeded = live_plan_successor_meta(live_dir, {"model": "default"})

    assert seeded["auto_approve_argument"] == "plan"
    assert "auto_approve_plan_action" not in seeded
    assert plan_successor_auto_relationships(seeded) == {
        "auto_approve_argument": "plan",
    }


def test_live_plan_successor_meta_missing_disk_passes_through(tmp_path) -> None:
    """No usable disk meta leaves the snapshot untouched (a copy)."""
    base = {"model": "default", "approve": True}

    seeded = live_plan_successor_meta(tmp_path / "absent", base)

    assert seeded == base
    assert seeded is not base


def test_coder_successor_inherits_live_tale_auto(tmp_path) -> None:
    """The coder of a ``%auto:tale`` planner keeps ``:tale``."""
    ctx = make_ctx(tmp_path)
    ctx.agent_meta = {"model": "default"}
    state = make_state(tmp_path)
    _write_live_meta(state, TALE_LIVE_META)
    plan_file = write_plan_file(tmp_path)
    approval = PlanApprovalResult(action="approve", plan_file=plan_file)

    run_plan_approval(tmp_path, approval=approval, ctx=ctx, state=state)

    assert accept_mod.create_followup_artifacts.call_count == 1
    _, base_meta, *_ = accept_mod.create_followup_artifacts.call_args.args
    relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
        "relationships"
    ]
    assert base_meta["auto_approve_argument"] == "tale"
    assert base_meta["auto_approve_plan_action"] == "tale"
    assert relationships["auto_approve_argument"] == "tale"
    assert relationships["auto_approve_plan_action"] == "tale"


def test_coder_successor_has_no_auto_after_toggle_off(tmp_path) -> None:
    """``A`` off before approval leaves the coder with no auto."""
    ctx = make_ctx(tmp_path)
    ctx.agent_meta = {
        "model": "default",
        "approve": True,
        "auto_approve_argument": "tale",
        "auto_approve_plan_action": "tale",
    }
    state = make_state(tmp_path)
    _write_live_meta(state, {"suffix": ".plan"})
    plan_file = write_plan_file(tmp_path)
    approval = PlanApprovalResult(action="approve", plan_file=plan_file)

    run_plan_approval(tmp_path, approval=approval, ctx=ctx, state=state)

    _, base_meta, *_ = accept_mod.create_followup_artifacts.call_args.args
    relationships = accept_mod.create_followup_artifacts.call_args.kwargs[
        "relationships"
    ]
    assert "approve" not in base_meta
    assert "auto_approve_argument" not in base_meta
    assert "auto_approve_plan_action" not in base_meta
    assert "auto_approve_argument" not in relationships
    assert "auto_approve_plan_action" not in relationships


def test_feedback_replanner_inherits_live_tale_auto(tmp_path) -> None:
    """The feedback replanner keeps the planner's live ``:tale`` state."""
    ctx = make_ctx(tmp_path)
    ctx.agent_meta = {"model": "default"}
    state = make_state(tmp_path)
    _write_live_meta(state, TALE_LIVE_META)
    plan_file = write_plan_file(tmp_path)
    approval = PlanApprovalResult(
        action="feedback",
        plan_file=plan_file,
        feedback="Add failure handling",
    )

    run_plan_approval(tmp_path, approval=approval, ctx=ctx, state=state)

    _, base_meta, *_ = plan_mod.create_followup_artifacts.call_args.args
    relationships = plan_mod.create_followup_artifacts.call_args.kwargs["relationships"]
    assert base_meta["auto_approve_argument"] == "tale"
    assert base_meta["auto_approve_plan_action"] == "tale"
    assert relationships["auto_approve_argument"] == "tale"
    assert relationships["auto_approve_plan_action"] == "tale"


def test_followup_artifacts_persist_relationship_auto_keys(tmp_path) -> None:
    """Relationship-carried auto keys land in the successor meta file."""
    from unittest.mock import patch

    followup = tmp_path / "followup-auto"
    followup.mkdir()
    with patch(
        "sase.axe.run_agent_helpers.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "test_proj",
            {"model": "opus"},
            "--code",
            "20260711120000",
            relationships={
                "plan_path": str(tmp_path / "plan.md"),
                "auto_approve_argument": "tale",
                "auto_approve_plan_action": "tale",
            },
        )

    meta = json.loads((followup / "agent_meta.json").read_text())
    assert meta["auto_approve_argument"] == "tale"
    assert meta["auto_approve_plan_action"] == "tale"
