"""Kind validation of forged and legacy BeadSnooze gate contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sase.bead.model import TaskPlusOneEvidence
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.snooze_gate_test_helpers import (
    bead_snooze_spec,
    preview_resource,
)


def test_bead_snooze_gate_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = bead_snooze_spec(request_id="bead-snooze-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="ready OR close OR snooze"),
            "invalid_bead_snooze_query",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"].pop("snooze"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(until="not-a-timestamp"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(snoozed_by="  "),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(
                plus_one_target=1, plus_one_baseline=3
            ),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["options"][2].update(feedback="required"),
            "invalid_bead_snooze_options",
        ),
        (
            lambda spec: spec["options"][2]["inputs"][0].update(label="Wake after"),
            "invalid_bead_snooze_options",
        ),
        (
            lambda spec: spec["options"][2]["inputs"][0].update(type="text"),
            "invalid_bead_snooze_options",
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
            lambda spec: spec["options"][2].pop("inputs"),
            "invalid_bead_snooze_options",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_bead_snooze_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {"path": "forged.txt", "role": "attachment", "content": "unexpected"}
            ),
            "invalid_bead_snooze_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(
                snooze_until="2026-08-10T09:00:00-04:00"
            ),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(
                snooze_until="2026-08-10T09:00:00"
            ),
            "invalid_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_bead_snooze_preview",
        ),
    ],
)
def test_bead_snooze_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(bead_snooze_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_bead_snooze_kind_validation_accepts_blank_notes(gate_home: Path) -> None:
    del gate_home
    spec = bead_snooze_spec(request_id="bead-snooze-blank-notes", notes="")

    create_gate(spec)


def test_bead_snooze_kind_validation_accepts_legacy_no_notes_placeholder(
    gate_home: Path,
) -> None:
    del gate_home
    spec = bead_snooze_spec(
        request_id="bead-snooze-legacy-notes",
        description="D",
        notes="",
        created_by="",
        created_at="",
    )
    resource = preview_resource(spec)
    assert resource["content"].endswith("## Description\n\nD\n")
    resource["content"] = resource["content"].replace(
        "## Description\n\nD\n",
        "## Description\n\nD\n\n## Notes\n\n_No notes._\n",
    )

    create_gate(spec)


def test_bead_snooze_kind_validation_accepts_description_containing_notes_marker_text(
    gate_home: Path,
) -> None:
    del gate_home
    spec = bead_snooze_spec(
        request_id="bead-snooze-desc-embeds-separator",
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
    return bead_snooze_spec(
        request_id=request_id,
        notes="",
        size="medium",
        plus_one_evidence=(evidence,),
    )


@pytest.mark.parametrize(
    ("label", "mutate_preview", "code"),
    [
        (
            "appended-heading",
            lambda content: content + "\n\n## Injected\n\nGotcha.\n",
            "invalid_bead_snooze_preview",
        ),
        (
            "size-mismatch",
            lambda content: content.replace("`medium`", "`large`"),
            "invalid_bead_snooze_preview",
        ),
    ],
)
def test_bead_snooze_kind_validation_rejects_blank_notes_preview_injection(
    gate_home: Path,
    label: str,
    mutate_preview: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(_blank_notes_spec_with_evidence(request_id=f"forged-blank-{label}"))
    resource = preview_resource(spec)
    resource["content"] = mutate_preview(resource["content"])

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


_FLAKE_FIELDS = {
    "node_id": "tests/x.py::test_y",
    "evidence": "3/50 under -n 8",
}


def test_bead_snooze_kind_validation_accepts_typed_gate(gate_home: Path) -> None:
    del gate_home
    create_gate(
        bead_snooze_spec(
            request_id="bead-snooze-typed-ok",
            task_type="flake",
            task_type_fields=_FLAKE_FIELDS,
        )
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec["presentation"]["chip"].update(glyph="?"),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(tags=["bead", "task", "ci"]),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"]["notes"].__setitem__(
                1, "forged type line"
            ),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["payload"]["task_type_display"].update(
                name="Not a flake"
            ),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["payload"]["task_type_display"].update(
                accent_color="red"
            ),
            "invalid_bead_snooze_payload",
        ),
    ],
)
def test_bead_snooze_kind_validation_rejects_forged_type_presentation(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(
        bead_snooze_spec(
            request_id=f"forged-type-{code}",
            task_type="flake",
            task_type_fields=_FLAKE_FIELDS,
        )
    )
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_bead_snooze_kind_validation_rejects_display_without_task_type(
    gate_home: Path,
) -> None:
    del gate_home
    spec = deepcopy(bead_snooze_spec(request_id="forged-display-without-type"))
    spec["payload"]["task_type_display"] = {
        "glyph": "≈",
        "name": "Flaky test",
        "accent_color": "#00D7D7",
        "facts": [],
    }

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_bead_snooze_payload"
    assert exc_info.value.target == "payload.task_type_display"
