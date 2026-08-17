"""Trusted BeadStaleCleanup response translation coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead._stale_cleanup_gate_response import (
    BeadStaleCleanupResponse,
    translate_bead_stale_cleanup_response,
)
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.stale_cleanup_gate_test_helpers import (
    stale_cleanup_bead,
    stale_cleanup_spec,
)
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def _response(
    *,
    indexes: list[int] | None = None,
    feedback: str | None = None,
    source: str = "tui",
    **overrides: Any,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "selected_option_ids": ["close"],
        "option_results": [
            {
                "id": "close",
                "result": {
                    "action": "close",
                    "close_bead_indexes": indexes if indexes is not None else [1, 2],
                },
            }
        ],
        "source": source,
    }
    if feedback is not None:
        response["feedback"] = feedback
    response.update(overrides)
    return response


def test_bead_stale_cleanup_translation_maps_indexes_through_the_roster(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(
        stale_cleanup_spec(
            request_id="bead-stale-cleanup-translate",
            beads=[
                stale_cleanup_bead(),
                stale_cleanup_bead(bead_id="sase-task.2", project="sase"),
            ],
        )
    )

    translated = translate_bead_stale_cleanup_response(
        gate.bundle_path,
        _response(indexes=[2, 1], feedback="too noisy", source="mobile"),
    )

    assert translated == BeadStaleCleanupResponse(
        beads=(("sase", "sase-task.2"), ("sase", "sase-task.1")),
        feedback="too noisy",
        source="mobile",
    )


def test_bead_stale_cleanup_translation_rejects_non_stale_cleanup_bundle(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="not-stale-cleanup"))

    with pytest.raises(GateError) as exc_info:
        translate_bead_stale_cleanup_response(gate.bundle_path, _response(indexes=[1]))

    assert exc_info.value.code == "invalid_response"


@pytest.mark.parametrize(
    ("indexes", "request_id"),
    [
        ([], "bead-stale-cleanup-empty-indexes"),
        ([0], "bead-stale-cleanup-zero-index"),
        ([3], "bead-stale-cleanup-outside-index"),
        ([1, 1], "bead-stale-cleanup-dup-index"),
    ],
)
def test_bead_stale_cleanup_translation_rejects_bad_indexes(
    gate_home: Path,
    indexes: list[int],
    request_id: str,
) -> None:
    del gate_home
    gate = create_gate(
        stale_cleanup_spec(
            request_id=request_id,
            beads=[
                stale_cleanup_bead(),
                stale_cleanup_bead(bead_id="sase-task.2"),
            ],
        )
    )

    with pytest.raises(GateError) as exc_info:
        translate_bead_stale_cleanup_response(
            gate.bundle_path, _response(indexes=indexes)
        )

    assert exc_info.value.code == "invalid_response"
