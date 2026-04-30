"""Tests for sase.ace.tui.widgets.deltas_builder."""

from __future__ import annotations

from rich.text import Text

from sase.ace.changespec.models import ChangeSpec, DeltaEntry, DeltaLineStats
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.deltas_builder import build_deltas_section


def _make_changespec(
    deltas: list[DeltaEntry] | None = None,
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
        deltas=deltas,
    )


def _sample_deltas() -> list[DeltaEntry]:
    return [
        DeltaEntry(path="src/sase/ace/changespec/deltas.py", change_type="A"),
        DeltaEntry(path="tests/test_deltas_parsing.py", change_type="A"),
        DeltaEntry(path="src/sase/ace/changespec/models.py", change_type="M"),
        DeltaEntry(path="src/sase/ace/changespec/parser.py", change_type="M"),
        DeltaEntry(path="src/sase/legacy/old_deltas.py", change_type="D"),
    ]


class TestNoDeltas:
    def test_none_renders_nothing(self) -> None:
        cs = _make_changespec(deltas=None)
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        assert text.plain == ""

    def test_empty_list_renders_nothing(self) -> None:
        cs = _make_changespec(deltas=[])
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        assert text.plain == ""


class TestCollapsed:
    def test_collapsed_renders_nothing(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.COLLAPSED)
        assert text.plain == ""


class TestExpanded:
    def test_expanded_shows_summary(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.EXPANDED)
        plain = text.plain
        assert plain.startswith("DELTAS:")
        assert "+2" in plain
        assert "~2" in plain
        assert "-1" in plain
        assert "(5 files)" in plain
        # No individual entries in the summary view.
        assert "deltas.py" not in plain

    def test_expanded_singular_file_label(self) -> None:
        cs = _make_changespec(deltas=[DeltaEntry(path="a.py", change_type="A")])
        text = Text()
        build_deltas_section(text, cs, FoldLevel.EXPANDED)
        assert "(1 file)" in text.plain

    def test_expanded_summary_includes_line_stats(self) -> None:
        cs = _make_changespec(
            deltas=[
                DeltaEntry(
                    path="a.py",
                    change_type="A",
                    line_stats=DeltaLineStats(added=5),
                ),
                DeltaEntry(
                    path="b.py",
                    change_type="M",
                    line_stats=DeltaLineStats(added=2, modified=3, removed=1),
                ),
                DeltaEntry(
                    path="c.py",
                    change_type="D",
                    line_stats=DeltaLineStats(removed=4),
                ),
            ]
        )
        text = Text()
        build_deltas_section(text, cs, FoldLevel.EXPANDED)
        assert "+1 (+5)" in text.plain
        assert "~1 (+2 ~3 -1)" in text.plain
        assert "-1 (-4)" in text.plain

    def test_summary_glyph_styles(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.EXPANDED)
        plain = text.plain
        added_offset = plain.index("+2")
        modified_offset = plain.index("~2")
        deleted_offset = plain.index("-1")
        added_styles = [
            span.style for span in text.spans if span.start <= added_offset < span.end
        ]
        modified_styles = [
            span.style
            for span in text.spans
            if span.start <= modified_offset < span.end
        ]
        deleted_styles = [
            span.style for span in text.spans if span.start <= deleted_offset < span.end
        ]
        assert "bold #5FD787" in added_styles
        assert "bold #FFD787" in modified_styles
        assert "bold #FF5F5F" in deleted_styles


class TestFullyExpanded:
    def test_lists_all_paths_alphabetically(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        assert plain.startswith("DELTAS:\n")
        # Alphabetical sort by path
        positions = [
            plain.index("src/sase/ace/changespec/deltas.py"),
            plain.index("src/sase/ace/changespec/models.py"),
            plain.index("src/sase/ace/changespec/parser.py"),
            plain.index("src/sase/legacy/old_deltas.py"),
            plain.index("tests/test_deltas_parsing.py"),
        ]
        assert positions == sorted(positions)
        # Glyphs match
        assert "+ src/sase/ace/changespec/deltas.py" in plain
        assert "~ src/sase/ace/changespec/models.py" in plain
        assert "- src/sase/legacy/old_deltas.py" in plain

    def test_basename_is_bold(self) -> None:
        cs = _make_changespec(
            deltas=[
                DeltaEntry(path="src/sase/ace/changespec/deltas.py", change_type="A")
            ]
        )
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        basename_offset = plain.index("deltas.py")
        dirname_offset = plain.index("src/sase/")
        basename_styles = [
            span.style
            for span in text.spans
            if span.start <= basename_offset < span.end
        ]
        dirname_styles = [
            span.style for span in text.spans if span.start <= dirname_offset < span.end
        ]
        assert "bold #87AFFF" in basename_styles
        assert "#87AFFF" in dirname_styles

    def test_path_without_directory(self) -> None:
        cs = _make_changespec(deltas=[DeltaEntry(path="README.md", change_type="M")])
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        assert "~ README.md" in plain

    def test_entry_line_stats_render_inline(self) -> None:
        cs = _make_changespec(
            deltas=[
                DeltaEntry(
                    path="README.md",
                    change_type="M",
                    line_stats=DeltaLineStats(added=2, modified=3, removed=1),
                ),
                DeltaEntry(
                    path="image.bin",
                    change_type="A",
                    line_stats=DeltaLineStats(binary=True),
                ),
                DeltaEntry(
                    path="rename.py", change_type="A", line_stats=DeltaLineStats()
                ),
            ]
        )
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        assert "~ README.md  +2 ~3 -1" in plain
        assert "+ image.bin  binary" in plain
        assert "+ rename.py  0 lines" in plain

    def test_glyph_styles(self) -> None:
        cs = _make_changespec(
            deltas=[
                DeltaEntry(path="a.py", change_type="A"),
                DeltaEntry(path="b.py", change_type="M"),
                DeltaEntry(path="c.py", change_type="D"),
            ]
        )
        text = Text()
        build_deltas_section(text, cs, FoldLevel.FULLY_EXPANDED)
        plain = text.plain
        plus_offset = plain.index("+ a.py")
        tilde_offset = plain.index("~ b.py")
        minus_offset = plain.index("- c.py")
        plus_styles = [s.style for s in text.spans if s.start <= plus_offset < s.end]
        tilde_styles = [s.style for s in text.spans if s.start <= tilde_offset < s.end]
        minus_styles = [s.style for s in text.spans if s.start <= minus_offset < s.end]
        assert "bold #5FD787" in plus_styles
        assert "bold #FFD787" in tilde_styles
        assert "bold #FF5F5F" in minus_styles
