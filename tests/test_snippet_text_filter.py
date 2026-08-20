"""Tests for the shared snippet substring filter."""

from __future__ import annotations

from sase.snippet.text_filter import filter_snippet_entries
from tests.ace.tui.modals.snippets_panel_test_helpers import snippet_entry


def test_empty_pattern_returns_entries_unchanged() -> None:
    entries = (snippet_entry("a"), snippet_entry("b"))

    assert (
        filter_snippet_entries(entries, pattern=None, include_bodies=False) is entries
    )
    assert filter_snippet_entries(entries, pattern="", include_bodies=True) is entries


def test_filter_matches_trigger_alias_and_source_without_bodies() -> None:
    entries = (
        snippet_entry("helper", aliases=("Helper",)),
        snippet_entry("wrap", kind="xprompt", path="xprompts/wrap.md"),
        snippet_entry("leaf", raw="mentions helper inside$0"),
    )

    assert [
        entry.trigger
        for entry in filter_snippet_entries(
            entries, pattern="Helper", include_bodies=False
        )
    ] == ["helper"]
    assert [
        entry.trigger
        for entry in filter_snippet_entries(
            entries, pattern="xprompt", include_bodies=False
        )
    ] == ["wrap"]
    assert filter_snippet_entries(entries, pattern="inside", include_bodies=False) == ()
    assert (
        filter_snippet_entries(entries, pattern="inside", include_definitions=False)
        == ()
    )


def test_body_matching_covers_raw_and_composed() -> None:
    entries = (
        snippet_entry("rawish", raw="needle in raw$0", composed="expanded"),
        snippet_entry("composedish", raw="$0", composed="needle in composed"),
        snippet_entry("other"),
    )

    matched = filter_snippet_entries(entries, pattern="needle", include_bodies=True)
    assert [entry.trigger for entry in matched] == ["rawish", "composedish"]
    via_cli = filter_snippet_entries(
        entries, pattern="needle", include_definitions=True
    )
    assert [entry.trigger for entry in via_cli] == ["rawish", "composedish"]
