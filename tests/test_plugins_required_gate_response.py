"""Trusted PluginsRequired response translation coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plugins._required_gate_response import (
    PluginsRequiredResponse,
    translate_plugins_required_response,
)
from tests.test_bead.task_gate_test_helpers import task_triage_spec
from tests.test_plugins_required_gate_helpers import plugins_required_spec


def _response(
    *,
    action: str = "install",
    installed: list[str] | None = None,
    changed: bool = True,
    source: str = "tui",
    **overrides: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"action": action}
    if action == "install":
        result["installed"] = installed if installed is not None else ["sase-github"]
        result["changed"] = changed
    response: dict[str, Any] = {
        "selected_option_ids": [action],
        "option_results": [{"id": action, "result": result}],
        "source": source,
    }
    response.update(overrides)
    return response


def test_plugins_required_translation_round_trips_install(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(
        plugins_required_spec(request_id="plugins-required-translate-install")
    )

    translated = translate_plugins_required_response(
        gate.bundle_path,
        _response(installed=["sase-github"], changed=True, source="mobile"),
    )

    assert translated == PluginsRequiredResponse(
        action="install",
        project="sase",
        installed=("sase-github",),
        changed=True,
        source="mobile",
    )


def test_plugins_required_translation_round_trips_dismiss(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(
        plugins_required_spec(request_id="plugins-required-translate-dismiss")
    )

    translated = translate_plugins_required_response(
        gate.bundle_path,
        _response(action="dismiss", source="ace"),
    )

    assert translated == PluginsRequiredResponse(
        action="dismiss",
        project="sase",
        installed=(),
        changed=False,
        source="ace",
    )


def test_plugins_required_translation_rejects_non_plugins_required_bundle(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="not-plugins-required"))

    with pytest.raises(GateError) as exc_info:
        translate_plugins_required_response(
            gate.bundle_path, _response(action="dismiss")
        )

    assert exc_info.value.code == "invalid_response"


def test_plugins_required_translation_rejects_mismatched_action(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(plugins_required_spec(request_id="plugins-required-bad-action"))

    with pytest.raises(GateError) as exc_info:
        translate_plugins_required_response(
            gate.bundle_path,
            {
                "selected_option_ids": ["install"],
                "option_results": [{"id": "install", "result": {"action": "dismiss"}}],
                "source": "tui",
            },
        )

    assert exc_info.value.code == "invalid_response"
