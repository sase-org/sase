"""Tests for sase.ace.tui.widgets.deltas_builder."""

from __future__ import annotations

import os
from pathlib import Path

from pytest import MonkeyPatch
from rich.text import Text

from sase.ace.changespec.models import ChangeSpec, DeltaEntry, DeltaLineStats
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.deltas_builder import build_deltas_section
from sase.ace.tui.widgets.changespec_detail import ChangeSpecDetail
from sase.ace.tui.widgets.hint_tracker import HintTracker


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
    def test_collapsed_renders_summary(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.COLLAPSED)
        assert text.plain == "DELTAS:  +2 ~2 -1 (5 files)\n"
        assert "deltas.py" not in text.plain

    def test_default_renders_summary(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs)
        assert text.plain == "DELTAS:  +2 ~2 -1 (5 files)\n"

    def test_collapsed_singular_file_label(self) -> None:
        cs = _make_changespec(deltas=[DeltaEntry(path="a.py", change_type="A")])
        text = Text()
        build_deltas_section(text, cs, FoldLevel.COLLAPSED)
        assert "(1 file)" in text.plain

    def test_collapsed_summary_includes_line_stats(self) -> None:
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
        build_deltas_section(text, cs, FoldLevel.COLLAPSED)
        assert text.plain == ("DELTAS:  +1 (+5) ~1 (+2 ~3 -1) -1 (-4) (3 files)\n")

    def test_summary_glyph_styles(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.COLLAPSED)
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

    def test_expanded_compatibility_state_lists_paths(self) -> None:
        cs = _make_changespec(deltas=_sample_deltas())
        text = Text()
        build_deltas_section(text, cs, FoldLevel.EXPANDED)
        plain = text.plain
        assert plain.startswith("DELTAS:\n")
        assert "+ src/sase/ace/changespec/deltas.py" in plain
        assert "~ src/sase/ace/changespec/models.py" in plain
        assert "- src/sase/legacy/old_deltas.py" in plain
        assert "(5 files)" not in plain

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


class TestFileHints:
    def test_expanded_entries_emit_hints_and_mappings(self) -> None:
        cs = _make_changespec(
            deltas=[
                DeltaEntry(path="b.py", change_type="M"),
                DeltaEntry(path="a.py", change_type="A"),
            ]
        )
        text = Text()

        tracker = build_deltas_section(
            text,
            cs,
            FoldLevel.FULLY_EXPANDED,
            show_file_hints=True,
        )

        assert "+ [1] a.py" in text.plain
        assert "~ [2] b.py" in text.plain
        assert tracker.mappings == {
            1: os.path.abspath("a.py"),
            2: os.path.abspath("b.py"),
        }
        assert tracker.counter == 3

    def test_relative_paths_resolve_under_workspace_dir(self, tmp_path: Path) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        cs = _make_changespec(deltas=[DeltaEntry(path="src/foo.py", change_type="M")])
        text = Text()

        tracker = build_deltas_section(
            text,
            cs,
            FoldLevel.FULLY_EXPANDED,
            show_file_hints=True,
            workspace_dir=str(workspace_dir),
        )

        assert tracker.mappings[1] == str(workspace_dir / "src/foo.py")

    def test_absolute_and_home_paths_resolve_directly(self) -> None:
        abs_path = "/tmp/sase-abs.py"
        home_path = "~/sase-home.py"
        cs = _make_changespec(
            deltas=[
                DeltaEntry(path=home_path, change_type="A"),
                DeltaEntry(path=abs_path, change_type="M"),
            ]
        )
        text = Text()

        tracker = build_deltas_section(
            text,
            cs,
            FoldLevel.FULLY_EXPANDED,
            show_file_hints=True,
            workspace_dir="/ignored/workspace",
        )

        assert tracker.mappings[1] == abs_path
        assert tracker.mappings[2] == os.path.expanduser(home_path)

    def test_collapsed_deltas_do_not_add_hidden_hints(self) -> None:
        incoming = HintTracker(
            counter=7,
            mappings={3: "/already.py"},
            hook_hint_to_idx={},
            hint_to_entry_id={},
            mentor_hint_to_info={},
        )
        cs = _make_changespec(deltas=[DeltaEntry(path="hidden.py", change_type="M")])
        text = Text()

        tracker = build_deltas_section(
            text,
            cs,
            FoldLevel.COLLAPSED,
            incoming,
            show_file_hints=True,
            workspace_dir="/workspace",
        )

        assert "[7]" not in text.plain
        assert tracker == incoming

    def test_hint_counter_continues_from_incoming_tracker(self) -> None:
        incoming = HintTracker(
            counter=3,
            mappings={1: "/one.py", 2: "/two.py"},
            hook_hint_to_idx={9: 4},
            hint_to_entry_id={8: "1a"},
            mentor_hint_to_info={7: ("mentor", "profile")},
        )
        cs = _make_changespec(
            deltas=[
                DeltaEntry(path="b.py", change_type="M"),
                DeltaEntry(path="a.py", change_type="A"),
            ]
        )
        text = Text()

        tracker = build_deltas_section(
            text,
            cs,
            FoldLevel.FULLY_EXPANDED,
            incoming,
            show_file_hints=True,
            workspace_dir="/workspace",
        )

        assert "+ [3] a.py" in text.plain
        assert "~ [4] b.py" in text.plain
        assert tracker.counter == 5
        assert tracker.mappings == {
            1: "/one.py",
            2: "/two.py",
            3: "/workspace/a.py",
            4: "/workspace/b.py",
        }
        assert tracker.hook_hint_to_idx == incoming.hook_hint_to_idx
        assert tracker.hint_to_entry_id == incoming.hint_to_entry_id
        assert tracker.mentor_hint_to_info == incoming.mentor_hint_to_info


class TestChangeSpecDetailFileHints:
    def test_update_display_with_hints_includes_expanded_deltas(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        project_file = tmp_path / "proj.gp"
        cs = _make_changespec(deltas=[DeltaEntry(path="src/foo.py", change_type="M")])
        cs.file_path = str(project_file)

        monkeypatch.setattr(
            "sase.ace.tui.widgets.changespec_detail.get_claimed_workspaces",
            lambda _project_file: [],
        )
        monkeypatch.setattr(
            "sase.ace.tui.widgets.changespec_detail."
            "get_workspace_directory_for_changespec",
            lambda _changespec: str(workspace_dir),
        )

        detail = ChangeSpecDetail()
        hint_mappings, _, _, _ = detail.update_display_with_hints(
            cs,
            query_string="",
            deltas_collapsed=FoldLevel.FULLY_EXPANDED,
        )

        assert hint_mappings == {1: str(workspace_dir / "src/foo.py")}
