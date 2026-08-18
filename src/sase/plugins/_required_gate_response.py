"""Translation of a persisted PluginsRequired response into trusted host input.

Nothing downstream may trust the answering client, so the action and the
install result are read from the option command's typed result rather than
from free-form response fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.kind_validation.plugins_required_payload import (
    parse_plugins_required_payload,
)
from sase.notification_gates.models import GateError
from sase.plugins._required_gate_spec import (
    PLUGINS_REQUIRED_DISMISS_OPTION_ID,
    PLUGINS_REQUIRED_INSTALL_OPTION_ID,
    PLUGINS_REQUIRED_KIND,
    PLUGINS_REQUIRED_OPTION_IDS,
    PluginsRequiredAction,
)


@dataclass(frozen=True)
class PluginsRequiredResponse:
    """Trusted decision translated from a persisted required-plugin gate."""

    action: PluginsRequiredAction
    project: str
    installed: tuple[str, ...]
    changed: bool
    source: str


def translate_plugins_required_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> PluginsRequiredResponse:
    """Translate one persisted PluginsRequired response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != PLUGINS_REQUIRED_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a plugins required gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "plugins required request payload is missing",
        )
    parsed = parse_plugins_required_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in PLUGINS_REQUIRED_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plugins required response must select exactly install or dismiss",
        )
    action = raw_selected[0]
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plugins required response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == action
        ),
        None,
    )
    if not isinstance(result, Mapping) or result.get("action") != action:
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plugins required response result does not match its selected action",
        )
    installed, changed = _install_result(action, result)
    source = response.get("source")
    return PluginsRequiredResponse(
        action=action,
        project=parsed.project,
        installed=installed,
        changed=changed,
        source=source if isinstance(source, str) and source else "host",
    )


def _install_result(
    action: str, result: Mapping[str, Any]
) -> tuple[tuple[str, ...], bool]:
    if action != PLUGINS_REQUIRED_INSTALL_OPTION_ID:
        if action != PLUGINS_REQUIRED_DISMISS_OPTION_ID:
            raise GateError(
                "invalid_response",
                "action",
                "plugins required response named an unsupported action",
            )
        return (), False
    raw_installed = result.get("installed")
    if not isinstance(raw_installed, list) or not all(
        isinstance(name, str) and name.strip() for name in raw_installed
    ):
        raise GateError(
            "invalid_response",
            "installed",
            "plugins required install result must list installed plugin names",
        )
    changed = result.get("changed")
    if not isinstance(changed, bool):
        raise GateError(
            "invalid_response",
            "changed",
            "plugins required install result must report whether code changed",
        )
    return tuple(raw_installed), changed
