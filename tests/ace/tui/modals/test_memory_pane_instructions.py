"""Instructions group and instruction cards (phase instructions-group)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.modals.memory_pane_instructions import (
    INSTRUCTIONS_GROUP_IDENTITY,
    InstructionSubject,
    build_instruction_card_meta,
    build_instruction_card_title,
    build_instruction_row_text,
    build_instructions_group_text,
    _instruction_display_for_subject_id,
    instruction_edit_refusal,
    instruction_group_node,
    instruction_node,
    _instruction_row_chips,
    instruction_subjects,
    is_instruction_group_row,
    is_instruction_subject_row,
    matches_instruction_filter,
)
from sase.ace.tui.modals.memory_pane_instructions_rail import (
    MemoryPaneInstructionsMixin,
)
from sase.ace.tui.modals.memory_panel_history import (
    _instruction_file_traits,
    selector_for_node,
)


def _subject_row(
    subject_id: str,
    paths: list[str],
    *,
    managed: bool = True,
    template: bool = False,
    diverged_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": subject_id,
        "kind": "instructions",
        "display_name": "AGENTS.md",
        "managed": managed,
        "template": template,
        "diverged_count": diverged_count,
        "paths": paths,
        "versions": [],
    }


def _subjects(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"subjects": list(rows)}


def _subject(
    subject_id: str = "instructions:project:sase/.",
    path: str = "AGENTS.md",
    *,
    managed: bool = True,
    template: bool = False,
    diverged: bool = False,
    shims: tuple[str, ...] = ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"),
) -> InstructionSubject:
    return InstructionSubject(
        subject_id=subject_id,
        path=path,
        display=path,
        managed=managed,
        template=template,
        diverged=diverged,
        diverged_count=3 if diverged else 0,
        shims=shims,
    )


def test_subjects_filters_kind_and_names_rows_by_directory() -> None:
    wire = _subjects(
        {"id": "note:project:sase/tui", "kind": "note"},
        _subject_row(
            "instructions:project:sase/src/sase/ace",
            ["src/sase/ace/AGENTS.md", "src/sase/ace/CLAUDE.md"],
        ),
        _subject_row(
            "instructions:project:sase/.",
            ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"],
        ),
    )
    found = instruction_subjects(wire)
    assert [subject.path for subject in found] == [
        "AGENTS.md",
        "src/sase/ace/AGENTS.md",
    ]
    assert [subject.display for subject in found] == [
        "AGENTS.md",
        "src/sase/ace/AGENTS.md",
    ]
    root = found[0]
    assert root.managed is True
    assert root.shims == ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md")


def test_subjects_root_sorts_first() -> None:
    wire = _subjects(
        _subject_row("instructions:project:sase/tools", ["tools/AGENTS.md"]),
        _subject_row("instructions:project:sase/.", ["AGENTS.md"]),
    )
    found = instruction_subjects(wire)
    assert found[0].path == "AGENTS.md"


def test_subjects_template_diverged_and_malformed() -> None:
    wire = _subjects(
        _subject_row(
            "instructions:project:sase/demos",
            ["demos/AGENTS.md"],
            managed=False,
            template=True,
            diverged_count=6,
        ),
    )
    (found,) = instruction_subjects(wire)
    assert found.managed is False
    assert found.template is True
    assert found.diverged is True
    assert found.diverged_count == 6
    assert instruction_subjects({}) == ()
    assert instruction_subjects(None) == ()
    assert instruction_subjects({"subjects": "nope"}) == ()


def test_display_for_subject_id() -> None:
    assert (
        _instruction_display_for_subject_id("instructions:project:sase/.")
        == "AGENTS.md"
    )
    assert (
        _instruction_display_for_subject_id("instructions:project:sase/src/sase/ace")
        == "src/sase/ace/AGENTS.md"
    )


def test_row_chips_cover_shims_diverged_template() -> None:
    assert _instruction_row_chips(_subject()) == ("≡ 4 shims",)
    diverged = _subject(diverged=True)
    assert "⚠ diverged" in _instruction_row_chips(diverged)
    assert "TEMPLATE" in _instruction_row_chips(_subject(template=True))
    assert _instruction_row_chips(_subject(shims=())) == ()
    assert _instruction_row_chips(_subject(shims=("CLAUDE.md",))) == ("≡ 1 shim",)
    row = build_instruction_row_text(_subject())
    assert row.plain.startswith("● AGENTS.md")
    assert "≡ 4 shims" in row.plain


def test_group_text_marks_expansion() -> None:
    assert build_instructions_group_text(False, 4).plain == "▸ INSTRUCTIONS · 4"
    assert build_instructions_group_text(True, 1).plain == "▾ INSTRUCTIONS · 1"


def test_filter_matches_by_path() -> None:
    subject = _subject(
        "instructions:project:sase/src/sase/ace", "src/sase/ace/AGENTS.md"
    )
    assert matches_instruction_filter(subject, "") is True
    assert matches_instruction_filter(subject, "ace") is True
    assert matches_instruction_filter(subject, "SRC/SASE") is True
    assert matches_instruction_filter(subject, "instructions") is True
    assert matches_instruction_filter(subject, "tools") is False


def test_nodes_carry_history_kind_and_resolve_by_path() -> None:
    node = instruction_node(_subject())
    assert node.history_only is True
    assert node.deleted_ordinal == 0
    assert is_instruction_subject_row(node) is True
    assert is_instruction_group_row(node) is False
    assert node.identity == "AGENTS.md"
    assert selector_for_node(node) == "AGENTS.md"
    header = instruction_group_node()
    assert is_instruction_group_row(header) is True
    assert is_instruction_subject_row(header) is False
    assert header.identity == INSTRUCTIONS_GROUP_IDENTITY


def _stub(subjects: tuple[InstructionSubject, ...], *, expanded: bool = False) -> Any:
    stub = SimpleNamespace(
        _instruction_order=tuple(subject.subject_id for subject in subjects),
        _instruction_subjects={subject.subject_id: subject for subject in subjects},
        _expanded_instructions=expanded,
        _filter_text="",
        _filter_bodies=False,
    )
    stub._instruction_subject_for_node = (
        MemoryPaneInstructionsMixin._instruction_subject_for_node.__get__(stub)
    )
    return stub


def test_filter_matches_collapsed_expanded_and_pattern() -> None:
    subjects = (
        _subject(),
        _subject("instructions:project:sase/src/sase/ace", "src/sase/ace/AGENTS.md"),
    )
    collapsed = MemoryPaneInstructionsMixin._instruction_filter_matches(
        _stub(subjects), ""
    )
    assert [node.identity for node in collapsed] == [INSTRUCTIONS_GROUP_IDENTITY]
    expanded = MemoryPaneInstructionsMixin._instruction_filter_matches(
        _stub(subjects, expanded=True), ""
    )
    assert [node.identity for node in expanded] == [
        INSTRUCTIONS_GROUP_IDENTITY,
        "AGENTS.md",
        "src/sase/ace/AGENTS.md",
    ]
    filtered = MemoryPaneInstructionsMixin._instruction_filter_matches(
        _stub(subjects), "ace"
    )
    assert [node.identity for node in filtered] == [
        INSTRUCTIONS_GROUP_IDENTITY,
        "src/sase/ace/AGENTS.md",
    ]
    assert (
        MemoryPaneInstructionsMixin._instruction_filter_matches(_stub(subjects), "zzz")
        == ()
    )
    assert MemoryPaneInstructionsMixin._instruction_filter_matches(_stub(()), "") == ()


def test_history_only_option_renders_group_and_rows() -> None:
    subjects = (_subject(),)
    stub = _stub(subjects, expanded=True)
    group_option = MemoryPaneInstructionsMixin._history_only_option(
        stub, instruction_group_node()
    )
    assert group_option is not None
    assert "INSTRUCTIONS · 1" in group_option.prompt.plain
    row_option = MemoryPaneInstructionsMixin._history_only_option(
        stub, instruction_node(subjects[0])
    )
    assert row_option is not None
    assert "AGENTS.md" in row_option.prompt.plain
    assert "≡ 4 shims" in row_option.prompt.plain


def test_instruction_file_traits_mirror_pager_lookup() -> None:
    scope = SimpleNamespace(
        instruction_files=(
            SimpleNamespace(
                agents_path="AGENTS.md",
                shim_paths=("CLAUDE.md",),
                template=False,
                managed=True,
            ),
            SimpleNamespace(
                agents_path="src/sase/ace/AGENTS.md",
                shim_paths=(),
                template=False,
                managed=False,
            ),
        )
    )
    assert _instruction_file_traits(scope, "AGENTS.md") == (False, True)
    assert _instruction_file_traits(scope, "CLAUDE.md") == (False, True)
    assert _instruction_file_traits(scope, "src/sase/ace/AGENTS.md") == (False, False)
    assert _instruction_file_traits(scope, "sase/memory/tui.md") == (None, None)
    assert _instruction_file_traits(None, "AGENTS.md") == (None, None)


def test_edit_refusals_name_managed_and_handwritten() -> None:
    assert instruction_edit_refusal(_subject()) == (
        "rendered from memory · edit its source notes"
    )
    assert instruction_edit_refusal(_subject(managed=False)) == (
        "hand-written instruction file · o opens it"
    )
    assert instruction_edit_refusal(None) == (
        "rendered from memory · edit its source notes"
    )


def _rendered_plain(renderable: Any) -> str:
    from io import StringIO

    from rich.console import Console

    buffer = StringIO()
    Console(file=buffer, width=100).print(renderable)
    return buffer.getvalue()


def test_card_title_and_meta_use_instruction_grammar() -> None:
    from rich.console import Group

    title = build_instruction_card_title(
        "AGENTS.md", "AGENTS.md", scope_display_name="sase", accent="#87D7FF"
    )
    assert isinstance(title, Group)
    assert "INSTRUCTIONS" in _rendered_plain(title)
    assert "AGENTS.md" in _rendered_plain(title)
    meta = build_instruction_card_meta(_subject(), accent="#87D7FF")
    assert isinstance(meta, Group)
    badges = meta.renderables[0].plain
    assert "MANAGED" in badges
    grid_plain = _rendered_plain(meta.renderables[1])
    assert "Source" in grid_plain
    assert "Shims" in grid_plain
    assert "CLAUDE.md" in grid_plain
    hand_meta = build_instruction_card_meta(
        _subject(managed=False, shims=()), accent="#87D7FF"
    )
    assert "HAND-WRITTEN" in hand_meta.renderables[0].plain


def _band_version(
    ordinal: int, *, committer_time: int = 1_790_510_400
) -> dict[str, Any]:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}".replace("0", "ab")[0:40],
        "committer_time": committer_time,
        "class": "rendered",
        "hidden": False,
        "summary": {
            "section_paths": ["Section"],
            "words_added": 6,
            "words_removed": 1,
            "frontmatter_phrase": None,
            "created_words": None,
            "volume": 7,
        },
        "provenance": {"agent": "athena", "bead": None},
        "cause": {
            "sources": [{"subject_id": "note:project:sase/gotchas"}],
            "config_paths": [],
            "renderer_paths": [],
            "regen_only": False,
        },
        "diverged": False,
        "aliased_paths": [],
        "path": "AGENTS.md",
        "source_path": "AGENTS.md",
    }


def test_strip_second_row_is_cause_row_for_instructions() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import render_time_strip
    from sase.pager.history_kit import (
        build_time_band_data,
        default_history_styles,
    )

    timeline = {
        "subject_id": "instructions:project:sase/.",
        "state": "tracked",
        "versions": [_band_version(25)],
        "managed": True,
    }
    styles = default_history_styles()
    instruction_data = build_time_band_data(
        subject_id="instructions:project:sase/.",
        timeline=timeline,
        current_ordinal=0,
        now_epoch=1_791_000_000,
        total_visible=1,
    )
    assert instruction_data is not None
    assert instruction_data.subject_kind == "instructions"
    strip = render_time_strip(instruction_data, width=80, rows=2, styles=styles)
    assert "rendered" in strip.plain
    assert "gotchas" in strip.plain

    note_data = build_time_band_data(
        subject_id="note:project:sase/tui",
        timeline={
            "subject_id": "note:project:sase/tui",
            "state": "tracked",
            "versions": [_band_version(3)],
            "managed": True,
        },
        current_ordinal=0,
        now_epoch=1_791_000_000,
        total_visible=1,
    )
    assert note_data is not None
    note_strip = render_time_strip(note_data, width=80, rows=2, styles=styles)
    assert "rendered · sources" not in note_strip.plain


def test_open_source_opens_handwritten_and_refuses_managed() -> None:
    """``o`` opens a hand-written ``AGENTS.md``; a managed one refuses."""
    from sase.ace.tui.modals.memory_pane import MemoryPane
    from sase.ace.tui.modals.memory_pane_instructions import (
        INSTRUCTION_GROUP_TOAST,
        MANAGED_INSTRUCTION_REFUSAL,
    )

    def _run(subject: InstructionSubject, node: Any) -> tuple[list[str], list[str]]:
        stub = _stub((subject,), expanded=True)
        opened: list[str] = []
        toasts: list[str] = []
        stub._selected_row = lambda: node
        stub.action_open_in_editor = lambda: opened.append("editor")
        stub._start_restat = lambda _note: opened.append("restat")
        stub.notify = lambda message, **_kw: toasts.append(str(message))
        MemoryPane.action_open_source(stub)  # type: ignore[arg-type]
        return opened, toasts

    handwritten = _subject(managed=False)
    opened, toasts = _run(handwritten, instruction_node(handwritten))
    assert opened == ["editor", "restat"]
    assert toasts == []

    managed = _subject()
    opened, toasts = _run(managed, instruction_node(managed))
    assert opened == []
    assert toasts == [MANAGED_INSTRUCTION_REFUSAL]

    opened, toasts = _run(managed, instruction_group_node())
    assert opened == []
    assert toasts == [INSTRUCTION_GROUP_TOAST]


def test_instruction_rows_offer_no_relation_links() -> None:
    """The root ``AGENTS.md`` card shows no chips, so Tab/l follow nothing."""
    from sase.ace.tui.modals.memory_panel_travel import MemoryPanelTravelMixin

    stub = SimpleNamespace(
        _chip_cursor=3,
        _chip_notes=("stale",),
        _chip_parent_count=1,
        _snapshot=object(),
    )
    stub._selected_row = lambda: instruction_node(_subject())
    MemoryPanelTravelMixin._refresh_links_for_current_note(stub)  # type: ignore[arg-type]
    assert stub._chip_notes == ()
    assert stub._chip_parent_count == 0
    assert stub._chip_cursor is None
