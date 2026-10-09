"""Flag-state parametrization of every launch row (``record`` phase).

Each spelling row runs the real launch path with
``autonomy_record_only`` on and off: gate outcomes must be identical in
both states, the record must match in both states, and legacy meta keys
must appear only with the flag off.
"""

from __future__ import annotations

import pytest

from sase.autonomy.record import LEGACY_AUTONOMY_KEYS
from sase.feature_flags import override_flags

from . import harness
from .rows import SPELLING_ROWS
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_launch_row_same_outcomes_both_flag_states(
    row, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every launch row resolves identically with the flag on and off."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    outcomes_on = harness.row_outcomes(
        row.prompt, workdir, tale_plan, epic_plan, monkeypatch=monkeypatch
    )
    with override_flags(autonomy_record_only=False):
        outcomes_off = harness.row_outcomes(
            row.prompt, workdir, tale_plan, epic_plan, monkeypatch=monkeypatch
        )

    assert outcomes_on == {
        "tale": row.tale,
        "epic": row.epic,
        "question": row.question,
    }
    assert outcomes_off == outcomes_on


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_launch_row_record_shape_both_flag_states(row, tmp_path) -> None:
    """The record matches in both states; legacy keys only when off."""
    _, on_meta, _ = harness.launch_meta(row.prompt, tmp_path / "on")
    with override_flags(autonomy_record_only=False):
        _, off_meta, _ = harness.launch_meta(row.prompt, tmp_path / "off")

    assert on_meta["autonomy"] == off_meta["autonomy"]
    assert on_meta["autonomy"]["revision"] == 1
    assert not any(key in on_meta for key in LEGACY_AUTONOMY_KEYS)
    for key in LEGACY_AUTONOMY_KEYS:
        if key in off_meta:
            assert off_meta[key] not in (None, False)
