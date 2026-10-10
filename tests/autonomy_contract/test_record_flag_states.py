"""Launch-row outcomes and record shape (``record`` phase).

Each spelling row runs the real launch path: gate outcomes must match the
row contract, the record must carry revision 1, and launches must write
no legacy meta keys.
"""

from __future__ import annotations

import pytest

from sase.autonomy.record import LEGACY_AUTONOMY_KEYS

from . import harness
from .rows import SPELLING_ROWS
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_launch_row_outcomes_match_contract(
    row, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every launch row resolves to its contracted gate outcomes."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    outcomes = harness.row_outcomes(
        row.prompt, workdir, tale_plan, epic_plan, monkeypatch=monkeypatch
    )

    assert outcomes == {
        "tale": row.tale,
        "epic": row.epic,
        "question": row.question,
    }


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_launch_row_record_shape(row, tmp_path) -> None:
    """The record carries revision 1 and launches write no legacy keys."""
    _, meta, _ = harness.launch_meta(row.prompt, tmp_path)

    assert meta["autonomy"]["revision"] == 1
    assert not any(key in meta for key in LEGACY_AUTONOMY_KEYS)
