"""Validation contract for BeadStaleCleanup gates."""

from __future__ import annotations

from sase.notification_gates.kind_validation.bead_stale_cleanup_payload import (
    BeadStaleCleanupPayload,
    parse_bead_stale_cleanup_payload,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateOption, GateSpec


def validate_bead_stale_cleanup_spec(spec: GateSpec) -> None:
    """Keep BeadStaleCleanup gates on their human-only trusted close contract."""
    _validate_bead_stale_cleanup_structure(spec)
    payload = parse_bead_stale_cleanup_payload(spec.payload)
    _validate_bead_stale_cleanup_options(spec, payload)
    preview_content = _validate_bead_stale_cleanup_resources(spec, payload)
    _validate_bead_stale_cleanup_presentation(spec, payload)
    _validate_bead_stale_cleanup_preview(payload, preview_content)


def _validate_bead_stale_cleanup_structure(spec: GateSpec) -> None:
    from sase.bead.stale_cleanup_gate import (
        BEAD_STALE_CLEANUP_CONTINUATION_MODE,
        BEAD_STALE_CLEANUP_QUERY,
    )

    if spec.continuation_mode != BEAD_STALE_CLEANUP_CONTINUATION_MODE:
        raise GateError(
            "invalid_bead_stale_cleanup_continuation",
            "continuation_mode",
            f"bead stale cleanup gates require {BEAD_STALE_CLEANUP_CONTINUATION_MODE}",
        )
    if spec.query != BEAD_STALE_CLEANUP_QUERY or spec.branches != (("close",),):
        raise GateError(
            "invalid_bead_stale_cleanup_query",
            "query",
            f"bead stale cleanup gates require query: {BEAD_STALE_CLEANUP_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_bead_stale_cleanup_structure",
            "groups",
            "bead stale cleanup gates do not define groups or operations",
        )


def _validate_bead_stale_cleanup_options(
    spec: GateSpec, payload: BeadStaleCleanupPayload
) -> None:
    """Rebuild the one option from the adapter and compare it whole.

    Comparing the parsed option rather than a hand-listed set of its fields
    is what keeps the per-bead close/keep inputs from drifting: a forged
    ``inputs`` declaration compiles to a different ``input_schema`` and both
    differences are caught by the same check.
    """
    from sase.bead.stale_cleanup_gate import (
        BEAD_STALE_CLEANUP_OPTION_IDS,
        bead_stale_cleanup_option_spec,
    )

    if tuple(option.id for option in spec.options) != BEAD_STALE_CLEANUP_OPTION_IDS:
        raise GateError(
            "invalid_bead_stale_cleanup_options",
            "options",
            "bead stale cleanup gates require a single close option",
        )
    expected = GateOption.from_mapping(bead_stale_cleanup_option_spec(payload), 0)
    if spec.options[0] != expected:
        raise GateError(
            "invalid_bead_stale_cleanup_options",
            "options.close",
            "bead stale cleanup option does not match the registered adapter",
        )


def _validate_bead_stale_cleanup_resources(
    spec: GateSpec, payload: BeadStaleCleanupPayload
) -> str | None:
    """Check the preview and command resources, returning the preview content."""
    from sase.bead.stale_cleanup_gate import (
        BEAD_STALE_CLEANUP_COMMAND_PATHS,
        BEAD_STALE_CLEANUP_PREVIEW_PATH,
        bead_stale_cleanup_gate_command_script,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *BEAD_STALE_CLEANUP_COMMAND_PATHS.values(),
        BEAD_STALE_CLEANUP_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_bead_stale_cleanup_resources",
            "resources",
            "bead stale cleanup gates require only their preview and command resources",
        )
    preview = resources[BEAD_STALE_CLEANUP_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_bead_stale_cleanup_preview",
            BEAD_STALE_CLEANUP_PREVIEW_PATH,
            "bead stale cleanup preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_bead_stale_cleanup_preview",
        description="bead stale cleanup preview",
    )
    command_path = BEAD_STALE_CLEANUP_COMMAND_PATHS["close"]
    command = resources[command_path]
    if command.role != "command" or not command.executable:
        raise GateError(
            "invalid_bead_stale_cleanup_command",
            command_path,
            "bead stale cleanup command resource is invalid",
        )
    content = read_gate_resource(
        command,
        code="invalid_bead_stale_cleanup_command",
        description="bead stale cleanup command",
    )
    if content != bead_stale_cleanup_gate_command_script(len(payload.beads)):
        raise GateError(
            "invalid_bead_stale_cleanup_command",
            command_path,
            "bead stale cleanup command does not match the registered adapter",
        )
    return preview_content


def _validate_bead_stale_cleanup_presentation(
    spec: GateSpec, payload: BeadStaleCleanupPayload
) -> None:
    from sase.bead.stale_cleanup_gate import (
        BEAD_STALE_CLEANUP_PREVIEW_PATH,
        bead_stale_cleanup_presentation_note,
    )

    expected_note = bead_stale_cleanup_presentation_note(payload)
    presentation = spec.presentation
    if (
        presentation.get("sender") != "bead"
        or presentation.get("icon") != "🧹"
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["bead", "task", "stale"]
        or presentation.get("panel") != "beads"
        or presentation.get("panel_icon") != "◈"
        or presentation.get("origin_agent") is not None
        or presentation.get("files") != [BEAD_STALE_CLEANUP_PREVIEW_PATH]
        or presentation.get("preview") != BEAD_STALE_CLEANUP_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_bead_stale_cleanup_presentation",
            "presentation",
            "bead stale cleanup presentation does not match the registered adapter",
        )


def _validate_bead_stale_cleanup_preview(
    payload: BeadStaleCleanupPayload, preview_content: str | None
) -> None:
    """Reconstruct the preview from its payload and compare it byte for byte."""
    from sase.bead.stale_cleanup_gate import (
        BEAD_STALE_CLEANUP_PREVIEW_PATH,
        render_bead_stale_cleanup_preview,
    )

    if preview_content != render_bead_stale_cleanup_preview(payload):
        raise GateError(
            "invalid_bead_stale_cleanup_preview",
            BEAD_STALE_CLEANUP_PREVIEW_PATH,
            "bead stale cleanup preview does not match the registered adapter",
        )
