"""Validation contract for TaskTriage gates."""

from __future__ import annotations

from typing import cast

from sase.notification_gates.kind_validation.preview_recovery import (
    preview_matches_renderer,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.kind_validation.task_triage_payload import (
    TaskTriagePayload,
    parse_task_triage_payload,
)
from sase.notification_gates.models import GateError, GateSpec


def validate_task_triage_spec(spec: GateSpec) -> None:
    """Keep TaskTriage gates on their human-only trusted task contract."""
    _validate_task_triage_structure(spec)
    payload = parse_task_triage_payload(spec.payload)
    _validate_task_triage_options(spec)
    preview_content = _validate_task_triage_resources(spec)
    _validate_task_triage_presentation(spec, payload)
    _validate_task_triage_preview(spec, payload, preview_content)


def _validate_task_triage_structure(spec: GateSpec) -> None:
    from sase.bead.task_gate import (
        TASK_TRIAGE_CONTINUATION_MODE,
        TASK_TRIAGE_QUERY,
    )

    if spec.continuation_mode != TASK_TRIAGE_CONTINUATION_MODE:
        raise GateError(
            "invalid_task_triage_continuation",
            "continuation_mode",
            f"task triage gates require {TASK_TRIAGE_CONTINUATION_MODE}",
        )
    if spec.query != TASK_TRIAGE_QUERY or spec.branches != (
        ("launch",),
        ("close",),
        ("snooze",),
    ):
        raise GateError(
            "invalid_task_triage_query",
            "query",
            f"task triage gates require query: {TASK_TRIAGE_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_task_triage_structure",
            "groups",
            "task triage gates do not define groups or operations",
        )


def _validate_task_triage_options(spec: GateSpec) -> None:
    from sase.bead.task_gate import (
        TASK_TRIAGE_COMMAND_PATHS,
        TASK_TRIAGE_OPTION_FEEDBACK,
        TASK_TRIAGE_OPTION_ICONS,
        TASK_TRIAGE_OPTION_IDS,
        TASK_TRIAGE_OPTION_LABELS,
        TaskTriageAction,
        task_triage_result_schema,
    )

    if tuple(option.id for option in spec.options) != TASK_TRIAGE_OPTION_IDS:
        raise GateError(
            "invalid_task_triage_options",
            "options",
            "task triage gates require launch, close, and snooze options",
        )
    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    for option in spec.options:
        typed_option_id = cast(TaskTriageAction, option.id)
        expected_command = TASK_TRIAGE_COMMAND_PATHS[typed_option_id]
        if (
            option.command.argv != (expected_command,)
            or option.input_schema != empty_input_schema
            or option.result_schema != task_triage_result_schema(typed_option_id)
            or option.feedback != TASK_TRIAGE_OPTION_FEEDBACK[typed_option_id]
            or option.label != TASK_TRIAGE_OPTION_LABELS[typed_option_id]
            or option.icon != TASK_TRIAGE_OPTION_ICONS[typed_option_id]
        ):
            raise GateError(
                "invalid_task_triage_options",
                f"options.{option.id}",
                "task triage option does not match the registered adapter",
            )


def _validate_task_triage_resources(spec: GateSpec) -> str | None:
    """Check the preview and command resources, returning the preview content."""
    from sase.bead.task_gate import (
        TASK_TRIAGE_COMMAND_PATHS,
        TASK_TRIAGE_PREVIEW_PATH,
        task_triage_gate_command_script,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *TASK_TRIAGE_COMMAND_PATHS.values(),
        TASK_TRIAGE_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_task_triage_resources",
            "resources",
            "task triage gates require only their preview and command resources",
        )
    preview = resources[TASK_TRIAGE_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_task_triage_preview",
            TASK_TRIAGE_PREVIEW_PATH,
            "task triage preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_task_triage_preview",
        description="task triage preview",
    )
    for option_id, path in TASK_TRIAGE_COMMAND_PATHS.items():
        command = resources[path]
        if command.role != "command" or not command.executable:
            raise GateError(
                "invalid_task_triage_command",
                path,
                "task triage command resource is invalid",
            )
        content = read_gate_resource(
            command,
            code="invalid_task_triage_command",
            description="task triage command",
        )
        if content != task_triage_gate_command_script(option_id):
            raise GateError(
                "invalid_task_triage_command",
                path,
                "task triage command does not match the registered adapter",
            )
    return preview_content


def _validate_task_triage_presentation(
    spec: GateSpec, payload: TaskTriagePayload
) -> None:
    from sase.bead.task_gate import (
        TASK_TRIAGE_PREVIEW_PATH,
        task_triage_presentation_note,
    )

    expected_note = task_triage_presentation_note(
        payload.bead_id,
        payload.title,
        payload.plus_one_count,
        created_at=payload.created_at,
        reopen_count=len(payload.close_history),
    )
    presentation = spec.presentation
    origin_agent = presentation.get("origin_agent")
    if (
        presentation.get("sender") != "bead"
        or presentation.get("icon") != "✦"
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["bead", "task"]
        or presentation.get("panel") != "beads"
        or (origin_agent is not None and not isinstance(origin_agent, str))
        or (isinstance(origin_agent, str) and not origin_agent)
        or presentation.get("files") != [TASK_TRIAGE_PREVIEW_PATH]
        or presentation.get("preview") != TASK_TRIAGE_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_task_triage_presentation",
            "presentation",
            "task triage presentation does not match the registered adapter",
        )


def _validate_task_triage_preview(
    spec: GateSpec, payload: TaskTriagePayload, preview_content: str | None
) -> None:
    """Reconstruct the preview from its payload and compare it byte for byte.

    The agent-authored description and notes are not carried by the payload, so
    they are recovered from the persisted preview by rendering a marker-bearing
    template and slicing the body the markers delimit.
    """
    from sase.bead.task_gate import (
        TASK_TRIAGE_PREVIEW_PATH,
        render_task_triage_preview,
    )

    origin_agent = spec.presentation.get("origin_agent")
    created_by = cast(str, origin_agent or "")

    def render(description: str, notes: str) -> str:
        return render_task_triage_preview(
            bead_id=payload.bead_id,
            title=payload.title,
            description=description,
            notes=notes,
            created_by=created_by,
            created_at=payload.created_at,
            size=payload.size,
            refs=payload.refs,
            plus_one_evidence=payload.plus_one_evidence,
            close_history=payload.close_history,
        )

    matches = preview_matches_renderer(
        render=render,
        description_marker="__TASK_TRIAGE_DESCRIPTION__",
        notes_marker="__TASK_TRIAGE_NOTES__",
        preview_content=preview_content,
    )
    if not matches:
        raise GateError(
            "invalid_task_triage_preview",
            TASK_TRIAGE_PREVIEW_PATH,
            "task triage preview does not match the registered adapter",
        )
