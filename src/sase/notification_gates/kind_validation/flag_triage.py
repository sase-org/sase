"""Validation contract for FlagTriage gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sase.notification_gates.kind_validation.flag_triage_payload import (
    FlagTriagePayload,
    parse_flag_triage_payload,
)
from sase.notification_gates.kind_validation.preview_recovery import (
    preview_matches_renderer,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateOption, GateSpec


def validate_flag_triage_spec(spec: GateSpec) -> None:
    """Keep FlagTriage gates on their human-only trusted removal contract."""
    _validate_flag_triage_structure(spec)
    payload = parse_flag_triage_payload(spec.payload)
    _validate_flag_triage_options(spec)
    preview_content = _validate_flag_triage_resources(spec)
    _validate_flag_triage_presentation(spec, payload)
    _validate_flag_triage_preview(spec, payload, preview_content)


def _validate_flag_triage_structure(spec: GateSpec) -> None:
    from sase.bead.flag_gate import FLAG_TRIAGE_CONTINUATION_MODE, FLAG_TRIAGE_QUERY

    if spec.continuation_mode != FLAG_TRIAGE_CONTINUATION_MODE:
        raise GateError(
            "invalid_flag_triage_continuation",
            "continuation_mode",
            f"flag triage gates require {FLAG_TRIAGE_CONTINUATION_MODE}",
        )
    if spec.query != FLAG_TRIAGE_QUERY or spec.branches != (
        ("remove",),
        ("extend",),
        ("keep",),
        ("close",),
    ):
        raise GateError(
            "invalid_flag_triage_query",
            "query",
            f"flag triage gates require query: {FLAG_TRIAGE_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_flag_triage_structure",
            "groups",
            "flag triage gates do not define groups or operations",
        )


def _validate_flag_triage_options(spec: GateSpec) -> None:
    """Rebuild every option from the adapter and compare it whole.

    Comparing the parsed option rather than a hand-listed set of its fields is
    what keeps the declared winner enum and new-threshold inputs from
    drifting: a forged ``inputs`` declaration compiles to a different
    ``input_schema`` and both differences are caught by the same check.
    """
    from sase.bead.flag_gate import (
        FLAG_TRIAGE_OPTION_IDS,
        FlagTriageAction,
        flag_triage_option_spec,
    )

    if tuple(option.id for option in spec.options) != FLAG_TRIAGE_OPTION_IDS:
        raise GateError(
            "invalid_flag_triage_options",
            "options",
            "flag triage gates require remove, extend, keep, and close options",
        )
    for index, option in enumerate(spec.options):
        typed_option_id = cast(FlagTriageAction, option.id)
        expected = GateOption.from_mapping(
            flag_triage_option_spec(typed_option_id), index
        )
        if option != expected:
            raise GateError(
                "invalid_flag_triage_options",
                f"options.{option.id}",
                "flag triage option does not match the registered adapter",
            )


def _validate_flag_triage_resources(spec: GateSpec) -> str | None:
    """Check the preview and command resources, returning the preview content."""
    from sase.bead.flag_gate import (
        FLAG_TRIAGE_COMMAND_PATHS,
        FLAG_TRIAGE_PREVIEW_PATH,
        flag_triage_gate_command_script,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *FLAG_TRIAGE_COMMAND_PATHS.values(),
        FLAG_TRIAGE_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_flag_triage_resources",
            "resources",
            "flag triage gates require only their preview and command resources",
        )
    preview = resources[FLAG_TRIAGE_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_flag_triage_preview",
            FLAG_TRIAGE_PREVIEW_PATH,
            "flag triage preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_flag_triage_preview",
        description="flag triage preview",
    )
    for option_id, path in FLAG_TRIAGE_COMMAND_PATHS.items():
        command = resources[path]
        if command.role != "command" or not command.executable:
            raise GateError(
                "invalid_flag_triage_command",
                path,
                "flag triage command resource is invalid",
            )
        content = read_gate_resource(
            command,
            code="invalid_flag_triage_command",
            description="flag triage command",
        )
        if content != flag_triage_gate_command_script(option_id):
            raise GateError(
                "invalid_flag_triage_command",
                path,
                "flag triage command does not match the registered adapter",
            )
    return preview_content


def _validate_flag_triage_presentation(
    spec: GateSpec, payload: FlagTriagePayload
) -> None:
    from sase.bead.flag_gate import flag_triage_presentation

    origin_agent = _presentation_origin_agent(
        spec.presentation, "invalid_flag_triage_presentation"
    )
    expected = flag_triage_presentation(
        bead_id=payload.bead_id,
        title=payload.title,
        flag=payload.flag,
        due_as_of=payload.due_as_of,
        release=payload.release,
        origin_agent=origin_agent,
        task_type=payload.task_type,
        task_type_display=payload.task_type_display,
    )
    if spec.presentation != expected:
        raise GateError(
            "invalid_flag_triage_presentation",
            "presentation",
            "flag triage presentation does not match the registered adapter",
        )


def _validate_flag_triage_preview(
    spec: GateSpec, payload: FlagTriagePayload, preview_content: str | None
) -> None:
    """Reconstruct the preview from its payload and compare it byte for byte.

    The agent-authored description and notes are not carried by the payload, so
    they are recovered from the persisted preview by rendering a marker-bearing
    template and slicing the body the markers delimit.
    """
    from sase.bead.flag_gate import (
        FLAG_TRIAGE_PREVIEW_PATH,
        render_flag_triage_preview,
    )

    origin_agent = spec.presentation.get("origin_agent")
    created_by = cast(str, origin_agent or "")

    def render(description: str, notes: str) -> str:
        return render_flag_triage_preview(
            bead_id=payload.bead_id,
            title=payload.title,
            description=description,
            notes=notes,
            flag=payload.flag,
            due_as_of=payload.due_as_of,
            release=payload.release,
            definition=payload.definition,
            kind=payload.kind,
            created_by=created_by,
            created_at=payload.created_at,
            size=payload.size,
            task_type=payload.task_type,
            task_type_fields=payload.task_type_fields,
            task_type_display=payload.task_type_display,
            call_sites=payload.call_sites,
        )

    matches = preview_matches_renderer(
        render=render,
        description_marker="__FLAG_TRIAGE_DESCRIPTION__",
        notes_marker="__FLAG_TRIAGE_NOTES__",
        preview_content=preview_content,
    )
    if not matches:
        raise GateError(
            "invalid_flag_triage_preview",
            FLAG_TRIAGE_PREVIEW_PATH,
            "flag triage preview does not match the registered adapter",
        )


def _presentation_origin_agent(presentation: Mapping[str, Any], code: str) -> str:
    origin_agent = presentation.get("origin_agent")
    if origin_agent is None:
        return ""
    if not isinstance(origin_agent, str) or not origin_agent:
        raise GateError(
            code,
            "presentation",
            "flag triage presentation does not match the registered adapter",
        )
    return origin_agent
