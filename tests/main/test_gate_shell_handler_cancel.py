"""Behavior tests for the ``sase gate cancel`` handler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.service import create_gate
from tests.gate_shell._cli_fixtures import (
    dispatch,
    gate_shell_home,
    make_gate_shell,
    patch_gate_shell_project_records,
)

__all__ = ["gate_shell_home"]

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps({'status': 'ok'}))\n"
)


def _spec(request_id: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {"icon": "🧪", "title": "T", "notes": ["n"]},
        "query": "cleanup",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            }
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND}
        ],
        "shell": {},
    }


def _make_pending_gate_shell(gate_id: str, member_name: str, lane: str) -> str:
    gate = create_gate(_spec(gate_id))
    artifacts_dir = make_gate_shell(
        "proj",
        "20260812120000",
        member_name,
        lane=lane,
        gate_id=gate_id,
    )
    import json as _json

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = _json.loads(meta_path.read_text())
    meta["gate_bundle_path"] = str(gate.bundle_path)
    meta_path.write_text(_json.dumps(meta), encoding="utf-8")
    return artifacts_dir


def test_cancel_settles_a_pending_gate_shell_as_stopped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts_dir = _make_pending_gate_shell("custom-1", "acme--gate", "acme")
    patch_gate_shell_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["gate", "cancel", "acme--gate"]) == 0

    out = capsys.readouterr().out
    assert "Cancelled" in out
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["gate_state"] == "stopped"
    paths = bundle_paths("custom", "custom-1")
    assert paths.cancellation.is_file()


def test_cancel_an_already_terminal_gate_shell_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts_dir = make_gate_shell(
        "proj",
        "20260812120000",
        "acme--gate",
        lane="acme",
        gate_id="custom-1",
        gate_state="failed",
    )
    patch_gate_shell_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["gate", "cancel", "acme--gate"]) == 0

    out = capsys.readouterr().out
    assert "already failed" in out


def test_cancel_unknown_reference_exits_with_ref_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_gate_shell_project_records(monkeypatch, [])

    assert dispatch(["gate", "cancel", "no-such-gate"]) == 2
    assert "no gate shell matches" in capsys.readouterr().err


def test_cancel_json_envelope_carries_the_gate_shell(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts_dir = _make_pending_gate_shell("custom-2", "beta--gate", "beta")
    patch_gate_shell_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["gate", "cancel", "beta--gate", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    assert payload["gate_shell"]["gate_state"] == "stopped"


def test_cancel_an_already_answered_gate_settles_as_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrently answered gate is not clobbered by a late cancel."""
    gate = create_gate(_spec("custom-3"))
    from sase.notification_gates.executor import execute_gate_selection

    execute_gate_selection(gate.bundle_path, ["cleanup"], source="cli")
    artifacts_dir = make_gate_shell(
        "proj", "20260812120000", "acme--gate", lane="acme", gate_id="custom-3"
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["gate_bundle_path"] = str(gate.bundle_path)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    patch_gate_shell_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["gate", "cancel", "acme--gate"]) == 0

    meta = json.loads(meta_path.read_text())
    assert meta["gate_state"] == "answered"
