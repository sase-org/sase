"""Repeatable non-terminal gate actions: run_command and origin edits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.edits import (
    accept_edited_origin,
    discard_origin_draft,
    origin_draft_state,
    refresh_gate_after_edit,
    resolve_edit_path,
)
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.journal import EXECUTION_JOURNAL_FILENAME
from sase.notification_gates.models import GateError
from sase.notification_gates.operations import execute_gate_operation
from sase.notification_gates.service import create_gate

_ANSWER_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, sys\n"
    "json.load(sys.stdin)\n"
    "print(json.dumps({'status': 'ok'}))\n"
)

_REPORT_COMMAND = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "json.load(sys.stdin)\n"
    "path = os.environ['GATE_TEST_LOG']\n"
    "with open(path, 'a') as stream:\n"
    "    stream.write('ran\\n')\n"
    "print(json.dumps({'summary': '1 file changed', 'body': 'diff body'}))\n"
)


def _rewrite_command(target: str) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        f"open({target!r}, 'w').write('rewritten\\n')\n"
        "print(json.dumps({'summary': 'rewrote it'}))\n"
    )


def _spec(
    *,
    request_id: str,
    operations: list[dict[str, object]],
    extra_resources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "\U0001f6e1",
            "title": "Actions",
            "notes": ["Actions"],
        },
        "query": "proceed",
        "primary_branch": ["proceed"],
        "options": [
            {
                "id": "proceed",
                "label": "Proceed",
                "command": {"argv": ["commands/proceed"]},
                "input_schema": {"type": "object"},
                "result_schema": {"type": "object"},
            }
        ],
        "operations": operations,
        "resources": [
            {
                "path": "commands/proceed",
                "role": "command",
                "content": _ANSWER_COMMAND,
            },
            *(extra_resources or []),
        ],
        "auto": False,
    }


def _report_action_spec(
    *,
    request_id: str = "report-action",
    command: str = _REPORT_COMMAND,
    targets: list[str] | None = None,
    editable: str | None = None,
) -> dict[str, object]:
    resources: list[dict[str, object]] = [
        {"path": "commands/report", "role": "command", "content": command}
    ]
    if editable is not None:
        resources.append(
            {"path": editable, "role": "editable", "content": "original\n"}
        )
    return _spec(
        request_id=request_id,
        operations=[
            {
                "id": "report",
                "kind": "run_command",
                "command": {"argv": ["commands/report"]},
                "label": "Show report",
                "key": "R",
                "display": "markdown",
                "result_schema": {"type": "object"},
                "targets": targets or [],
            }
        ],
        extra_resources=resources,
    )


def _errors(bundle_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text())
        for path in sorted((bundle_path / "errors").glob("*.json"))
    ]


def _journal(bundle_path: Path) -> list[dict[str, object]]:
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture()
def action_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "actions.log"
    monkeypatch.setenv("GATE_TEST_LOG", str(log))
    return log


def test_run_command_action_repeats_and_leaves_the_gate_answerable(
    gate_home: Path, action_log: Path
) -> None:
    gate = create_gate(_report_action_spec())

    first = execute_gate_operation(gate.bundle_path, "report")
    second = execute_gate_operation(gate.bundle_path, "report")

    assert first.display.summary == "1 file changed"
    assert first.display.body == "diff body"
    assert first.display.refresh is False
    assert first.display_format == "markdown"
    assert second.review_revision == first.review_revision == 1
    assert action_log.read_text().split() == ["ran", "ran"]
    assert not gate.response_path.exists()
    assert [record["event"] for record in _journal(gate.bundle_path)] == [
        "operation_ran",
        "operation_ran",
    ]

    execution = execute_gate_selection(gate.bundle_path, ["proceed"])
    assert execution.response["selected_option_ids"] == ["proceed"]


def test_run_command_action_refuses_a_settled_gate(
    gate_home: Path, action_log: Path
) -> None:
    answered = create_gate(_report_action_spec(request_id="answered"))
    execute_gate_selection(answered.bundle_path, ["proceed"])
    with pytest.raises(GateError) as rejected:
        execute_gate_operation(answered.bundle_path, "report")
    assert rejected.value.code == "already_answered"

    cancelled = create_gate(_report_action_spec(request_id="cancelled"))
    cancel_gate(cancelled.bundle_path)
    with pytest.raises(GateError) as refused:
        execute_gate_operation(cancelled.bundle_path, "report")
    assert refused.value.code == "gate_cancelled"
    assert not action_log.exists()


def test_action_rewriting_an_undeclared_resource_fails_and_is_recorded(
    gate_home: Path,
) -> None:
    gate = create_gate(
        _report_action_spec(
            request_id="undeclared",
            command=_rewrite_command("notes.md"),
            editable="notes.md",
        )
    )

    with pytest.raises(GateError) as rejected:
        execute_gate_operation(gate.bundle_path, "report")

    assert rejected.value.code == "hash_mismatch"
    assert [error["code"] for error in _errors(gate.bundle_path)] == ["hash_mismatch"]
    assert not gate.response_path.exists()
    [record] = _journal(gate.bundle_path)
    assert (record["event"], record["code"]) == ("operation_ran", "hash_mismatch")


def test_action_rewriting_a_declared_target_rehashes_and_bumps_the_revision(
    gate_home: Path,
) -> None:
    gate = create_gate(
        _report_action_spec(
            request_id="declared",
            command=_rewrite_command("notes.md"),
            editable="notes.md",
            targets=["notes.md"],
        )
    )

    result = execute_gate_operation(gate.bundle_path, "report")

    assert result.review_revision == 2
    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    assert envelope["review_revision"] == 2
    assert envelope["hashes"] == result.hashes
    # The bundle stays verifiable, so the gate is still answerable afterwards.
    execution = execute_gate_selection(gate.bundle_path, ["proceed"])
    assert execution.response["selected_option_ids"] == ["proceed"]


def test_unknown_and_wrong_kind_actions_are_rejected(gate_home: Path) -> None:
    gate = create_gate(
        _spec(
            request_id="edit-only",
            operations=[
                {"id": "edit_notes", "kind": "edit_file", "target": "notes.md"}
            ],
            extra_resources=[
                {"path": "notes.md", "role": "editable", "content": "original\n"}
            ],
        )
    )

    with pytest.raises(GateError) as unknown:
        execute_gate_operation(gate.bundle_path, "nope")
    assert unknown.value.code == "unknown_operation"

    with pytest.raises(GateError) as wrong_kind:
        execute_gate_operation(gate.bundle_path, "edit_notes")
    assert wrong_kind.value.code == "invalid_operation"


def _origin_spec(origin: Path, *, request_id: str = "origin-edit") -> dict[str, object]:
    return _spec(
        request_id=request_id,
        operations=[
            {
                "id": "edit_notes",
                "kind": "edit_file",
                "target": "notes.md",
                "edit_target": "origin",
                "label": "Edit notes",
                "key": "e",
            }
        ],
        extra_resources=[
            {"path": "notes.md", "role": "editable", "source": str(origin)}
        ],
    )


def test_origin_edit_target_resolves_to_the_recorded_origin(
    gate_home: Path, tmp_path: Path
) -> None:
    origin = tmp_path / "notes.md"
    origin.write_text("original\n")
    gate = create_gate(_origin_spec(origin))

    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    target = resolve_edit_path(gate.bundle_path, envelope, "edit_notes")

    assert target.origin == origin
    assert target.path == origin
    assert target.resource_path == "notes.md"
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "clean"

    origin.write_text("revised\n")
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "draft"

    accept_edited_origin(gate.bundle_path, "edit_notes")

    resource = gate.bundle_path / "notes.md"
    assert resource.read_text() == "revised\n"
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "clean"


def test_origin_edit_target_falls_back_to_the_bundle_resource(
    gate_home: Path, tmp_path: Path
) -> None:
    origin = tmp_path / "gone.md"
    origin.write_text("original\n")
    gate = create_gate(_origin_spec(origin, request_id="origin-missing"))
    origin.unlink()

    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    target = resolve_edit_path(gate.bundle_path, envelope, "edit_notes")

    assert target.origin is None
    assert target.path == gate.bundle_path / "notes.md"
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "missing"
    # With no origin to copy from, accepting falls back to the bundle resource.
    assert accept_edited_origin(gate.bundle_path, "edit_notes")["resources"]


def test_discarding_a_draft_restores_the_origin_from_the_reviewed_copy(
    gate_home: Path, tmp_path: Path
) -> None:
    origin = tmp_path / "notes.md"
    origin.write_text("original\n")
    gate = create_gate(_origin_spec(origin, request_id="origin-discard"))
    before = json.loads((gate.bundle_path / "request.json").read_text())

    origin.write_text("unwanted draft\n")
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "draft"

    assert discard_origin_draft(gate.bundle_path, "edit_notes") == "clean"

    assert origin.read_text() == "original\n"
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "clean"
    # Discarding never advances what the reviewer is reviewing.
    after = json.loads((gate.bundle_path / "request.json").read_text())
    assert after["review_revision"] == before["review_revision"]
    assert after["hashes"] == before["hashes"]


def test_discarding_reports_missing_when_no_origin_was_recorded(
    gate_home: Path, tmp_path: Path
) -> None:
    origin = tmp_path / "gone.md"
    origin.write_text("original\n")
    gate = create_gate(_origin_spec(origin, request_id="discard-missing"))
    origin.unlink()

    assert discard_origin_draft(gate.bundle_path, "edit_notes") == "missing"


def test_a_rejected_origin_draft_restores_the_reviewed_bundle_bytes(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "notes.md"
    origin.write_text("original\n")
    gate = create_gate(_origin_spec(origin, request_id="origin-rejected"))
    before = json.loads((gate.bundle_path / "request.json").read_text())

    from sase.notification_gates.adapters import GateAdapter

    def reject(_self: GateAdapter, *, path: Path) -> None:
        raise GateError("invalid_resource", str(path), "rejected by the adapter")

    monkeypatch.setattr(GateAdapter, "validate_edited_resource", reject)
    origin.write_text("revised\n")

    with pytest.raises(GateError) as rejected:
        accept_edited_origin(gate.bundle_path, "edit_notes")

    assert rejected.value.code == "invalid_resource"
    assert (gate.bundle_path / "notes.md").read_text() == "original\n"
    after = json.loads((gate.bundle_path / "request.json").read_text())
    assert after["review_revision"] == before["review_revision"] == 1
    assert after["hashes"] == before["hashes"]
    # The reviewer's draft survives in the origin file, so reopening resumes it.
    assert origin.read_text() == "revised\n"
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "draft"


def test_resource_edits_still_refresh_without_an_origin(gate_home: Path) -> None:
    gate = create_gate(
        _spec(
            request_id="resource-edit",
            operations=[
                {"id": "edit_notes", "kind": "edit_file", "target": "notes.md"}
            ],
            extra_resources=[
                {"path": "notes.md", "role": "editable", "content": "original\n"}
            ],
        )
    )
    (gate.bundle_path / "notes.md").write_text("revised\n")

    hashes = refresh_gate_after_edit(gate.bundle_path, "edit_notes")

    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    assert envelope["review_revision"] == 2
    assert envelope["hashes"] == hashes
    assert origin_draft_state(gate.bundle_path, "edit_notes") == "clean"


def test_declared_actions_must_be_owned_by_the_bundle(gate_home: Path) -> None:
    unowned_command = _spec(
        request_id="unowned-command",
        operations=[
            {
                "id": "report",
                "kind": "run_command",
                "command": {"argv": ["commands/missing"]},
            }
        ],
    )
    with pytest.raises(GateError) as rejected:
        create_gate(unowned_command)
    assert rejected.value.code == "unowned_command"

    unowned_target = _report_action_spec(
        request_id="unowned-target", targets=["notes.md"]
    )
    with pytest.raises(GateError) as bad_target:
        create_gate(unowned_target)
    assert bad_target.value.code == "unowned_edit_target"


def test_action_keys_may_not_collide_with_the_modals_or_each_other(
    gate_home: Path,
) -> None:
    reserved = _report_action_spec(request_id="reserved-key")
    operations = reserved["operations"]
    assert isinstance(operations, list)
    operations[0]["key"] = "d"
    with pytest.raises(GateError) as collision:
        create_gate(reserved)
    assert collision.value.code == "reserved_action_key"

    duplicated = _spec(
        request_id="duplicate-key",
        operations=[
            {
                "id": "edit_notes",
                "kind": "edit_file",
                "target": "notes.md",
                "key": "e",
            },
            {
                "id": "report",
                "kind": "run_command",
                "command": {"argv": ["commands/report"]},
                "key": "e",
            },
        ],
        extra_resources=[
            {"path": "notes.md", "role": "editable", "content": "original\n"},
            {
                "path": "commands/report",
                "role": "command",
                "content": _REPORT_COMMAND,
            },
        ],
    )
    with pytest.raises(GateError) as duplicate:
        create_gate(duplicated)
    assert duplicate.value.code == "duplicate_action_key"


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        ({"id": "x", "kind": "open_url", "target": "notes.md"}, "invalid_operation"),
        (
            {"id": "x", "kind": "edit_file", "target": "notes.md", "display": "json"},
            "invalid_request",
        ),
        (
            {
                "id": "x",
                "kind": "run_command",
                "command": {"argv": ["commands/report"]},
                "display": "html",
            },
            "invalid_operation",
        ),
        (
            {
                "id": "x",
                "kind": "edit_file",
                "target": "notes.md",
                "edit_target": "elsewhere",
            },
            "invalid_operation",
        ),
    ],
)
def test_malformed_action_declarations_are_rejected(
    gate_home: Path, operation: dict[str, object], code: str
) -> None:
    with pytest.raises(GateError) as rejected:
        create_gate(
            _spec(
                request_id="malformed",
                operations=[operation],
                extra_resources=[
                    {"path": "notes.md", "role": "editable", "content": "x\n"},
                    {
                        "path": "commands/report",
                        "role": "command",
                        "content": _REPORT_COMMAND,
                    },
                ],
            )
        )
    assert rejected.value.code == code


def test_an_action_declaration_round_trips_through_the_envelope(
    gate_home: Path,
) -> None:
    gate = create_gate(_report_action_spec(request_id="round-trip"))

    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    [stored] = envelope["operations"]
    assert stored["label"] == "Show report"
    assert stored["display"] == "markdown"
    assert stored["key"] == "R"
    assert stored["targets"] == []
    # Reparsing the stored record is what every reader does; it must round trip.
    from sase.notification_gates.model_operations import GateOperation

    assert GateOperation.from_mapping(stored, 0).to_dict() == stored


@pytest.mark.parametrize("tier", ["tale", "epic"])
def test_both_plan_tiers_declare_the_registered_edit_action(tier: str) -> None:
    from sase.notification_gates.kind_validation.plan import validate_plan_spec
    from sase.notification_gates.models import GateSpec
    from sase.notification_gates.registry import adapter_for_kind
    from sase.plan_gate import plan_gate_edit_operation

    operation = plan_gate_edit_operation(tier)  # type: ignore[arg-type]
    assert operation["edit_target"] == "origin"
    assert operation["key"] == "e"
    assert operation["label"] == ("Edit epic plan" if tier == "epic" else "Edit plan")

    kind = "plan" if tier == "tale" else "epic_plan"
    adapter = adapter_for_kind(kind)
    spec = GateSpec.from_mapping(_plan_like_request(tier))
    validate_plan_spec(spec, adapter)

    tampered = _plan_like_request(tier)
    operations = tampered["operations"]
    assert isinstance(operations, list)
    operations[0]["edit_target"] = "resource"
    with pytest.raises(GateError) as rejected:
        validate_plan_spec(GateSpec.from_mapping(tampered), adapter)
    assert rejected.value.code == "invalid_plan_operation"


def _plan_like_request(tier: str) -> dict[str, object]:
    from sase.plan_gate import (
        PLAN_RESOURCE_PATH,
        TALE_PLAN_SUBMIT_GROUP,
        plan_gate_command_script,
        plan_gate_edit_operation,
        plan_gate_option_ids,
        plan_gate_query,
    )

    option_ids = plan_gate_option_ids(tier)  # type: ignore[arg-type]
    return {
        "schema_version": 3,
        "kind": "plan" if tier == "tale" else "epic_plan",
        "request_id": f"plan-{tier}",
        "producer": {},
        "payload": {
            "authored_tier": tier,
            "plan_resource": PLAN_RESOURCE_PATH,
        },
        "presentation": {"notes": ["Plan"], "files": [PLAN_RESOURCE_PATH]},
        "query": plan_gate_query(tier),  # type: ignore[arg-type]
        "primary_branch": (["approve"] if tier == "epic" else ["approve", "commit"]),
        "options": [
            {
                "id": option_id,
                "label": option_id.title(),
                "command": {"argv": [f"commands/{option_id}"]},
            }
            for option_id in option_ids
        ],
        "groups": ([TALE_PLAN_SUBMIT_GROUP.to_dict()] if tier == "tale" else []),
        "operations": [plan_gate_edit_operation(tier)],  # type: ignore[arg-type]
        "resources": [
            {"path": PLAN_RESOURCE_PATH, "role": "editable", "content": "# Plan\n"},
            *[
                {
                    "path": f"commands/{option_id}",
                    "role": "command",
                    "content": plan_gate_command_script(option_id),
                }
                for option_id in option_ids
            ],
        ],
        "auto": False,
    }
