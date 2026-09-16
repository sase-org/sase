"""Agent-side gate-shell handoff and the package's lazy export table."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest

import sase.gate_shell as gate_shell_package
from sase.gate_shell import (
    GATE_PENDING_MARKER,
    maybe_handoff_gate_from_agent,
    will_handoff_gate_to_agent_runner,
)
from sase.gate_shell.models import GateShellRecord, GateShellState


@pytest.mark.parametrize(
    ("name", "target"),
    sorted(gate_shell_package._LAZY_EXPORTS.items()),
)
def test_every_lazy_export_resolves(name: str, target: tuple[str, str]) -> None:
    module_name, attribute = target
    assert hasattr(import_module(module_name), attribute)
    assert getattr(gate_shell_package, name) is not None


def _record(gate_state: GateShellState = "pending") -> GateShellRecord:
    return GateShellRecord(
        gate_id="g123",
        member_agent_name="agent--gate",
        lane="agent",
        project_name="proj",
        artifacts_dir="/tmp/member",
        timestamp="20260916120000",
        kind="sudo",
        gate_state=gate_state,
        start_status="WAITING",
        stop_status="ANSWERED",
        accent="yellow",
        label="sudo",
        reason="test",
        creator_agent="agent",
        bundle_path=None,
        notification_id=None,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="release",
    )


def test_will_handoff_gate_to_agent_runner_follows_sase_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    assert will_handoff_gate_to_agent_runner() is False
    monkeypatch.setenv("SASE_AGENT", "1")
    assert will_handoff_gate_to_agent_runner() is True


def test_maybe_handoff_gate_from_agent_writes_marker_and_kills_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "202609" / "16"
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with patch("sase.main.utils.kill_agent_runner_group") as kill:
        assert maybe_handoff_gate_from_agent(_record()) is True

    marker = json.loads((artifacts_dir / GATE_PENDING_MARKER).read_text())
    assert marker["gate_id"] == "g123"
    assert marker["member_artifacts_dir"] == "/tmp/member"
    assert marker["member_agent_name"] == "agent--gate"
    assert marker["kind"] == "sudo"
    kill.assert_called_once_with(str(artifacts_dir))


def test_maybe_handoff_gate_from_agent_skips_terminal_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    with patch("sase.main.utils.kill_agent_runner_group") as kill:
        assert maybe_handoff_gate_from_agent(_record("answered")) is False

    assert not (tmp_path / GATE_PENDING_MARKER).exists()
    kill.assert_not_called()


def test_maybe_handoff_gate_from_agent_is_noop_outside_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    assert maybe_handoff_gate_from_agent(_record()) is False
    assert not (tmp_path / GATE_PENDING_MARKER).exists()
