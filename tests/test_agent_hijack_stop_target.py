"""Hijack stop-target reads the model facts runners actually write."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack._stop_target import resolve_target
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running

_AGENT = "hijack-e2e--0"
_TS = "20261106120000"
_PID = 424242
_WS = 3
_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "agent_hijack"
    / "runner_agent_meta.json"
)


def _load_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _write_meta(
    tmp_path: Path,
    extra: dict[str, Any] | None = None,
    *,
    drop: tuple[str, ...] = (),
) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta = _load_fixture()
    for key in drop:
        meta.pop(key, None)
    if extra:
        meta.update(extra)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return artifacts


def _install_target(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, project_file: str
) -> None:
    def fake_fields(agent: Any) -> tuple[Any, str, str, str, bool]:
        return Path(agent.artifacts_dir), "proj", project_file, _TS, False

    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", fake_fields)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_target._claim_workspace_dir",
        lambda _project, _claim: None,
    )


def _deps(artifacts: Path, *, is_monitor: bool = False) -> StopDeps:
    row = SimpleNamespace(
        name=_AGENT,
        artifacts_dir=str(artifacts),
        status="RUNNING",
        pid=_PID,
        is_monitor=is_monitor,
        agent_session="hijack-e2e",
        workspace_num=_WS,
    )
    return StopDeps(
        find_agent=lambda name: (
            SimpleNamespace(name=_AGENT, artifacts_dir=str(artifacts))
            if name == _AGENT
            else None
        ),
        list_running=lambda: [row],
    )


def test_resolve_target_reads_runner_model_keys_from_captured_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _write_meta(tmp_path)
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WS,
                "ace(run)-20261106_120000",
                "feature",
                pid=_PID,
                artifacts_timestamp=_TS,
            )
        ],
    )
    _install_target(monkeypatch, artifacts, project_file)

    target = resolve_target(_AGENT, deps=_deps(artifacts, is_monitor=True))

    assert target is not None
    assert target.provider == "fakey"
    assert target.model == "fakey-large"
    assert target.effort == "high"
    assert target.capabilities == ["hijack"]
    assert (
        target.run_started_at
        == datetime.fromisoformat("2026-11-06T12:00:00+00:00").timestamp()
    )
    assert target.is_monitor_turn is False
    assert target.is_gate_turn is False
    assert target.gate_state is None


def test_resolve_target_falls_back_to_exec_llm_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _write_meta(
        tmp_path,
        extra={"exec_llm_provider": "claude"},
        drop=("llm_provider",),
    )
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WS,
                "ace(run)-20261106_120000",
                "feature",
                pid=_PID,
                artifacts_timestamp=_TS,
            )
        ],
    )
    _install_target(monkeypatch, artifacts, project_file)

    target = resolve_target(_AGENT, deps=_deps(artifacts))

    assert target is not None
    assert target.provider == "claude"


def test_resolve_target_classifies_monitor_from_durable_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _write_meta(
        tmp_path,
        extra={
            "agent_session": "hijack-e2e",
            "agent_session_role": "monitor",
            "turn_kind": "monitor",
            "monitor_id": "mon-1",
            "monitor_state": "running",
        },
    )
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WS,
                "ace(run)-20261106_120000",
                "feature",
                pid=_PID,
                artifacts_timestamp=_TS,
            )
        ],
    )
    _install_target(monkeypatch, artifacts, project_file)

    target = resolve_target(_AGENT, deps=_deps(artifacts, is_monitor=False))

    assert target is not None
    assert target.is_monitor_turn is True
    assert target.is_gate_turn is False


def test_resolve_target_classifies_gate_from_durable_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _write_meta(
        tmp_path,
        extra={
            "agent_session": "hijack-e2e",
            "agent_session_role": "gate",
            "turn_kind": "gate",
            "gate_id": "gate-1",
            "gate_state": "pending",
        },
    )
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                _WS,
                "ace(run)-20261106_120000",
                "feature",
                pid=_PID,
                artifacts_timestamp=_TS,
            )
        ],
    )
    _install_target(monkeypatch, artifacts, project_file)

    target = resolve_target(_AGENT, deps=_deps(artifacts))

    assert target is not None
    assert target.is_gate_turn is True
    assert target.gate_state == "pending"
    assert target.is_monitor_turn is False
