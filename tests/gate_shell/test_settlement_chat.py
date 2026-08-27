"""Settle-time decision record and chat file written by ``settle_gate_shell``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.gate_shell.log import (
    _append_gate_shell_log_text as append_gate_shell_log_text,
)
from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import read_gate_shell_marker
from sase.history.chat import get_chat_file_path
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate

_ECHO_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "print(json.dumps({'status': 'ok', 'input': json.load(sys.stdin)}))\n"
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _spec(request_id: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Reclaim disk space",
            "notes": ["Free up disk on the shared volume"],
        },
        "query": "cleanup OR reject",
        "primary_branch": ["cleanup"],
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            },
            {
                "id": "reject",
                "label": "Reject",
                "command": {"argv": ["commands/reject"]},
            },
        ],
        "resources": [
            {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND},
            {"path": "commands/reject", "role": "command", "content": _ECHO_COMMAND},
        ],
    }


def _make_gate_shell_member(gate_home: Path, request_id: str, bundle_path: Path) -> str:
    shell = GateShellSpec.from_mapping(
        {"pending_status": "GATE", "settled_status": "GATED"},
        branches=(("cleanup",), ("reject",)),
    )
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane", "model": "gpt-5"},
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=None,
        gate_id=request_id,
        gate_kind="custom",
        label="Reclaim disk space",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    update_meta_field(artifacts_dir, "gate_bundle_path", str(bundle_path))
    return artifacts_dir


def test_settle_gate_shell_writes_decision_record_and_chat(
    gate_home: Path,
) -> None:
    request_id = "reclaim-1"
    gate = create_gate(_spec(request_id))
    artifacts_dir = _make_gate_shell_member(gate_home, request_id, gate.bundle_path)
    append_gate_shell_log_text(artifacts_dir, "$ commands/cleanup\ndeleted 3 files\n")

    execute_gate_selection(
        gate.bundle_path, ["cleanup"], {}, feedback="go ahead", source="test"
    )

    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    settled = settle_gate_shell(record, gate_state="answered", reason="gate answered")

    assert settled.gate_state == "answered"

    decision_text = (Path(artifacts_dir) / "gate_decision.md").read_text(
        encoding="utf-8"
    )
    assert "Reclaim disk space" in decision_text
    assert "- [x] Clean up (cleanup)" in decision_text
    assert "- [ ] Reject (reject)" in decision_text
    assert "go ahead" in decision_text
    assert "deleted 3 files" in decision_text

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    chat_path = meta["chat_path"]
    assert chat_path

    resolved_chat_path = get_chat_file_path(chat_path)
    chat_text = Path(resolved_chat_path).read_text(encoding="utf-8")
    assert "Reclaim disk space" in chat_text
    assert "go ahead" in chat_text
    assert "deleted 3 files" in chat_text

    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["chat_path"] == chat_path
    assert done["gate_decision_path"] == meta["gate_decision_path"]


def test_settle_gate_shell_writes_chat_when_branch_helper_unavailable(
    gate_home: Path,
) -> None:
    request_id = "reclaim-missing-helper"
    gate = create_gate(_spec(request_id))
    artifacts_dir = _make_gate_shell_member(gate_home, request_id, gate.bundle_path)
    execute_gate_selection(gate.bundle_path, ["cleanup"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    missing_helper = SimpleNamespace(
        returncode=127,
        stdout="",
        stderr="branch_or_workspace_name: command not found",
    )
    with patch("sase.history.chat.run_shell_command", return_value=missing_helper):
        settled = settle_gate_shell(
            record, gate_state="answered", reason="gate answered"
        )

    assert settled.gate_state == "answered"
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    chat_path = meta["chat_path"]
    assert chat_path

    chat_text = Path(get_chat_file_path(chat_path)).read_text(encoding="utf-8")
    assert "Reclaim disk space" in chat_text


def test_settle_gate_shell_is_idempotent_once_terminal(gate_home: Path) -> None:
    request_id = "reclaim-2"
    gate = create_gate(_spec(request_id))
    artifacts_dir = _make_gate_shell_member(gate_home, request_id, gate.bundle_path)
    execute_gate_selection(gate.bundle_path, ["reject"], {}, source="test")
    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None

    first = settle_gate_shell(record, gate_state="answered", reason="gate answered")
    again = settle_gate_shell(first, gate_state="answered", reason="gate answered")

    assert again.gate_state == "answered"
    meta_after_first = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta_after_first["chat_path"]
