"""TaskTriage trusted-kind validation against forged gate contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sase.bead._task_gate_spec import build_task_triage_gate_spec
from sase.bead.model import TaskPlusOneEvidence
from sase.bead.task_gate import TASK_TRIAGE_PREVIEW_PATH
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def test_task_triage_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = task_triage_spec(request_id="task-triage-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="close OR launch OR snooze"),
            "invalid_task_triage_query",
        ),
        (
            lambda spec: spec["options"][2].update(label="Snooze (3d)"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["options"][2].update(feedback="required"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["options"][2].pop("inputs"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["options"][2]["inputs"][0].update(label="Wake after"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["options"][2]["inputs"][0].update(type="text"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["options"][2].update(
                input_schema={
                    "type": "object",
                    "properties": {"duration": {"type": "string"}},
                    "required": ["duration"],
                    "additionalProperties": True,
                }
            ),
            "conflicting_input_declaration",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(created_at=17),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(created_at="2020-06-01T00:00:00Z"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["payload"].update(close_history=[{"bad": True}]),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                close_history=[
                    {
                        "closed_at": "2026-06-01T00:00:00Z",
                        "close_reason": None,
                        "resolution": None,
                        "reopened_at": "2026-06-15T00:00:00Z",
                        "reopened_via": "not_a_real_cause",
                        "reopened_by": None,
                    }
                ]
            ),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["options"][0].update(feedback="disabled"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_task_triage_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_task_triage_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_task_triage_preview",
        ),
    ],
)
def test_task_triage_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(task_triage_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def _blank_notes_spec(*, request_id: str, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "description": "Make invalidation deterministic.",
        "notes": "",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "producer": {"agent_name": "triage-test"},
    }
    fields.update(overrides)
    return build_task_triage_gate_spec(request_id=request_id, **fields)


def _preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == TASK_TRIAGE_PREVIEW_PATH
    )


def test_task_triage_kind_validation_accepts_blank_notes(gate_home: Path) -> None:
    del gate_home
    spec = _blank_notes_spec(request_id="task-triage-blank-notes")

    create_gate(spec)


def test_task_triage_kind_validation_accepts_legacy_no_notes_placeholder(
    gate_home: Path,
) -> None:
    del gate_home
    spec = build_task_triage_gate_spec(
        request_id="task-triage-legacy-notes",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="D",
        notes="",
    )
    preview_resource = _preview_resource(spec)
    assert preview_resource["content"] == (
        "# sase-task.1 — Follow up on the cache\n\n## Description\n\nD\n"
    )
    preview_resource["content"] = (
        "# sase-task.1 — Follow up on the cache\n\n"
        "## Description\n\nD\n\n## Notes\n\n_No notes._\n"
    )

    create_gate(spec)


def test_task_triage_kind_validation_accepts_description_containing_notes_marker_text(
    gate_home: Path,
) -> None:
    del gate_home
    spec = build_task_triage_gate_spec(
        request_id="task-triage-desc-embeds-separator",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="Intro line.\n\n## Notes\n\n  indented continuation.",
        notes="",
    )

    create_gate(spec)


def _blank_notes_spec_with_evidence(*, request_id: str) -> dict[str, Any]:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Reproduced after clearing the cache.",
    )
    return _blank_notes_spec(
        request_id=request_id,
        size="medium",
        plus_one_evidence=(evidence,),
    )


@pytest.mark.parametrize(
    ("label", "mutate_preview", "code"),
    [
        (
            "appended-heading",
            lambda content: content + "\n\n## Injected\n\nGotcha.\n",
            "invalid_task_triage_preview",
        ),
        (
            "size-mismatch",
            lambda content: content.replace("`medium`", "`large`"),
            "invalid_task_triage_preview",
        ),
    ],
)
def test_task_triage_kind_validation_rejects_blank_notes_preview_injection(
    gate_home: Path,
    label: str,
    mutate_preview: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(_blank_notes_spec_with_evidence(request_id=f"forged-blank-{label}"))
    preview_resource = _preview_resource(spec)
    preview_resource["content"] = mutate_preview(preview_resource["content"])

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


_FLAKE_FIELDS = {
    "node_id": "tests/x.py::test_y",
    "evidence": "3/50 under -n 8",
}


def _typed_spec(*, request_id: str, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "description": "Make invalidation deterministic.",
        "notes": "Discovered while landing sase-bg.",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "task_type": "flake",
        "task_type_fields": _FLAKE_FIELDS,
        "producer": {"agent_name": "triage-test"},
    }
    fields.update(overrides)
    return build_task_triage_gate_spec(request_id=request_id, **fields)


def test_task_triage_kind_validation_accepts_typed_gate(gate_home: Path) -> None:
    del gate_home
    create_gate(_typed_spec(request_id="task-triage-typed-ok"))


def test_task_triage_kind_validation_accepts_typed_gate_with_blank_notes(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(_typed_spec(request_id="task-triage-typed-blank-notes", notes=""))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec["presentation"]["chip"].update(glyph="?"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(tags=["bead", "task", "ci"]),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"]["notes"].__setitem__(
                1, "forged type line"
            ),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["payload"]["task_type_display"].update(
                name="Not a flake"
            ),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["payload"]["task_type_display"].update(
                accent_color="red"
            ),
            "invalid_task_triage_payload",
        ),
    ],
)
def test_task_triage_kind_validation_rejects_forged_type_presentation(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(_typed_spec(request_id=f"forged-type-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_task_triage_kind_validation_rejects_forged_chip_on_untyped_gate(
    gate_home: Path,
) -> None:
    del gate_home
    spec = deepcopy(task_triage_spec(request_id="forged-untyped-chip"))
    spec["presentation"]["chip"] = {
        "glyph": "≈",
        "label": "flake",
        "color": "#00D7D7",
    }

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_task_triage_presentation"


def test_task_triage_kind_validation_rejects_display_without_task_type(
    gate_home: Path,
) -> None:
    del gate_home
    spec = deepcopy(task_triage_spec(request_id="forged-display-without-type"))
    spec["payload"]["task_type_display"] = {
        "glyph": "≈",
        "name": "Flaky test",
        "accent_color": "#00D7D7",
        "facts": [],
    }

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_task_triage_payload"
    assert exc_info.value.target == "payload.task_type_display"


def test_task_triage_kind_validation_rejects_mutated_preview_type_fact(
    gate_home: Path,
) -> None:
    del gate_home
    spec = deepcopy(_typed_spec(request_id="forged-type-fact", notes=""))
    preview_resource = _preview_resource(spec)
    preview_resource["content"] = preview_resource["content"].replace(
        "**Task type:** ≈ `flake`",
        "**Task type:** ⨯ `bug`",
    )

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_task_triage_preview"
