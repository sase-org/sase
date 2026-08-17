"""BeadStaleCleanup trusted-kind validation against forged gate contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sase.bead.stale_cleanup_gate import (
    BEAD_STALE_CLEANUP_MAX_BEADS,
    BEAD_STALE_CLEANUP_PREVIEW_PATH,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate

from .stale_cleanup_gate_test_helpers import stale_cleanup_bead, stale_cleanup_spec


def test_bead_stale_cleanup_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = stale_cleanup_spec(request_id="bead-stale-cleanup-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


def _preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == BEAD_STALE_CLEANUP_PREVIEW_PATH
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(continuation_mode="task_triage"),
            "invalid_bead_stale_cleanup_continuation",
        ),
        (
            lambda spec: spec["options"][0].update(label="Sweep them"),
            "invalid_bead_stale_cleanup_options",
        ),
        (
            lambda spec: spec["options"][0]["inputs"][0].update(default="keep"),
            "invalid_bead_stale_cleanup_options",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_bead_stale_cleanup_payload",
        ),
        (
            lambda spec: spec["payload"].update(beads=[]),
            "invalid_bead_stale_cleanup_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                beads=[
                    stale_cleanup_bead(),
                    stale_cleanup_bead(),
                ]
            ),
            "invalid_bead_stale_cleanup_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                beads=[
                    stale_cleanup_bead(bead_id=f"sase-task.{index}")
                    for index in range(1, BEAD_STALE_CLEANUP_MAX_BEADS + 2)
                ]
            ),
            "invalid_bead_stale_cleanup_payload",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_bead_stale_cleanup_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_bead_stale_cleanup_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_bead_stale_cleanup_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_bead_stale_cleanup_presentation",
        ),
        (
            lambda spec: _preview_resource(spec).update(
                content=_preview_resource(spec)["content"].replace("7 days", "8 days")
            ),
            "invalid_bead_stale_cleanup_preview",
        ),
    ],
)
def test_bead_stale_cleanup_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(stale_cleanup_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code
