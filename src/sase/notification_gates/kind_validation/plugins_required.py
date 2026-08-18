"""Validation contract for PluginsRequired gates."""

from __future__ import annotations

from typing import cast

from sase.notification_gates.kind_validation.plugins_required_payload import (
    PluginsRequiredPayload,
    parse_plugins_required_payload,
)
from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateOption, GateSpec


def validate_plugins_required_spec(spec: GateSpec) -> None:
    """Keep PluginsRequired gates on their human-only install-offer contract."""
    _validate_plugins_required_structure(spec)
    payload = parse_plugins_required_payload(spec.payload)
    _validate_plugins_required_options(spec)
    preview_content = _validate_plugins_required_resources(spec, payload)
    _validate_plugins_required_presentation(spec, payload)
    _validate_plugins_required_preview(payload, preview_content)


def _validate_plugins_required_structure(spec: GateSpec) -> None:
    from sase.plugins.required_gate import (
        PLUGINS_REQUIRED_CONTINUATION_MODE,
        PLUGINS_REQUIRED_QUERY,
    )

    if spec.continuation_mode != PLUGINS_REQUIRED_CONTINUATION_MODE:
        raise GateError(
            "invalid_plugins_required_continuation",
            "continuation_mode",
            f"plugins required gates require {PLUGINS_REQUIRED_CONTINUATION_MODE}",
        )
    if spec.query != PLUGINS_REQUIRED_QUERY or spec.branches != (
        ("install",),
        ("dismiss",),
    ):
        raise GateError(
            "invalid_plugins_required_query",
            "query",
            f"plugins required gates require query: {PLUGINS_REQUIRED_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_plugins_required_structure",
            "groups",
            "plugins required gates do not define groups or operations",
        )


def _validate_plugins_required_options(spec: GateSpec) -> None:
    from sase.plugins.required_gate import (
        PLUGINS_REQUIRED_OPTION_IDS,
        PluginsRequiredAction,
        plugins_required_option_spec,
    )

    if tuple(option.id for option in spec.options) != PLUGINS_REQUIRED_OPTION_IDS:
        raise GateError(
            "invalid_plugins_required_options",
            "options",
            "plugins required gates require install and dismiss options",
        )
    for index, option in enumerate(spec.options):
        typed_option_id = cast(PluginsRequiredAction, option.id)
        expected = GateOption.from_mapping(
            plugins_required_option_spec(typed_option_id), index
        )
        if option != expected:
            raise GateError(
                "invalid_plugins_required_options",
                f"options.{option.id}",
                "plugins required option does not match the registered adapter",
            )


def _validate_plugins_required_resources(
    spec: GateSpec, payload: PluginsRequiredPayload
) -> str | None:
    from sase.plugins.required_gate import (
        PLUGINS_REQUIRED_COMMAND_PATHS,
        PLUGINS_REQUIRED_PREVIEW_PATH,
        plugins_required_gate_command_script,
        plugins_required_install_queries,
    )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *PLUGINS_REQUIRED_COMMAND_PATHS.values(),
        PLUGINS_REQUIRED_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_plugins_required_resources",
            "resources",
            "plugins required gates require only their preview and command resources",
        )
    preview = resources[PLUGINS_REQUIRED_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_plugins_required_preview",
            PLUGINS_REQUIRED_PREVIEW_PATH,
            "plugins required preview resource is invalid",
        )
    preview_content = read_gate_resource(
        preview,
        code="invalid_plugins_required_preview",
        description="plugins required preview",
    )
    names = plugins_required_install_queries(payload.missing)
    for option_id, path in PLUGINS_REQUIRED_COMMAND_PATHS.items():
        command = resources[path]
        if command.role != "command" or not command.executable:
            raise GateError(
                "invalid_plugins_required_command",
                path,
                "plugins required command resource is invalid",
            )
        content = read_gate_resource(
            command,
            code="invalid_plugins_required_command",
            description="plugins required command",
        )
        expected = plugins_required_gate_command_script(option_id, requirements=names)
        if content != expected:
            raise GateError(
                "invalid_plugins_required_command",
                path,
                "plugins required command does not match the registered adapter",
            )
    return preview_content


def _validate_plugins_required_presentation(
    spec: GateSpec, payload: PluginsRequiredPayload
) -> None:
    from sase.plugins.required_gate import (
        PLUGINS_REQUIRED_PREVIEW_PATH,
        plugins_required_presentation_note,
    )

    expected_note = plugins_required_presentation_note(payload)
    presentation = spec.presentation
    if (
        presentation.get("sender") != "plugin"
        or presentation.get("icon") != "📦"
        or presentation.get("title")
        != f"Missing required plugins — {payload.project_label}"
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["plugin", "required"]
        or presentation.get("panel") != "plugins"
        or presentation.get("panel_icon") != "📦"
        or presentation.get("origin_agent") is not None
        or presentation.get("files") != [PLUGINS_REQUIRED_PREVIEW_PATH]
        or presentation.get("preview") != PLUGINS_REQUIRED_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_plugins_required_presentation",
            "presentation",
            "plugins required presentation does not match the registered adapter",
        )


def _validate_plugins_required_preview(
    payload: PluginsRequiredPayload, preview_content: str | None
) -> None:
    from sase.plugins.required_gate import (
        PLUGINS_REQUIRED_PREVIEW_PATH,
        render_plugins_required_preview,
    )

    if preview_content != render_plugins_required_preview(payload):
        raise GateError(
            "invalid_plugins_required_preview",
            PLUGINS_REQUIRED_PREVIEW_PATH,
            "plugins required preview does not match the registered adapter",
        )
