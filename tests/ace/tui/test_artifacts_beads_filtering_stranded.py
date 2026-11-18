"""Stranded status filtering behavior for Artifacts Beads."""

from __future__ import annotations

from pathlib import Path

from tests.ace.tui._artifacts_beads_filtering_test_helpers import matched_bead_ids
from tests.ace.tui._artifacts_beads_helpers import snapshot


def _seed_alpha_stranded(*, leaf_id: str = "alpha-1.2") -> None:
    from sase.ace.tui.models import agent_stranded
    from sase.bead.stranded import StrandedReport
    from sase.core.stranded_work_facade import (
        StrandedWorkReport,
        StrandedWorkVerdict,
    )

    agent_stranded._STRANDED_REPORT_CACHE.set(
        "alpha",
        StrandedReport(
            report=StrandedWorkReport(
                verdicts=(
                    StrandedWorkVerdict(
                        bead_id=leaf_id,
                        kind="phase",
                        state="stranded",
                        reason="unclosed",
                        parent_id="alpha-1",
                    ),
                ),
                stranded_ids=(leaf_id,),
                blocked_ids=(),
            ),
            titles={},
            generated_at=1.0,
        ),
        "test",
    )


def test_status_stranded_filter_matches_cached_stranded_leaves(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.models import agent_stranded

    try:
        _seed_alpha_stranded()
        assert matched_bead_ids(tmp_path, "status:stranded") == ["alpha-1.2"]
        assert "alpha-1.2" not in matched_bead_ids(tmp_path, "-status:stranded")
        assert matched_bead_ids(tmp_path, "status:stranded -status:open") == []
    finally:
        agent_stranded._STRANDED_REPORT_CACHE.clear()


def test_status_stranded_index_key_follows_report_replacement(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.models import agent_stranded
    from sase.ace.tui.widgets.artifacts.beads_filtering import (
        beads_filter_source_key,
        build_bead_filter_index,
    )

    value = snapshot(tmp_path)
    try:
        _seed_alpha_stranded(leaf_id="alpha-1.2")
        first = build_bead_filter_index(value)
        assert "stranded" in first.by_option_id["phase:alpha-1.2"].status_labels

        _seed_alpha_stranded(leaf_id="alpha-1.1")
        assert beads_filter_source_key(value) != first.source_key
        second = build_bead_filter_index(value)
        assert second.source_key != first.source_key
        assert "stranded" not in second.by_option_id["phase:alpha-1.2"].status_labels
        assert "stranded" in second.by_option_id["phase:alpha-1.1"].status_labels
    finally:
        agent_stranded._STRANDED_REPORT_CACHE.clear()
