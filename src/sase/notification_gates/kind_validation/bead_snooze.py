"""Validation contract for BeadSnooze gates."""

from __future__ import annotations

from typing import cast

from sase.notification_gates.kind_validation.bead_snooze_payload import (
    BeadSnoozePayload,
    parse_bead_snooze_payload,
)
from sase.notification_gates.kind_validation.preview_recovery import (
    preview_matches_renderer,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import (
    NO_INPUT_SCHEMA,
    GateError,
    GateSpec,
    stamp_schema_dialect,
)


def validate_bead_snooze_spec(spec: GateSpec) -> None:
    """Keep BeadSnooze gates on their human-only trusted task contract."""
    _validate_bead_snooze_structure(spec)
    payload = parse_bead_snooze_payload(spec.payload)
    _validate_bead_snooze_options(spec)
    preview_content = _validate_bead_snooze_resources(spec)
    _validate_bead_snooze_presentation(spec, payload)
    _validate_bead_snooze_preview(spec, payload, preview_content)


def _validate_bead_snooze_structure(spec: GateSpec) -> None:
    from sase.bead.snooze_gate import (
        BEAD_SNOOZE_CONTINUATION_MODE,
        BEAD_SNOOZE_QUERY,
    )

    if spec.continuation_mode != BEAD_SNOOZE_CONTINUATION_MODE:
        raise GateError(
            "invalid_bead_snooze_continuation",
            "continuation_mode",
            f"bead snooze gates require {BEAD_SNOOZE_CONTINUATION_MODE}",
        )
    if spec.query != BEAD_SNOOZE_QUERY or spec.branches != (
        ("close",),
        ("ready",),
        ("snooze",),
    ):
        raise GateError(
            "invalid_bead_snooze_query",
            "query",
            f"bead snooze gates require query: {BEAD_SNOOZE_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_bead_snooze_structure",
            "groups",
            "bead snooze gates do not define groups or operations",
        )


def _validate_bead_snooze_options(spec: GateSpec) -> None:
    from sase.bead.snooze_gate import (
        BEAD_SNOOZE_COMMAND_PATHS,
        BEAD_SNOOZE_OPTION_FEEDBACK,
        BEAD_SNOOZE_OPTION_IDS,
        BeadSnoozeAction,
        bead_snooze_result_schema,
    )

    if tuple(option.id for option in spec.options) != BEAD_SNOOZE_OPTION_IDS:
        raise GateError(
            "invalid_bead_snooze_options",
            "options",
            "bead snooze gates require close, ready, and snooze options",
        )
    for option in spec.options:
        typed_option_id = cast(BeadSnoozeAction, option.id)
        expected_command = BEAD_SNOOZE_COMMAND_PATHS[typed_option_id]
        if (
            option.command.argv != (expected_command,)
            or option.input_schema != NO_INPUT_SCHEMA
            or option.result_schema
            != stamp_schema_dialect(bead_snooze_result_schema(typed_option_id))
            or option.feedback != BEAD_SNOOZE_OPTION_FEEDBACK[typed_option_id]
        ):
            raise GateError(
                "invalid_bead_snooze_options",
                f"options.{option.id}",
                "bead snooze option does not match the registered adapter",
            )


def _validate_bead_snooze_resources(spec: GateSpec) -> str | None:
    """Check the preview and command resources, returning the preview content."""
    from sase.bead.snooze_gate import (
        BEAD_SNOOZE_COMMAND_PATHS,
        BEAD_SNOOZE_PREVIEW_PATH,
        bead_snooze_gate_command_script,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *BEAD_SNOOZE_COMMAND_PATHS.values(),
        BEAD_SNOOZE_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_bead_snooze_resources",
            "resources",
            "bead snooze gates require only their preview and command resources",
        )
    preview = resources[BEAD_SNOOZE_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_bead_snooze_preview",
            BEAD_SNOOZE_PREVIEW_PATH,
            "bead snooze preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_bead_snooze_preview",
        description="bead snooze preview",
    )
    for option_id, path in BEAD_SNOOZE_COMMAND_PATHS.items():
        command = resources[path]
        if command.role != "command" or not command.executable:
            raise GateError(
                "invalid_bead_snooze_command",
                path,
                "bead snooze command resource is invalid",
            )
        content = read_gate_resource(
            command,
            code="invalid_bead_snooze_command",
            description="bead snooze command",
        )
        if content != bead_snooze_gate_command_script(option_id):
            raise GateError(
                "invalid_bead_snooze_command",
                path,
                "bead snooze command does not match the registered adapter",
            )
    return preview_content


def _validate_bead_snooze_presentation(
    spec: GateSpec, payload: BeadSnoozePayload
) -> None:
    from sase.bead.snooze_gate import (
        BEAD_SNOOZE_PREVIEW_PATH,
        bead_snooze_presentation_note,
    )

    task = payload.task
    expected_note = bead_snooze_presentation_note(
        task.bead_id,
        task.title,
        task.plus_one_count,
        until=payload.snooze.until,
        reopen_count=len(task.close_history),
    )
    presentation = spec.presentation
    origin_agent = presentation.get("origin_agent")
    if (
        presentation.get("sender") != "bead"
        or presentation.get("icon") != "◈"
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["bead", "task"]
        or presentation.get("panel") != "beads"
        or presentation.get("snooze_until") != payload.snooze.until
        or (origin_agent is not None and not isinstance(origin_agent, str))
        or (isinstance(origin_agent, str) and not origin_agent)
        or presentation.get("files") != [BEAD_SNOOZE_PREVIEW_PATH]
        or presentation.get("preview") != BEAD_SNOOZE_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_bead_snooze_presentation",
            "presentation",
            "bead snooze presentation does not match the registered adapter",
        )


def _validate_bead_snooze_preview(
    spec: GateSpec, payload: BeadSnoozePayload, preview_content: str | None
) -> None:
    """Reconstruct the preview from its payload and compare it byte for byte.

    The agent-authored description and notes are not carried by the payload, so
    they are recovered from the persisted preview by rendering a marker-bearing
    template and slicing the body the markers delimit.
    """
    from sase.bead.snooze_gate import (
        BEAD_SNOOZE_PREVIEW_PATH,
        render_bead_snooze_preview,
    )

    task = payload.task
    origin_agent = spec.presentation.get("origin_agent")
    created_by = cast(str, origin_agent or "")

    def render(description: str, notes: str) -> str:
        return render_bead_snooze_preview(
            bead_id=task.bead_id,
            title=task.title,
            description=description,
            notes=notes,
            snooze=payload.snooze,
            created_by=created_by,
            created_at=task.created_at,
            size=task.size,
            refs=task.refs,
            plus_one_evidence=task.plus_one_evidence,
            close_history=task.close_history,
        )

    matches = preview_matches_renderer(
        render=render,
        description_marker="__BEAD_SNOOZE_DESCRIPTION__",
        notes_marker="__BEAD_SNOOZE_NOTES__",
        preview_content=preview_content,
    )
    if not matches:
        raise GateError(
            "invalid_bead_snooze_preview",
            BEAD_SNOOZE_PREVIEW_PATH,
            "bead snooze preview does not match the registered adapter",
        )
