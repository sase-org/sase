"""Gate-shell creation stamps pending-member identity and pulses after it exists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.paths import sase_projects_dir
from sase.gate_shell import transaction as transaction_module
from sase.gate_shell.transaction import create_gate_shell
from sase.notification_gates.model_validation import GateError

from tests.gate_shell.test_transaction_gate_intent import (
    _creation_result,
    _install_transaction_fakes,
    _set_agent_env,
    _shell_gate_spec,
)


def _planner_action_data(planner_dir: Path) -> dict[str, str]:
    return {
        "artifacts_dir": str(planner_dir),
        "agent_timestamp": "20260919072902",
        "agent_root_timestamp": "20260919072902",
    }


def test_create_gate_shell_stamps_action_data_and_pulses_after_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _set_agent_env(tmp_path, monkeypatch)
    artifacts_root = sase_projects_dir() / "proj" / "artifacts"
    artifacts_root.mkdir(parents=True)
    member_dir = tmp_path / "20260919074517"
    member_dir.mkdir()
    planner_dir = tmp_path / "planner"
    planner_dir.mkdir()
    captured: dict[str, Any] = {}

    def fake_create_gate(spec: Any) -> Any:
        pulse = artifacts_root / ".ace_refresh_pulse"
        captured["action_data"] = dict(spec.presentation.get("action_data") or {})
        captured["pulse_during_create_gate"] = pulse.exists()
        return _creation_result(tmp_path)

    _install_transaction_fakes(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transaction_module,
        "create_gate_shell_member",
        lambda *args, **kwargs: str(member_dir),
    )
    monkeypatch.setattr(transaction_module, "create_gate", fake_create_gate)

    spec = _shell_gate_spec()
    spec["presentation"]["action_data"] = _planner_action_data(planner_dir)

    create_gate_shell(spec)

    pulse = artifacts_root / ".ace_refresh_pulse"
    action_data = captured["action_data"]
    assert captured["pulse_during_create_gate"] is False
    assert pulse.is_file()
    assert "ace-run" not in pulse.relative_to(artifacts_root).as_posix()
    assert pulse.stat().st_mtime >= member_dir.stat().st_mtime
    assert action_data["raw_suffix"] == "20260919074517"
    assert action_data["artifacts_dir"] == str(planner_dir)
    assert action_data["agent_timestamp"] == "20260919072902"
    assert action_data["agent_root_timestamp"] == "20260919072902"
    assert action_data["family_root_suffix"] == "20260919072902"


def test_failed_create_gate_does_not_pulse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _set_agent_env(tmp_path, monkeypatch)
    artifacts_root = sase_projects_dir() / "proj" / "artifacts"
    artifacts_root.mkdir(parents=True)
    _install_transaction_fakes(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transaction_module,
        "create_gate",
        lambda _spec: (_ for _ in ()).throw(
            GateError("invalid", "gate", "create failed")
        ),
    )

    with pytest.raises(GateError, match="create failed"):
        create_gate_shell(_shell_gate_spec())

    assert not (artifacts_root / ".ace_refresh_pulse").exists()
