"""Rendering helper tests for the Snippets panel shell."""

from __future__ import annotations

from sase.ace.tui.keymaps.app_keymaps import SnippetPanelKeymaps
from sase.ace.tui.modals.snippets_panel_help_modal import SnippetsPanelHelpModal
from sase.ace.tui.modals.snippets_panel_rendering import (
    _bound_composed_preview,
    _highlight_raw_template,
    _snippet_call_diagnostics,
    build_empty_project_message,
    build_panel_footer,
    build_trail_strip,
    trigger_rail_width,
)
from sase.core.snippet_catalog_facade import SnippetCall, SnippetSourceSpan
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    snippet_call,
    snippet_entry,
)


def test_trail_strip_shows_full_path_when_short() -> None:
    text = build_trail_strip(("outer", "helper", "leaf"), accent="#87D7FF")

    assert text.plain == "TRAIL  outer › helper › leaf"


def test_trail_strip_elides_middle_when_long_and_first_is_kept() -> None:
    path = tuple(f"snip{index:02d}-with-a-long-name" for index in range(10))

    text = build_trail_strip(path, accent="#87D7FF", max_width=40)

    assert text.plain.startswith(f"TRAIL  {path[0]}")
    assert "…" in text.plain
    assert text.plain.endswith(f"{path[-2]} › {path[-1]}")


def test_empty_project_message_names_display_name() -> None:
    text = build_empty_project_message("Research", accent="#87D7FF")

    assert "Research" in text.plain
    assert "gh_" not in text.plain
    assert "add" not in text.plain.lower()


def test_panel_footer_lists_only_conditional_keys() -> None:
    keymaps = SnippetPanelKeymaps()

    assert (
        build_panel_footer(
            keymaps, has_entries=False, has_source_path=False, ring_size=1
        )
        == ""
    )

    footer = build_panel_footer(
        keymaps,
        has_entries=True,
        has_source_path=True,
        ring_size=2,
        has_relations=True,
        has_trail=True,
        focused_relation_trigger="leaf",
    )
    assert "p/P project" in footer
    assert "Tab relation" in footer
    assert "Enter / l follow" in footer
    assert "→ leaf" in footer
    assert "backspace / h back" in footer
    assert "y copy" in footer
    assert "o source" in footer
    assert "Z view" in footer
    assert "d delete" not in footer
    assert "e edit" not in footer
    assert "a add" not in footer
    assert "filter" not in footer
    assert "help" not in footer


def test_trigger_rail_width_is_driven_by_the_widest_row() -> None:
    entries = (
        snippet_entry("very_long_trigger_name", aliases=("VeryLongTriggerName",)),
        snippet_entry("z"),
    )

    width = trigger_rail_width(entries, available_width=1000)
    assert 32 <= width <= 52
    assert width > trigger_rail_width((snippet_entry("z"),), available_width=1000)


def test_trigger_rail_width_clamps_below_the_minimum() -> None:
    assert trigger_rail_width((), available_width=1000) == 32
    assert trigger_rail_width((snippet_entry("a"),), available_width=1000) == 32


def test_trigger_rail_width_clamps_above_the_maximum() -> None:
    entry = snippet_entry("a" * 80)

    assert trigger_rail_width((entry,), available_width=1000) == 52


def test_highlight_raw_template_marks_tabstops_and_calls() -> None:
    template = "before #[helper] $0 after"
    call_start = template.index("#[helper]")
    call_end = call_start + len("#[helper]")
    call = SnippetCall(
        authored_target="helper",
        canonical_target="helper",
        positional_args=(),
        span=SnippetSourceSpan(start=call_start, end=call_end),
        status="resolved",
    )

    text = _highlight_raw_template(template, (call,), accent="#87D7FF")

    assert text.plain == template
    assert "#[helper]" in text.plain
    assert "$0" in text.plain
    assert any("underline" in str(span.style) for span in text.spans)


def test_highlight_raw_template_marks_missing_calls_as_warnings() -> None:
    template = "#[gone]"
    call = snippet_call("gone", status="missing", start=0, end=len(template))

    text = _highlight_raw_template(template, (call,), accent="#87D7FF")

    assert any("red" in str(span.style) for span in text.spans)


def test_bound_composed_preview_elides_long_bodies() -> None:
    body = "\n".join(f"line {index}" for index in range(20))

    preview = _bound_composed_preview(body, max_lines=3, max_chars=400)

    assert preview.startswith("line 0")
    assert "line 3" not in preview
    assert preview.endswith("…")


def test_snippet_call_diagnostics_skip_resolved_calls() -> None:
    entry = snippet_entry(
        "outer",
        calls=(
            snippet_call("helper", status="resolved"),
            snippet_call("gone", status="missing"),
            snippet_call("self", status="cycle"),
            snippet_call("gone", status="missing"),
        ),
    )

    assert _snippet_call_diagnostics(entry) == (
        "missing: gone",
        "cycle: self",
    )


def test_panel_footer_lists_edit_and_delete_when_mutable() -> None:
    keymaps = SnippetPanelKeymaps()
    footer = build_panel_footer(
        keymaps,
        has_entries=True,
        has_source_path=True,
        ring_size=1,
        can_mutate=True,
    )
    assert "e edit" in footer
    assert "d delete" in footer
    assert "o source" in footer


def test_help_modal_lists_browsing_and_crud_keys() -> None:
    modal = SnippetsPanelHelpModal(keymaps=SnippetPanelKeymaps())
    content = modal._content()
    from rich.console import Console

    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(content)
    text = capture.get()
    assert "Next Snippet" in text
    assert "Filter" in text
    assert "Add Snippet" in text
    assert "Edit Snippet" in text
    assert "Delete Snippet" in text
