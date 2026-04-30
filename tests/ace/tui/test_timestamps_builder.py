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
        TimestampEntry(
            timestamp="2026-03-29 10:15:00",
            event_type="REWIND",
            detail="(3)",
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
        assert "REWIND" in plain
        assert "(3)" in plain

        digit_offset = plain.index("[folded: 3]") + len("[folded: ")
        bracket_offset = plain.index("[folded: 3]")
        spans_at_digit = [
            span for span in text.spans if span.start <= digit_offset < span.end
        ]
        spans_at_bracket = [
            span for span in text.spans if span.start <= bracket_offset < span.end
        ]
        assert any(span.style == "bold #87D7FF" for span in spans_at_digit)
        assert any(span.style == "italic #808080" for span in spans_at_bracket)

    def test_collapsed_no_timestamps_shows_nothing(self) -> None:
        cs = _make_changespec(timestamps=None)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.COLLAPSED)
        assert text.plain == ""

    def test_collapsed_single_entry_no_folded_indicator(self) -> None:
        entries = [
            TimestampEntry(
                timestamp="2026-03-29 10:00:00",
                event_type="COMMIT",
                detail="(1)",
            ),
        ]
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.COLLAPSED)
        plain = text.plain
        assert "COMMIT" in plain
        assert "folded" not in plain

    def test_collapsed_shows_last_entry_not_first(self) -> None:
        entries = _make_entries()
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.COLLAPSED)
        plain = text.plain
        # Last entry (REWIND) should be visible
        assert "REWIND" in plain
        assert "(3)" in plain
        # First entry's detail should NOT appear
        assert "10:00:00" not in plain


class TestExpanded:
    def test_expanded_shows_commit_and_rewind_entries_only(self) -> None:
        entries = _make_entries()
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.EXPANDED)
        plain = text.plain
        assert "TIMESTAMPS:" in plain
        assert "COMMIT" in plain
        assert "REWIND" in plain
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
        assert "REWIND" in plain

    def test_rebase_entry_uses_rebase_color(self) -> None:
        entries = [
            TimestampEntry(
                timestamp="2026-03-29 10:20:00",
                event_type="REBASE",
                detail="old-parent -> new-parent",
            )
        ]
        cs = _make_changespec(timestamps=entries)
        text = Text()
        build_timestamps_section(text, cs, FoldLevel.FULLY_EXPANDED)

        plain = text.plain
        rebase_offset = plain.index("REBASE")
        arrow_offset = plain.index(" -> ")
        spans_at_rebase = [
            span for span in text.spans if span.start <= rebase_offset < span.end
        ]
        spans_at_arrow = [
            span for span in text.spans if span.start <= arrow_offset < span.end
        ]
        assert any(span.style == "bold #FFAF5F" for span in spans_at_rebase)
        assert any(span.style == "bold #808080" for span in spans_at_arrow)
