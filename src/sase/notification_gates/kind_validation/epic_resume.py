"""Validation contract for EpicResume gates."""

from __future__ import annotations

from sase.notification_gates.kind_validation.epic_resume_payload import (
    EpicResumePayload,
    parse_epic_resume_payload,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateOption, GateSpec


def validate_epic_resume_spec(spec: GateSpec) -> None:
    """Keep EpicResume gates on their human-only trusted resume contract."""
    _validate_epic_resume_structure(spec)
    payload = parse_epic_resume_payload(spec.payload)
    _validate_epic_resume_options(spec)
    preview_content = _validate_epic_resume_resources(spec)
    _validate_epic_resume_presentation(spec, payload)
    _validate_epic_resume_preview(payload, preview_content)


def _validate_epic_resume_structure(spec: GateSpec) -> None:
    from sase.bead.epic_resume_gate import (
        EPIC_RESUME_CONTINUATION_MODE,
        EPIC_RESUME_QUERY,
    )

    if spec.continuation_mode != EPIC_RESUME_CONTINUATION_MODE:
        raise GateError(
            "invalid_epic_resume_continuation",
            "continuation_mode",
            f"epic resume gates require {EPIC_RESUME_CONTINUATION_MODE}",
        )
    if spec.query != EPIC_RESUME_QUERY or spec.branches != (("resume",),):
        raise GateError(
            "invalid_epic_resume_query",
            "query",
            f"epic resume gates require query: {EPIC_RESUME_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_epic_resume_structure",
            "groups",
            "epic resume gates do not define groups or operations",
        )


def _validate_epic_resume_options(spec: GateSpec) -> None:
    """Rebuild the one option from the adapter and compare it whole."""
    from sase.bead.epic_resume_gate import (
        EPIC_RESUME_OPTION_IDS,
        epic_resume_option_spec,
    )

    if tuple(option.id for option in spec.options) != EPIC_RESUME_OPTION_IDS:
        raise GateError(
            "invalid_epic_resume_options",
            "options",
            "epic resume gates require a single resume option",
        )
    expected = GateOption.from_mapping(epic_resume_option_spec(), 0)
    if spec.options[0] != expected:
        raise GateError(
            "invalid_epic_resume_options",
            "options.resume",
            "epic resume option does not match the registered adapter",
        )


def _validate_epic_resume_resources(spec: GateSpec) -> str | None:
    """Check the preview and command resources, returning the preview content."""
    from sase.bead.epic_resume_gate import (
        EPIC_RESUME_COMMAND_PATHS,
        EPIC_RESUME_PREVIEW_PATH,
        epic_resume_gate_command_script,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *EPIC_RESUME_COMMAND_PATHS.values(),
        EPIC_RESUME_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_epic_resume_resources",
            "resources",
            "epic resume gates require only their preview and command resources",
        )
    preview = resources[EPIC_RESUME_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_epic_resume_preview",
            EPIC_RESUME_PREVIEW_PATH,
            "epic resume preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_epic_resume_preview",
        description="epic resume preview",
    )
    command_path = EPIC_RESUME_COMMAND_PATHS["resume"]
    command = resources[command_path]
    if command.role != "command" or not command.executable:
        raise GateError(
            "invalid_epic_resume_command",
            command_path,
            "epic resume command resource is invalid",
        )
    content = read_gate_resource(
        command,
        code="invalid_epic_resume_command",
        description="epic resume command",
    )
    if content != epic_resume_gate_command_script():
        raise GateError(
            "invalid_epic_resume_command",
            command_path,
            "epic resume command does not match the registered adapter",
        )
    return preview_content


def _validate_epic_resume_presentation(
    spec: GateSpec, payload: EpicResumePayload
) -> None:
    from sase.bead.epic_resume_gate import (
        EPIC_RESUME_PREVIEW_PATH,
        epic_resume_presentation_note,
        epic_resume_presentation_title,
    )

    expected_note = epic_resume_presentation_note(payload)
    expected_title = epic_resume_presentation_title(payload.epic_id)
    presentation = spec.presentation
    if (
        presentation.get("sender") != "bead"
        or presentation.get("icon") != "🔁"
        or presentation.get("title") != expected_title
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["bead", "epic", "resume"]
        or presentation.get("panel") != "beads"
        or presentation.get("panel_icon") != "◈"
        or presentation.get("origin_agent") is not None
        or presentation.get("files") != [EPIC_RESUME_PREVIEW_PATH]
        or presentation.get("preview") != EPIC_RESUME_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_epic_resume_presentation",
            "presentation",
            "epic resume presentation does not match the registered adapter",
        )


def _validate_epic_resume_preview(
    payload: EpicResumePayload, preview_content: str | None
) -> None:
    """Reconstruct the preview from its payload and compare it byte for byte."""
    from sase.bead.epic_resume_gate import (
        EPIC_RESUME_PREVIEW_PATH,
        render_epic_resume_preview,
    )

    if preview_content != render_epic_resume_preview(payload):
        raise GateError(
            "invalid_epic_resume_preview",
            EPIC_RESUME_PREVIEW_PATH,
            "epic resume preview does not match the registered adapter",
        )
