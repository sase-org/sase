"""Tests for pager-owned trail snapshot and breadcrumb renderers."""

from __future__ import annotations

from rich.cells import cell_len

from sase.pager._labels import LabelWindowScope
from sase.pager._trail_chrome import (
    build_pager_help_content,
    build_pager_trail_snapshot,
    render_trail_band,
)
from sase.pager._trail_chrome_band import _render_compact_trail_row
from sase.pager._trail_chrome_model import (
    PagerTrailDisplayEntry as _PagerTrailDisplayEntry,
)
from sase.pager._trail_chrome_model import PagerTrailSnapshot
from sase.pager._trail_chrome_path import (
    render_trail_path_row as _render_trail_path_row,
)
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.trail import PagerSearchState, PagerTrailEntry


def _section(
    title: str, *, kind: str = "file", identity: str | None = None
) -> PagerSection:
    return PagerSection(
        identity=identity or f"file:/tmp/{title}",
        title=title,
        kind=kind,
        body=f"{title}\n",
    )


def _document(title: str, section: PagerSection | None = None) -> PagerDocument:
    section = _section(f"{title}.md") if section is None else section
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def _search_state() -> PagerSearchState:
    return PagerSearchState(
        mode="off",
        direction="forward",
        query="",
        corpus="",
        line_starts=(0,),
        match_spans=(),
        current_selection=None,
        origin_offset=0,
        restore_scroll_x=0,
        restore_scroll_y=0,
        last_search=None,
    )


def _trail_entry(
    title: str,
    *,
    kind: str = "file",
    identity: str | None = None,
) -> PagerTrailEntry:
    section = _section(title, kind=kind, identity=identity)
    document = _document(title, section)
    return PagerTrailEntry(
        document=document,
        document_identity=identity or section.identity,
        document_title=document.title,
        section_identity=section.identity,
        section_title=section.title,
        section_kind=section.kind,
        scroll_x=0,
        scroll_y=0,
        search=_search_state(),
        label_anchor=LabelWindowScope(0, 1),
    )


def _snapshot(labels: list[str], current_index: int) -> PagerTrailSnapshot:
    entries = []
    for index, label in enumerate(labels):
        state = "current" if index == current_index else "back"
        if index > current_index:
            state = "forward"
        entries.append(
            _PagerTrailDisplayEntry(
                document_identity=f"doc:{index}",
                document_title=label,
                section_identity=f"section:{index}",
                section_title=label,
                section_kind="file" if index % 2 else "bead",
                state=state,
            )
        )
    return PagerTrailSnapshot(entries=tuple(entries), current_index=current_index)


def test_snapshot_orders_back_current_and_reversed_forward_stack() -> None:
    back = [_trail_entry("overview"), _trail_entry("design", kind="bead")]
    current_section = _section("pager.md", kind="ref:plan")
    current_document = _document("pager.md", current_section)
    forward = [_trail_entry("review", kind="bead"), _trail_entry("tests")]

    snapshot = build_pager_trail_snapshot(
        back=back,
        document=current_document,
        document_identity="file:/tmp/pager.md",
        current_section=current_section,
        forward=forward,
    )

    assert [entry.short_label for entry in snapshot.entries] == [
        "overview",
        "design",
        "pager.md",
        "tests",
        "review",
    ]
    assert snapshot.position == 3
    assert snapshot.total == 5
    assert snapshot.back_count == 2
    assert snapshot.forward_count == 2


def test_path_row_expands_to_complete_path_when_it_fits() -> None:
    snapshot = _snapshot(["overview", "problem", "notes", "pager.md", "tests"], 3)

    row = _render_trail_path_row(snapshot, width=120).plain

    for label in ("overview", "problem", "notes", "pager.md", "tests"):
        assert label in row
    assert row.count("●") == 1
    assert "…1" not in row


def test_path_row_counts_omitted_runs_precisely() -> None:
    snapshot = _snapshot(
        ["overview", "problem", "notes", "design", "pager.md", "app.py", "tests"],
        4,
    )

    row = _render_trail_path_row(snapshot, width=34).plain

    assert "pager.md" in row
    assert row.count("●") == 1
    assert "…3" in row
    assert "…2" in row


def test_rows_never_exceed_requested_cell_width() -> None:
    snapshot = _snapshot(
        [
            "intro",
            "problem",
            "设计-notes.md",
            "combining-e\u0301-title.md",
            "very-long-current-filename-with-suffix.py",
            "follow-up",
            "review",
        ],
        4,
    )

    for width in range(0, 161):
        for rendered in (
            _render_trail_path_row(snapshot, width=width),
            _render_compact_trail_row(snapshot, width=width),
            render_trail_band(snapshot, width=width, screen_height=24),
            render_trail_band(snapshot, width=width, screen_height=10),
        ):
            for row in rendered.plain.splitlines() or [""]:
                assert cell_len(row) <= width


def test_very_narrow_path_keeps_the_current_marker() -> None:
    snapshot = _snapshot(["overview", "pager.md", "review"], 1)

    assert _render_trail_path_row(snapshot, width=1).plain == "●"
    assert _render_trail_path_row(snapshot, width=8).plain.count("●") == 1


def test_labels_are_literal_single_line_text() -> None:
    snapshot = _snapshot(["[bold]\nname\t\x1b[31m.md", "current"], 1)

    row = _render_trail_path_row(snapshot, width=80).plain

    assert "[bold]" in row
    assert "\n" not in row
    assert "\t" not in row
    assert "\x1b" not in row


def test_help_content_lists_complete_history_with_states_and_identity() -> None:
    snapshot = _snapshot(["same.md", "same.md", "same.md"], 1)

    content = build_pager_help_content(
        section_total=1,
        label_count=0,
        trail_snapshot=snapshot,
        width=40,
    )
    text = content.text.plain

    assert " 1  " in text
    assert "back" in text
    assert "current" in text
    assert "forward" in text
    assert "section:1" in text
    assert content.current_line > 0


def test_full_trail_band_uses_tab_for_forward_hint() -> None:
    snapshot = _snapshot(["overview", "pager.md", "review"], 1)

    text = render_trail_band(snapshot, width=80, screen_height=24).plain

    assert "<tab> forward 1" in text
    assert "^I forward" not in text
