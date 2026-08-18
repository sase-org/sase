"""PluginsRequired trusted-kind validation against forged gate contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plugins.required_gate import PLUGINS_REQUIRED_PREVIEW_PATH

from tests.test_plugins_required_gate_helpers import (
    missing_entry,
    plugins_required_spec,
)


def test_plugins_required_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = plugins_required_spec(request_id="plugins-required-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


def _preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == PLUGINS_REQUIRED_PREVIEW_PATH
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(continuation_mode="flag_triage"),
            "invalid_plugins_required_continuation",
        ),
        (
            lambda spec: spec["options"][0].update(label="Install them"),
            "invalid_plugins_required_options",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_plugins_required_payload",
        ),
        (
            lambda spec: spec["payload"].update(missing=[]),
            "invalid_plugins_required_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                missing=[missing_entry(), missing_entry()]
            ),
            "invalid_plugins_required_payload",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_plugins_required_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_plugins_required_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="beads"),
            "invalid_plugins_required_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_plugins_required_presentation",
        ),
        (
            lambda spec: _preview_resource(spec).update(
                content=_preview_resource(spec)["content"].replace(
                    "restarts axe", "does not restart axe"
                )
            ),
            "invalid_plugins_required_preview",
        ),
    ],
)
def test_plugins_required_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(plugins_required_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code
