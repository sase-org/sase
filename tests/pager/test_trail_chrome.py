"""Tests for pager-owned trail snapshot and breadcrumb renderers."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Span

from sase.pager._labels import LabelWindowScope
from sase.pager._line_mark import LineMark
from sase.pager._trail_chrome import (
    build_pager_help_content,
    build_pager_trail_snapshot,
    render_trail_band,
)
from sase.pager._trail_chrome_band import _render_compact_trail_row
from sase.pager._trail_chrome_model import MUTED_STYLE
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
    line_mark: LineMark | None = None,
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
        line_mark=line_mark,
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


def test_breadcrumb_appends_line_and_range_suffix_from_the_mark() -> None:
    back = [_trail_entry("resolve.py", line_mark=LineMark(0, 27, 27))]
    current_section = _section("pager.md", kind="ref:plan")
    current_document = _document("pager.md", current_section)
    forward = [_trail_entry("tests", line_mark=LineMark(0, 12, 20))]

    snapshot = build_pager_trail_snapshot(
        back=back,
        document=current_document,
        document_identity="file:/tmp/pager.md",
        current_section=current_section,
        current_line_mark=LineMark(0, 3, 3),
        forward=forward,
    )

    assert [entry.short_label for entry in snapshot.entries] == [
        "resolve.py:27",
        "pager.md:3",
        "tests:12–20",
    ]
    assert snapshot.entries[0].full_label == "resolve.py:27"
    assert snapshot.current.full_label == "pager.md:3"


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


def test_back_crumb_mutes_an_intact_ws_root_token() -> None:
    snapshot = _snapshot(["~ws/acme_3/a.md", "pager.md"], 1)

    row = _render_trail_path_row(snapshot, width=120)

    start = row.plain.index("~ws/acme_3/a.md")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in row.spans


def test_current_crumb_has_no_muted_span_for_a_ws_label() -> None:
    snapshot = _snapshot(["overview", "~ws/acme_3/a.md"], 1)

    row = _render_trail_path_row(snapshot, width=120)

    start = row.plain.index("~ws/acme_3/a.md")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) not in row.spans


def test_truncated_ws_prefix_renders_without_a_muted_span() -> None:
    snapshot = _snapshot(["~ws/acme_3/very-long-name-here.md", "pager.md"], 1)

    row = _render_trail_path_row(snapshot, width=22)

    assert "~ws/" not in row.plain
    muted_texts = {
        row.plain[span.start : span.end]
        for span in row.spans
        if span.style == MUTED_STYLE
    }
    assert muted_texts <= {" › "}


def test_rows_never_exceed_requested_cell_width() -> None:
    snapshot = _snapshot(
        [
            "intro",
            "problem",
            "设计-notes.md",
            "combining-e\u0301-title.md",
            "very-long-current-filename-with-suffix.py",
            "~ws/acme_3/deeply/nested/path/file.py",
            "follow-up",
            "review",
        ],
        5,
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


def test_full_trail_band_uses_ctrl_i_for_forward_hint() -> None:
    snapshot = _snapshot(["overview", "pager.md", "review"], 1)

    text = render_trail_band(snapshot, width=80, screen_height=24).plain

    assert "^I forward 1" in text
    assert "<tab> forward" not in text


def _committed_pin(ordinal: int, view: str = "read", base: int | None = None) -> object:
    from dataclasses import replace

    from sase.pager.history.models import committed_pin_for_ordinal

    pin = committed_pin_for_ordinal("note:project:demo/note", ordinal)
    if view == "diff":
        pin = replace(
            pin, view="diff", compare_base=base, explicit_base=base is not None
        )
    return pin


def _now_diff_pin(base: int) -> object:
    from dataclasses import replace

    from sase.pager.history.models import live_pin_for_subject

    pin = live_pin_for_subject("note:project:demo/note")
    return replace(pin, view="diff", compare_base=base, explicit_base=True)


def test__suffix_for_pin_names_read_diff_and_now() -> None:
    from sase.pager._trail_chrome import _suffix_for_pin
    from sase.pager.history.models import live_pin_for_subject

    assert _suffix_for_pin(None) == ""
    assert _suffix_for_pin(_committed_pin(24)) == "@v24"
    assert _suffix_for_pin(_committed_pin(24, "diff", base=23)) == "@v23→v24"
    assert _suffix_for_pin(_now_diff_pin(25)) == "@v25→now"
    assert _suffix_for_pin(live_pin_for_subject("s")) == ""


def test_suffix_for_moment_names_past_diff_and_tombstone() -> None:
    from sase.pager._trail_chrome import suffix_for_moment
    from sase.pager.history.moment import build_moment

    assert suffix_for_moment(None) == ""
    rows = [
        {
            "ordinal": ordinal,
            "commit": f"{ordinal:040d}",
            "blob_oid": f"blob-{ordinal:036d}",
            "committer_time": 1790000000,
            "class": "authored",
        }
        for ordinal in (23, 24, 25)
    ]
    meta = {"worktree_oid": "wt", "head_oid": "hd"}
    past = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(23, 24, 25),
        pin=_committed_pin(24),  # type: ignore[arg-type]
        status="live",
    )
    assert suffix_for_moment(past) == "@v24"

    diff_pin = _committed_pin(24, "diff", base=23)
    diff = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(23, 24, 25),
        pin=diff_pin,  # type: ignore[arg-type]
        status="live",
    )
    assert suffix_for_moment(diff) == "@v23→v24"

    tomb_rows = [{**rows[0]}, {**rows[1]}, {**rows[2], "class": "deleted"}]
    from sase.pager.history.models import live_pin_for_subject

    deleted = build_moment(
        rows=tomb_rows,
        meta=meta,
        visible_ordinals=(23, 24, 25),
        pin=live_pin_for_subject("s"),
        status="tombstone",
    )
    assert suffix_for_moment(deleted) == "@✖"


def test_snapshot_carries_version_suffixes_in_entries_and_signature() -> None:
    back = [_trail_entry("overview"), _trail_entry("design", kind="bead")]
    current_section = _section("pager.md", kind="ref:plan")
    current_document = _document("pager.md", current_section)
    forward = [_trail_entry("review")]

    snapshot = build_pager_trail_snapshot(
        back=back,
        document=current_document,
        document_identity="file:/tmp/pager.md",
        current_section=current_section,
        forward=forward,
        version_pins={
            "file:/tmp/overview": _committed_pin(21),
            "file:/tmp/review": _committed_pin(23, "diff", base=22),
        },
        current_suffix="@v24",
    )

    assert [entry.version_suffix for entry in snapshot.entries] == [
        "@v21",
        "",
        "@v24",
        "@v22→v23",
    ]
    assert snapshot.entries[0].signature[-1] == "@v21"
    assert snapshot.current.signature[-1] == "@v24"

    row = _render_trail_path_row(snapshot, width=120)
    assert "@v21" in row.plain
    assert "@v24" in row.plain
    assert "@v22→v23" in row.plain
    suffix_style = next(
        span.style for span in row.spans if row.plain[span.start : span.end] == "@v21"
    )
    from sase.pager.history.styles import default_history_styles

    assert suffix_style == default_history_styles().past


def test_suffix_sheds_before_labels_truncate() -> None:
    from dataclasses import replace

    from sase.pager._trail_chrome_model import PagerTrailSnapshot

    snapshot = _snapshot(["overview", "pager.md", "review"], 1)

    suffixed = PagerTrailSnapshot(
        entries=tuple(
            replace(
                entry, version_suffix="@v24" if entry.state == "current" else "@v21"
            )
            for entry in snapshot.entries
        ),
        current_index=snapshot.current_index,
    )
    full = _render_trail_path_row(suffixed, width=120).plain
    assert "@v24" in full and "pager.md" in full

    shed = _render_trail_path_row(suffixed, width=40).plain
    assert "@v24" not in shed and "@v21" not in shed
    assert "pager.md" in shed and "overview" in shed and "review" in shed

    truncated = _render_trail_path_row(suffixed, width=34).plain
    assert "@v24" not in truncated and "@v21" not in truncated
    assert "…" in truncated
