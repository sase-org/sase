"""Tests for sase.ace.tui.widgets.timestamps_builder."""

from __future__ import annotations

from rich.text import Text

from sase.ace.changespec.models import ChangeSpec, TimestampEntry
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.timestamps_builder import build_timestamps_section


def _make_changespec(
    timestamps: list[TimestampEntry] | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name="test-cl",
        description="test",
        parent=None,
        cl=None,
        status="WIP",
        test_targets=None,
        kickstart=None,
        file_path="proj.gp",
        line_number=1,
        timestamps=timestamps,
    )


def _make_entries() -> list[TimestampEntry]:
    return [
        TimestampEntry(
            timestamp="2026-03-29 10:00:00",
            event_type="COMMIT",
            detail="(1)",
        ),
        TimestampEntry(
            timestamp="2026-03-29 10:05:00",
            event_type="STATUS",
            detail="WIP -> Draft",
        ),
        TimestampEntry(
            timestamp="2026-03-29 10:10:00",
            event_type="SYNC",
            detail="(2)",
        ),
    ]


class TestCollapsed:
    def test_collapsed_shows_folded_count(self) -> None:
        entries = _make_entries()
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.COLLAPSED)
        plain = text.plain
        assert "TIMESTAMPS:" in plain
        assert "[folded: 3]" in plain

    def test_collapsed_no_timestamps_shows_nothing(self) -> None:
        cs = _make_changespec(timestamps=None)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.COLLAPSED)
        assert text.plain == ""


class TestExpanded:
    def test_expanded_shows_commit_entries_only(self) -> None:
        entries = _make_entries()
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.EXPANDED)
        plain = text.plain
        assert "TIMESTAMPS:" in plain
        assert "COMMIT" in plain
        # STATUS and SYNC entries should be filtered out
        assert "STATUS" not in plain
        assert "SYNC" not in plain


class TestFullyExpanded:
    def test_fully_expanded_shows_all_entries(self) -> None:
        entries = _make_entries()
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        assert "TIMESTAMPS:" in plain
        assert "COMMIT" in plain
        assert "STATUS" in plain
        assert "SYNC" in plain
