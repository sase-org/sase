"""Scope basics for Enter-on-agent: patch, gate row, and silent rows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._patch_navigation import (
    AgentPatchNavigationMixin,
)
from sase.ace.tui.models.agent import AgentType

from ._agent_enter_targets_helpers import (
    _gate_row,
    _resolve,
    _sources,
)
from ._agent_unread_helpers import make_agent


def test_standalone_patch_only_row() -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.kind == "patch"
    assert target.source == "patch"
    assert target.key == "patch:demo"
    assert target.label == "Go to Patch"
    assert target.patch_name == "demo"
    assert resolution.primary == target
    assert resolution.empty_message is None


def test_patch_sentinels_have_no_patch_target() -> None:
    for name in ("~", "unknown"):
        agent = make_agent(name=name, raw_suffix="20260918010102")
        resolution = _resolve(agent)
        assert resolution.targets == ()


def test_patch_mixin_rejects_running_marker() -> None:
    class _PatchApp(AgentPatchNavigationMixin):
        _agents_with_children: list = []

    app = _PatchApp()
    assert (
        app._resolve_agent_cl_name(make_agent(name="~", raw_suffix="20260918010103"))
        is None
    )
    assert (
        app._resolve_agent_cl_name(
            make_agent(name="unknown", raw_suffix="20260918010104")
        )
        is None
    )
    assert (
        app._resolve_agent_cl_name(make_agent(name="real", raw_suffix="20260918010105"))
        == "real"
    )


def test_pending_sudo_gate_row() -> None:
    agent = _gate_row("010101", notification_id="n-sudo")
    resolution = _resolve(agent)
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.kind == "gate"
    assert target.source == "gate_row"
    assert target.key == "gate:gate-abc123"
    assert target.label == "Review sudo request"
    assert target.badge is not None and target.badge.startswith("SUDO")
    assert target.notification_id == "n-sudo"
    assert target.gate_id == "gate-abc123"


@pytest.mark.parametrize(
    ("kind", "start_status", "label", "expected"),
    [
        ("launch", "LAUNCH", None, "Approve agent launch"),
        ("hitl", "HITL", None, "Respond to checkpoint"),
        ("plan", "TALE", None, "Review tale plan"),
        ("plan", "PLAN", None, "Review plan"),
        ("epic_plan", "EPIC", None, "Review epic plan"),
        ("task_triage", "GATE", None, "Triage task"),
        ("custom", "GATE", "Do the thing", "Do the thing"),
        ("custom", "GATE", None, "Open gate"),
        ("mystery", "GATE", None, "Open gate"),
    ],
)
def test_gate_row_labels(
    kind: str, start_status: str, label: str | None, expected: str
) -> None:
    agent = _gate_row(
        "020202",
        gate_id=f"gate-{kind}",
        kind=kind,
        start_status=start_status,
        label=label,
    )
    [target] = _resolve(agent).targets
    assert target.label == expected


def test_settled_gate_row_reports_settled_message() -> None:
    agent = _gate_row(
        "030303",
        state="answered",
        stop_time=datetime(2026, 9, 18, 13, 0, 0),
        stop_status="APPROVED",
    )
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "This gate already settled (APPROVED)"


def test_settling_gate_row_is_not_a_target() -> None:
    agent = _gate_row("040404", state="settling")
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "This gate already settled (settling)"


def test_container_mirroring_gate_state_has_no_phantom_gate() -> None:
    container = replace(
        make_agent(name="fam-root", raw_suffix="20260918010101"),
        agent_family_role="root",
        agent_family="fam",
        agent_name="starter",
        gate_state="pending",
        gate_start_status="SUDO",
        followup_agents=[],
    )
    assert container.is_gate is False
    resolution = _resolve(container)
    assert "gate_row" not in _sources(resolution)


def test_clan_container_points_inside() -> None:
    agent = replace(
        make_agent(name="clan-row", raw_suffix="20260918010101"),
        is_clan_container=True,
        agent_clan="testclan",
    )
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "Select an agent inside this clan"


def test_monitor_and_proc_rows_are_silent() -> None:
    monitor = replace(
        make_agent(name="mon", raw_suffix="20260918010101"),
        agent_family_role="monitor",
    )
    assert monitor.is_monitor is True
    assert _resolve(monitor).targets == ()

    proc = replace(
        make_agent(name="proc", raw_suffix="20260918010102"),
        agent_type=AgentType.PROC_SHELL,
    )
    assert proc.is_proc_shell is True
    assert _resolve(proc).targets == ()
