"""Contract tests for staged gate preparation and rehydration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import build_gate_staged_record
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    build_gate_staged_payload,
    validate_gate_staged_payload,
    validate_staged_handoff,
)
from sase.gate_turn.models import GateTurnError
from sase.gate_turn.staged_contract import (
    STAGED_GATE_RESOURCES_DIRNAME,
    collect_staged_gate_creator,
    discard_staged_gate_snapshot,
    prepare_staged_gate,
    read_staged_gate_snapshot_bytes,
    rehydrate_staged_gate_spec,
)
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.models import GateError

_ECHO_COMMAND = "#!/bin/sh\necho ok\n"
_UNICODE_BODY = "héllo wörld ✓ — naïve café\n"
_BINARY_BODY = b"\x00\x01\x02\xff\xfe\xfd binary \xe2\x9c\x93 ok"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _write_sources(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Create source files and point the working directory at them."""
    (root / "notes.md").write_text("editable notes\n", encoding="utf-8")
    (root / "abs.md").write_text("absolute editable\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(_BINARY_BODY)
    monkeypatch.chdir(root)
    return {
        "notes.md": b"editable notes\n",
        "abs": b"absolute editable\n",
        "blob": _BINARY_BODY,
    }


def _request(
    *,
    request_id: str | None = "stage-1",
    workspace: str = "inherit",
    include_turn: bool = True,
) -> dict[str, Any]:
    resources: list[dict[str, Any]] = [
        {"path": "commands/cleanup", "role": "command", "content": _ECHO_COMMAND},
        {"path": "commands/fetch", "role": "command", "content": _ECHO_COMMAND},
        {"path": "commands/apply", "role": "command", "content": _ECHO_COMMAND},
        {"path": "notes.md", "role": "editable", "source": "notes.md"},
        {"path": "preview.txt", "role": "preview", "content": _UNICODE_BODY},
    ]
    request: dict[str, Any] = {
        "schema_version": 3,
        "kind": "custom",
        "producer": {"agent": "test-agent", "extra": 1},
        "continuation_mode": "gate_turn",
        "gate_timeout_seconds": 3600.0,
        "payload": {"plan": ["a"], "nested": {"n": 1}},
        "presentation": {
            "title": "Stage me",
            "notes": ["first note"],
            "tags": ["t1"],
            "files": ["notes.md"],
            "preview": "preview.txt",
            "icon": "\U0001f9ea",
            "color": "#AABBCC",
        },
        "query": "cleanup OR (fetch AND apply)",
        "options": [
            {
                "id": "cleanup",
                "label": "Clean up",
                "command": {"argv": ["commands/cleanup"]},
            },
            {
                "id": "fetch",
                "label": "Fetch",
                "command": {"argv": ["commands/fetch"]},
            },
            {
                "id": "apply",
                "label": "Apply",
                "command": {"argv": ["commands/apply"]},
            },
        ],
        "groups": [{"options": ["fetch", "apply"], "label": "Fetch and apply"}],
        "primary_branch": ["cleanup"],
        "operations": [
            {
                "id": "edit-notes",
                "kind": "edit_file",
                "label": "Edit notes",
                "target": "notes.md",
                "edit_target": "origin",
            },
            {
                "id": "run-check",
                "kind": "run_command",
                "label": "Run check",
                "command": {"argv": ["commands/cleanup"]},
                "targets": ["notes.md"],
                "display": "text",
            },
        ],
        "resources": resources,
        "auto": {"enabled": False},
    }
    if request_id is not None:
        request["request_id"] = request_id
    if include_turn:
        request["turn"] = {
            "workspace": workspace,
            "pending_status": "GATE",
            "settled_status": "GATED",
            "next": {
                "prompt": "follow up",
                "fork": "session",
                "output": ["results"],
                "model": "m1",
            },
            "branches": {
                "cleanup": {"status": "DONE", "prompt": "did cleanup"},
            },
        }
    return request


def _creator(artifacts_dir: str) -> dict[str, Any]:
    return {
        "project": "proj",
        "project_file": "/tmp/proj.sase",
        "artifacts_dir": artifacts_dir,
        "timestamp": "20261029T000000Z",
        "agent": "agent-1",
        "agent_session": "agent-1--session",
        "target": "agent-1",
        "workspace_num": 3,
        "runner_pid": 111,
        "cl_name": "cl-1",
        "meta": {},
    }


def test_spec_to_dict_round_trips_full_custom_gate() -> None:
    spec = GateSpec.from_mapping(_request())
    assert "turn_row_managed" not in spec.to_dict()
    assert "branches" not in spec.to_dict()
    assert "shell" not in spec.to_dict()
    reparsed = GateSpec.from_mapping(spec.to_dict())
    assert reparsed == spec


def test_spec_to_dict_rejects_managed_row_in_user_json() -> None:
    data = _request()
    data["turn_row_managed"] = True
    with pytest.raises(GateError):
        GateSpec.from_mapping(data)


def test_prepare_captures_snapshots_and_builds_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    assert preparation.auto_execute is False
    assert preparation.request_id == "stage-1"
    assert preparation.workspace_mode == "inherit"
    assert preparation.successor_workspace == "inherit"
    assert preparation.carry_allowed is True
    assert preparation.payload is not None
    assert preparation.record is not None

    payload = validate_gate_staged_payload(dict(preparation.payload))
    assert payload["request_id"] == "stage-1"
    assert payload["spec"]["request_id"] == "stage-1"
    assert validate_staged_handoff(dict(preparation.record)) == preparation.record

    manifest = {entry["path"]: entry for entry in preparation.snapshots}
    assert set(manifest) == {"notes.md"}
    entry = manifest["notes.md"]
    assert entry["origin"] == "notes.md"
    assert entry["executable"] is False
    assert entry["sha256"] == hashlib.sha256(sources["notes.md"]).hexdigest()
    assert entry["size_bytes"] == len(sources["notes.md"])
    assert entry["staged_relpath"].endswith("notes.md")

    stored = read_staged_gate_snapshot_bytes(
        str(artifacts), preparation.staged_id, "notes.md"
    )
    assert stored == sources["notes.md"]

    rehydrated = rehydrate_staged_gate_spec(payload)
    assert rehydrated == preparation.spec
    assert rehydrated.turn_row_managed is True


def test_prepare_release_workspace_maps_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(workspace="release"),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.workspace_mode == "release"
    assert preparation.successor_workspace == "none"
    assert preparation.carry_allowed is False
    assert preparation.record is not None
    assert validate_staged_handoff(dict(preparation.record)) == preparation.record


def test_prepare_auto_gate_stays_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.user_question_actions import (
        QUESTION_COMMAND_PATH,
        QUESTION_CONTINUATION_MODE,
        question_gate_command_script,
        question_response_schema,
        validate_user_questions,
    )
    from tests.autonomy_contract.harness import question_first_fixture_record

    _write_sources(tmp_path, monkeypatch)
    questions = validate_user_questions(
        [{"question": "Choose one", "options": [{"label": "First"}]}]
    )
    schema = question_response_schema(questions)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        {
            "schema_version": 3,
            "kind": "question",
            "request_id": "automatic-question",
            "continuation_mode": QUESTION_CONTINUATION_MODE,
            "payload": {
                "questions": questions,
                "session_id": "automatic-question",
            },
            "query": "submit",
            "primary_branch": ["submit"],
            "options": [
                {
                    "id": "submit",
                    "label": "Submit answers",
                    "command": {"argv": [QUESTION_COMMAND_PATH]},
                    "input_schema": schema,
                    "result_schema": schema,
                    "feedback": "optional",
                }
            ],
            "resources": [
                {
                    "path": QUESTION_COMMAND_PATH,
                    "role": "command",
                    "content": question_gate_command_script(),
                }
            ],
            "auto": {
                "enabled": True,
                "policy": question_first_fixture_record(),
            },
        },
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.auto_execute is True
    assert preparation.payload is None
    assert preparation.record is None
    assert preparation.snapshots == ()
    assert preparation.snapshot_dir is None
    assert not (artifacts / STAGED_GATE_RESOURCES_DIRNAME).exists()


def test_prepare_requires_turn_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    request = _request(include_turn=False)
    request.pop("continuation_mode", None)
    with pytest.raises(GateTurnError, match="turn block"):
        prepare_staged_gate(
            request,
            creator=_creator(str(artifacts)),
            artifacts_dir=str(artifacts),
            staged_id="bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        )
    assert not (artifacts / STAGED_GATE_RESOURCES_DIRNAME).exists()


def test_prepare_mints_request_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(request_id=None),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.request_id.startswith("custom-")
    assert preparation.payload is not None
    assert preparation.payload["request_id"] == preparation.request_id
    assert preparation.payload["spec"]["request_id"] == preparation.request_id


def test_prepare_rejects_bad_command_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    (tmp_path / "bad.sh").write_text("echo no-header\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    request = _request()
    request["options"].append(
        {"id": "bad", "label": "Bad", "command": {"argv": ["badcmd"]}}
    )
    request["query"] = "cleanup OR (fetch AND apply) OR bad"
    request["primary_branch"] = ["bad"]
    request["resources"].append(
        {"path": "badcmd", "role": "command", "source": "bad.sh"}
    )
    staged_id = "cccccccc-cccc-4ccc-8ddd-eeeeeeeeeeee"
    with pytest.raises(GateError) as exc_info:
        prepare_staged_gate(
            request,
            creator=_creator(str(artifacts)),
            artifacts_dir=str(artifacts),
            staged_id=staged_id,
        )
    assert exc_info.value.code == "invalid_command"
    assert not (artifacts / STAGED_GATE_RESOURCES_DIRNAME / staged_id).exists()


def test_snapshot_survives_source_removal_and_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.payload is not None
    (tmp_path / "notes.md").write_text("changed after stage\n", encoding="utf-8")

    stored = read_staged_gate_snapshot_bytes(
        str(artifacts), preparation.staged_id, "notes.md"
    )
    assert stored == sources["notes.md"]

    (tmp_path / "notes.md").unlink()
    assert (
        read_staged_gate_snapshot_bytes(
            str(artifacts), preparation.staged_id, "notes.md"
        )
        == sources["notes.md"]
    )
    rehydrated = rehydrate_staged_gate_spec(preparation.payload)
    assert rehydrated == preparation.spec
    assert rehydrated.resources[3].source is not None
    assert str(rehydrated.resources[3].source) == "notes.md"


def test_snapshot_rejects_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    with pytest.raises(GateTurnError, match="escapes"):
        read_staged_gate_snapshot_bytes(
            str(artifacts), preparation.staged_id, "../notes.md"
        )


def test_binary_and_absolute_sources_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    request = _request()
    request["resources"].append(
        {"path": "blob.bin", "role": "attachment", "source": "blob.bin"}
    )
    request["resources"].append(
        {
            "path": "abs.md",
            "role": "editable",
            "source": str(tmp_path / "abs.md"),
        }
    )
    preparation = prepare_staged_gate(
        request,
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.payload is not None
    manifest = {entry["path"]: entry for entry in preparation.snapshots}
    assert set(manifest) == {"notes.md", "blob.bin", "abs.md"}
    assert manifest["blob.bin"]["sha256"] == hashlib.sha256(sources["blob"]).hexdigest()
    assert manifest["abs.md"]["origin"] == str(tmp_path / "abs.md")
    assert (
        read_staged_gate_snapshot_bytes(
            str(artifacts), preparation.staged_id, "blob.bin"
        )
        == sources["blob"]
    )
    validate_gate_staged_payload(dict(preparation.payload))


def test_unicode_content_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.payload is not None
    preview = next(
        resource
        for resource in preparation.payload["spec"]["resources"]
        if resource["path"] == "preview.txt"
    )
    assert preview["content"] == _UNICODE_BODY
    rehydrated = rehydrate_staged_gate_spec(preparation.payload)
    assert rehydrated == preparation.spec


def test_discard_snapshot_removes_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.snapshot_dir is not None
    assert preparation.snapshot_dir.exists()
    discard_staged_gate_snapshot(str(artifacts), preparation.staged_id)
    assert not preparation.snapshot_dir.exists()
    discard_staged_gate_snapshot(str(artifacts), preparation.staged_id)


def test_collect_creator_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261029T000000Z"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent-1",
                "agent_session": "agent-1--session",
                "workspace_num": 3,
                "pid": 111,
                "cl_name": "cl-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    creator = collect_staged_gate_creator(project_name="proj")
    assert creator["project"] == "proj"
    assert creator["artifacts_dir"] == str(artifacts)
    assert creator["timestamp"] == "20261029T000000Z"
    assert creator["agent"] == "agent-1"
    assert creator["agent_session"] == "agent-1--session"
    assert creator["target"] == "agent-1"
    assert creator["workspace_num"] == 3
    assert creator["runner_pid"] == 111
    assert creator["cl_name"] == "cl-1"
    assert creator["meta"] == {}
    assert creator["project_file"].endswith(".sase")


def test_collect_creator_requires_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261029T000000Z"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    with pytest.raises(GateTurnError, match="no calling agent"):
        collect_staged_gate_creator(project_name="proj")


def test_build_gate_staged_record_validates_disposition() -> None:
    payload = build_gate_staged_payload(
        {
            "request_id": "stage-1",
            "spec": {"request_id": "stage-1", "resources": []},
            "auto": {"decision": {}, "policy_block": {}, "auto_execute": False},
            "resources": [],
            "creator": {
                "project": "proj",
                "project_file": "/tmp/proj.sase",
                "artifacts_dir": "/tmp/a",
                "timestamp": "20261029T000000Z",
                "agent": "agent-1",
            },
            "workspace_mode": "inherit",
        }
    )
    record = build_gate_staged_record(
        payload=payload,
        successor_workspace="inherit",
        carry_allowed=True,
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    assert validate_staged_handoff(dict(record)) == record

    mismatched = build_gate_staged_record(
        payload=payload,
        successor_workspace="none",
        carry_allowed=False,
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    with pytest.raises(StagedHandoffContractError, match="successor_workspace"):
        validate_staged_handoff(mismatched)


def test_frozen_manual_spec_publishes_from_rehydration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_home: Path
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "artifacts"
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
    )
    assert preparation.payload is not None

    from sase.notification_gates.service import create_gate

    first = create_gate(rehydrate_staged_gate_spec(preparation.payload))
    second = create_gate(rehydrate_staged_gate_spec(preparation.payload))
    assert first.notification_id == second.notification_id
    assert first.bundle_path == second.bundle_path
