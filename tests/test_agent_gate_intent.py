"""Agent-side gate intent marker I/O."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.agent.gate_intent import (
    GATE_INTENT_PREFIX,
    begin_gate_intent,
    clear_gate_intent,
    discard_gate_intents,
    list_gate_intents,
)


def _set_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))


def test_marker_written_only_for_agent_child_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_agent_env(monkeypatch, tmp_path)

    path = begin_gate_intent("sudo", request_id="sudo-one")

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "sudo"
    assert payload["request_id"] == "sudo-one"
    assert payload["pid"] == os.getpid()


def test_marker_not_written_outside_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    assert begin_gate_intent("sudo", request_id="sudo-one") is None
    assert list_gate_intents(tmp_path) == []


def test_marker_not_written_by_runner_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_agent_env(monkeypatch, tmp_path)
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": os.getpid()}),
        encoding="utf-8",
    )

    assert begin_gate_intent("sudo", request_id="sudo-one") is None
    assert list_gate_intents(tmp_path) == []


def test_marker_is_per_pid_and_restamps_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_agent_env(monkeypatch, tmp_path)

    first = begin_gate_intent("sudo", source="sase sudo request")
    second = begin_gate_intent("sudo", request_id="sudo-two")

    assert first == second
    intents = list_gate_intents(tmp_path)
    assert len(intents) == 1
    assert intents[0].path.name == f"{GATE_INTENT_PREFIX}{os.getpid()}.json"
    assert intents[0].request_id == "sudo-two"
    assert intents[0].source == "create_gate_shell"


def test_clear_removes_only_current_process_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_agent_env(monkeypatch, tmp_path)
    own = begin_gate_intent("sudo", request_id="sudo-one")
    other = tmp_path / f"{GATE_INTENT_PREFIX}123456.json"
    other.write_text(json.dumps({"pid": 123456, "kind": "custom"}), encoding="utf-8")

    clear_gate_intent()

    assert own is not None
    assert not own.exists()
    assert other.exists()


def test_discard_removes_all_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_agent_env(monkeypatch, tmp_path)
    begin_gate_intent("sudo", request_id="sudo-one")
    (tmp_path / f"{GATE_INTENT_PREFIX}123456.json").write_text(
        json.dumps({"pid": 123456, "kind": "custom"}),
        encoding="utf-8",
    )

    discard_gate_intents(tmp_path)

    assert list_gate_intents(tmp_path) == []


def test_corrupt_json_counts_as_unknown_intent(tmp_path: Path) -> None:
    path = tmp_path / f"{GATE_INTENT_PREFIX}123456.json"
    path.write_text("{", encoding="utf-8")

    intents = list_gate_intents(tmp_path)

    assert len(intents) == 1
    assert intents[0].path == path
    assert intents[0].pid == 123456
    assert intents[0].kind is None
    assert intents[0].corrupt is True
