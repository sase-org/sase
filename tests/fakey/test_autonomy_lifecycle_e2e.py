"""Fakey ``%auto:tale`` lifecycle e2e (``%auto`` E1 ``cli`` phase).

Scenario: a ``%auto:tale`` planner, its auto-approved tale plan, the
coder (inherits ``tale``), a monitor started by the coder, the monitor
follow-up (inherits ``tale``), a gate created by the follow-up, and the
gate follow-up (inherits ``tale``). The epic plan proposed in the gate
follow-up parks. In a second scenario, ``A`` off mid-chain makes the next
follow-up park.

This is function-driven, not provider-driven: it drives the real
successor helper (``create_followup_artifacts``, which the inherit phase
wired for in-process coders, question successors, pipe, gate-turn
members, and monitor members) and the real gate creation (execution
side effects stubbed, as in the contract harness). No provider is
invoked and nothing on the decision path is mocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.autonomy.record import read_record

from tests.autonomy_contract import harness
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _gate_policies(
    artifacts_dir: Path,
    tale_plan: Path,
    epic_plan: Path,
    monkeypatch: Any,
    tag: str,
) -> dict[str, dict[str, Any]]:
    """Create real tale and epic gates from live meta; return policies."""
    from sase.plan_gate import build_plan_approval_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    policies: dict[str, dict[str, Any]] = {}
    for kind, plan_file in (("plan", tale_plan), ("epic_plan", epic_plan)):
        auto_action = get_auto_plan_approval_action()
        auto_argument = get_auto_plan_approval_argument()
        if auto_argument is None and auto_action in {"tale", "epic"}:
            auto_argument = auto_action
        spec = build_plan_approval_gate_spec(
            str(plan_file),
            f"{kind}-{tag}",
            auto_enabled=auto_action is not None,
            auto_argument=auto_argument,
        )
        gate = harness.create_plan_gate_isolated(spec, artifacts_dir, f"{kind}-{tag}")
        resolved = gate.to_dict().get("auto_resolution") or {}
        policies[kind] = dict(resolved.get("policy") or {})
        policies[f"{kind}_state"] = {"state": resolved.get("state")}
    return policies


def _successor(
    live_meta: dict[str, Any], tmp_path: Path, suffix: str
) -> tuple[dict[str, Any], Path]:
    meta = harness.adapt_followup_artifacts(live_meta, tmp_path, suffix=suffix)
    follower_dir = tmp_path / f"chain{suffix}"
    follower_dir.mkdir(exist_ok=True)
    harness.write_meta(follower_dir, meta)
    return meta, follower_dir


def test_tale_lifecycle_inherits_to_gate_followup(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A ``%auto:tale`` chain inherits to the gate follow-up; epics park."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    # The planner launches with `%auto:tale` through the real launch path.
    _, planner_meta, planner_dir = harness.launch_meta(
        "%auto:tale\nDo the work", workdir
    )
    assert read_record(planner_meta)["profile"] == "tale"

    # Its tale plan auto-approves with policy `auto`.
    policies = _gate_policies(planner_dir, tale_plan, epic_plan, monkeypatch, "planner")
    assert policies["plan"]["outcome"] == "auto"
    assert policies["plan"]["value"] == "approve_archive"

    # The coder inherits `tale` structurally through the real helper.
    coder_meta, _ = _successor(planner_meta, tmp_path, "--code")
    coder_record = read_record(coder_meta)
    assert coder_record is not None
    assert coder_record["profile"] == "tale"
    assert coder_record["source"] == "inherited"

    # A monitor started by the coder, and its follow-up, inherit `tale`.
    monitor_meta, _ = _successor(coder_meta, tmp_path, "--monitor")
    assert read_record(monitor_meta)["profile"] == "tale"
    followup_meta, followup_dir = _successor(monitor_meta, tmp_path, "--followup")
    assert read_record(followup_meta)["profile"] == "tale"

    # A gate created by the follow-up auto-resolves its tale plan ...
    followup_policies = _gate_policies(
        followup_dir, tale_plan, epic_plan, monkeypatch, "followup"
    )
    assert followup_policies["plan"]["outcome"] == "auto"

    # ... and the gate follow-up inherits `tale` ...
    gate_followup_meta, gate_followup_dir = _successor(
        followup_meta, tmp_path, "--gate"
    )
    assert read_record(gate_followup_meta)["profile"] == "tale"

    # ... so the epic plan proposed there parks for a human.
    gate_followup_policies = _gate_policies(
        gate_followup_dir, tale_plan, epic_plan, monkeypatch, "gate-followup"
    )
    assert gate_followup_policies["epic_plan"]["outcome"] == "ask"
    assert gate_followup_policies["epic_plan_state"]["state"] == "disabled"


def test_a_off_mid_chain_parks_next_followup(tmp_path: Path, monkeypatch: Any) -> None:
    """``A`` off mid-chain means the next follow-up parks everything."""
    from sase.ace.tui.actions.agents._directive_persistence import (
        persist_autonomy_toggle,
    )

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    _, planner_meta, _ = harness.launch_meta("%auto:tale\nDo the work", workdir)
    coder_meta, _ = _successor(planner_meta, tmp_path, "--code")
    followup_meta, followup_dir = _successor(coder_meta, tmp_path, "--followup")
    assert read_record(followup_meta)["profile"] == "tale"

    # `A` off on the live follow-up through the real toggle mutation.
    (followup_dir / "raw_prompt.md").write_text(
        "%auto:tale\nDo the work", encoding="utf-8"
    )
    persist_autonomy_toggle(followup_dir, "manual", surface="tui")
    toggled = harness.read_meta(followup_dir)
    assert read_record(toggled)["profile"] == "manual"

    # The next follow-up is manual: tale and epic plans both park.
    next_meta, next_dir = _successor(toggled, tmp_path, "--after-off")
    assert read_record(next_meta)["profile"] == "manual"
    policies = _gate_policies(next_dir, tale_plan, epic_plan, monkeypatch, "after")
    assert policies["plan"]["outcome"] == "ask"
    assert policies["epic_plan"]["outcome"] == "ask"
