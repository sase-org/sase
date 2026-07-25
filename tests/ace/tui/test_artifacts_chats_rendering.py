"""Grouped row and provenance rendering coverage for Artifacts Chats."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.console import Console

from sase.ace.tui.widgets.artifacts.chats_list import build_chat_options
from sase.ace.tui.widgets.artifacts.chats_rendering import (
    CHAT_PROVENANCE_COLORS,
    CHAT_PROVENANCE_GLYPHS,
    chat_row_text,
)
from sase.history.chat_catalog_provenance import ChatProvenance
from tests.ace.tui._artifacts_chats_helpers import chat_entry, pane_snapshot


@pytest.mark.parametrize(
    ("provenance", "machine", "label"),
    [
        ("local", None, "local"),
        ("shared", None, "shared"),
        ("remote", "zeus", "zeus"),
        ("unknown", None, "?"),
    ],
)
def test_each_provenance_has_distinct_glyph_label_and_color(
    provenance: ChatProvenance,
    machine: str | None,
    label: str,
) -> None:
    entry = chat_entry(
        provenance,
        provenance=provenance,
        machine=machine,
    )
    row = chat_row_text(entry)
    provenance_style = f"bold {CHAT_PROVENANCE_COLORS[provenance]}"

    assert row.plain.startswith(f"▌{CHAT_PROVENANCE_GLYPHS[provenance]} {label}")
    assert any(str(span.style) == provenance_style for span in row.spans)
    assert row.no_wrap is True
    assert row.overflow == "ellipsis"
    assert len(row.wrap(Console(width=34), 34)) == 1


def test_rows_remain_newest_first_with_date_headers() -> None:
    entries = (
        chat_entry("today-new", mtime="2026-07-24T14:32:00-04:00"),
        chat_entry("today-old", mtime="2026-07-24T09:15:00-04:00"),
        chat_entry("yesterday", mtime="2026-07-23T19:00:00-04:00"),
        chat_entry("historic", mtime="2026-07-20T08:00:00-04:00"),
    )
    options, rows = build_chat_options(
        pane_snapshot(entries),
        project_scope="alpha",
        loading=False,
        now=datetime.fromisoformat("2026-07-24T20:00:00-04:00"),
    )

    assert [option.prompt.plain for option in options if option.disabled] == [
        "── Today ────────────────────",
        "── Yesterday ────────────────────",
        "── 2026-07-20 ────────────────────",
    ]
    assert [row.entry for row in rows.values()] == list(entries)
    assert "14:32" in options[1].prompt.plain
    assert "09:15" in options[2].prompt.plain
