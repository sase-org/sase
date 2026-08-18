"""Trusted notification-gate contract for missing required plugins.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and host effects from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.plugins._required_gate_spec` — constants, request spec, commands
- :mod:`sase.plugins._required_gate_preview` — the Markdown and notification text
- :mod:`sase.plugins._required_gate_response` — persisted response → trusted decision
- :mod:`sase.plugins._required_gate_actions` — the host effect a decision authorizes
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.plugins._required_gate_actions import apply_plugins_required_decision
from sase.plugins._required_gate_preview import (
    plugins_required_presentation_note,
    render_plugins_required_preview,
)
from sase.plugins._required_gate_response import (
    PluginsRequiredResponse,
    translate_plugins_required_response,
)
from sase.plugins._required_gate_spec import (
    PLUGINS_REQUIRED_COMMAND_PATHS,
    PLUGINS_REQUIRED_CONTINUATION_MODE,
    PLUGINS_REQUIRED_DISMISS_OPTION_ID,
    PLUGINS_REQUIRED_INSTALL_OPTION_ID,
    PLUGINS_REQUIRED_KIND,
    PLUGINS_REQUIRED_MISSING_KINDS,
    PLUGINS_REQUIRED_OPTION_ICONS,
    PLUGINS_REQUIRED_OPTION_IDS,
    PLUGINS_REQUIRED_OPTION_LABELS,
    PLUGINS_REQUIRED_PREVIEW_PATH,
    PLUGINS_REQUIRED_PRIMARY_BRANCH,
    PLUGINS_REQUIRED_QUERY,
    PluginsRequiredAction,
    build_plugins_required_gate_spec,
    execute_plugins_required_gate_command,
    plugins_required_gate_command_script,
    plugins_required_install_queries,
    plugins_required_missing_payload,
    plugins_required_option_spec,
    plugins_required_result_schema,
)


def create_plugins_required_gate(
    *,
    request_id: str,
    project: str,
    missing: Sequence[Any],
    project_label: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> Any:
    """Create one human-only install-offer gate for a project's missing set."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_plugins_required_gate_spec(
            request_id=request_id,
            project=project,
            missing=missing,
            project_label=project_label,
            producer=producer,
        )
    )


__all__ = [
    "PLUGINS_REQUIRED_COMMAND_PATHS",
    "PLUGINS_REQUIRED_CONTINUATION_MODE",
    "PLUGINS_REQUIRED_DISMISS_OPTION_ID",
    "PLUGINS_REQUIRED_INSTALL_OPTION_ID",
    "PLUGINS_REQUIRED_KIND",
    "PLUGINS_REQUIRED_MISSING_KINDS",
    "PLUGINS_REQUIRED_OPTION_ICONS",
    "PLUGINS_REQUIRED_OPTION_IDS",
    "PLUGINS_REQUIRED_OPTION_LABELS",
    "PLUGINS_REQUIRED_PREVIEW_PATH",
    "PLUGINS_REQUIRED_PRIMARY_BRANCH",
    "PLUGINS_REQUIRED_QUERY",
    "PluginsRequiredAction",
    "PluginsRequiredResponse",
    "apply_plugins_required_decision",
    "build_plugins_required_gate_spec",
    "create_plugins_required_gate",
    "execute_plugins_required_gate_command",
    "plugins_required_gate_command_script",
    "plugins_required_install_queries",
    "plugins_required_missing_payload",
    "plugins_required_option_spec",
    "plugins_required_presentation_note",
    "plugins_required_result_schema",
    "render_plugins_required_preview",
    "translate_plugins_required_response",
]
