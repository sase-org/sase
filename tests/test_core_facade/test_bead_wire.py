"""Phase-size conversion tests for the Python bead wire."""

from __future__ import annotations

import pytest

from sase.bead.model import PhaseSize
from sase.core.bead_wire import issue_from_dict, phase_size_value


@pytest.mark.parametrize("size", [PhaseSize.XSMALL, PhaseSize.XLARGE])
def test_extended_phase_sizes_round_trip_through_wire(size: PhaseSize) -> None:
    issue = issue_from_dict(
        {
            "id": "beads-1.1",
            "title": "Sized phase",
            "issue_type": "phase",
            "parent_id": "beads-1",
            "size": phase_size_value(size),
        }
    )

    assert issue.size is size
