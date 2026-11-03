"""Adapter binding tests for readout (split from test_readout)."""

from __future__ import annotations

import pytest

from sase.instructions.readout import (
    ACCEPTED,
    MISS,
    MONITOR_PREPARED,
    PLAN_HANDOFF,
)
from tests.instructions._readout_support import passthrough_manifest_normalize


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    passthrough_manifest_normalize(monkeypatch)


def test_adapter_binding_scores_evidence_matrix() -> None:
    """The thin adapter defers to the Rust readout policy without a fallback."""
    from sase.core.instruction_readout import classify_instruction_readout

    assert (
        classify_instruction_readout(
            {
                "handoff": "plan",
                "declaration": "accepted",
                "has_dirty_obligations": True,
            }
        )
        == PLAN_HANDOFF
    )
    assert (
        classify_instruction_readout(
            {
                "handoff": "monitor_prepared",
                "declaration": "not_required",
                "has_dirty_obligations": True,
            }
        )
        == MONITOR_PREPARED
    )
    assert (
        classify_instruction_readout(
            {
                "handoff": "plan",
                "declaration": "missing",
                "has_dirty_obligations": False,
            }
        )
        == PLAN_HANDOFF
    )
    assert (
        classify_instruction_readout(
            {
                "handoff": "plan",
                "declaration": "missing",
                "has_dirty_obligations": True,
            }
        )
        == MISS
    )
    assert (
        classify_instruction_readout(
            {
                "handoff": None,
                "declaration": "accepted",
                "has_dirty_obligations": False,
            }
        )
        == ACCEPTED
    )
    assert (
        classify_instruction_readout(
            {
                "handoff": None,
                "declaration": "missing",
                "has_dirty_obligations": False,
            }
        )
        == MISS
    )


def test_adapter_binding_rejects_unknown_handoff() -> None:
    """Unknown handoff evidence is a contract error, not a silent class."""
    from sase.core.instruction_readout import (
        _InstructionReadoutError,
        classify_instruction_readout,
    )

    with pytest.raises(_InstructionReadoutError):
        classify_instruction_readout(
            {
                "handoff": "future_kind",
                "declaration": "accepted",
                "has_dirty_obligations": False,
            }
        )
