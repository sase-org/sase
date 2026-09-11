"""CLI answered-gate --resume uses the stored answer and rejects conflicts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import read_gate_shell_marker
from sase.notification_gates.cli_answer import _resume_answered_shell
from sase.notification_gates.cli_support import GateCliError
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.service import create_gate
from sase.shells.followup import FollowupLaunchResult
from tests.gate_shell._settlement_followup_helpers import (
    DEFAULT_SHELL,
    gate_spec,
    make_gate_shell_member,
    sandbox_home,
)

__all__ = ["sandbox_home"]


def _bundle(request_id: str) -> Any:
    from sase.notification_gates.cli_support import resolve_gate_cli_bundle

    return resolve_gate_cli_bundle("custom", request_id)


def test_answered_resume_rejects_conflicting_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "resume-conflict"
    gate = create_gate(gate_spec(request_id, shell=DEFAULT_SHELL))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=DEFAULT_SHELL
    )
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    monkeypatch.setattr(
        "sase.gate_shell.handoff_launch.launch_gate_followup_agent",
        lambda *a, **k: FollowupLaunchResult(launched=True, agent_name="lane--1"),
    )
    settle_gate_shell(record, gate_state="answered", reason="gate answered")
    record = read_gate_shell_marker("proj", artifacts_dir)
    monkeypatch.setattr(
        "sase.notification_gates.cli_answer.find_gate_shell_by_gate_id",
        lambda *a, **k: record,
    )

    bundle = _bundle(request_id)
    with pytest.raises(GateCliError, match="stored options"):
        _resume_answered_shell(
            bundle,
            selected_ids=["reject"],
            input_data=None,
            option_inputs=None,
            feedback=None,
        )


def test_answered_resume_after_success_reports_the_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "resume-success"
    gate = create_gate(gate_spec(request_id, shell=DEFAULT_SHELL))
    artifacts_dir = make_gate_shell_member(
        request_id, gate.bundle_path, shell=DEFAULT_SHELL
    )
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    def fake_launcher(
        called_dir: str, meta: dict, **kwargs: object
    ) -> FollowupLaunchResult:
        del kwargs
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

        meta["gate_followup_agent"] = "lane--1"
        update_meta_field(called_dir, "gate_followup_agent", "lane--1")
        return FollowupLaunchResult(launched=True, agent_name="lane--1")

    monkeypatch.setattr(
        "sase.gate_shell.handoff_launch.launch_gate_followup_agent", fake_launcher
    )
    settle_gate_shell(record, gate_state="answered", reason="gate answered")
    record = read_gate_shell_marker("proj", artifacts_dir)
    monkeypatch.setattr(
        "sase.notification_gates.cli_answer.find_gate_shell_by_gate_id",
        lambda *a, **k: record,
    )

    payload = _resume_answered_shell(
        _bundle(request_id),
        selected_ids=["cleanup"],
        input_data=None,
        option_inputs=None,
        feedback=None,
    )
    assert payload["handoff_resumed"] is True
    assert payload["followup_agent"] == "lane--1"
    assert payload["already_answered"] is True
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_followup_outcome"] == "launched"
