"""History-badge and time-verb tests for the pager subject line."""

from __future__ import annotations

import re

from rich.text import Text

from sase.pager._chrome import footer_legend, subject_line, time_verbs_for_moment
from sase.pager._chrome_history import history_badge
from sase.pager.document import PagerDocument, PagerOrigin
from sase.pager.history.models import committed_pin_for_ordinal, live_pin_for_subject
from sase.pager.history.moment import VersionMoment, build_moment
from sase.pager.history.styles import default_history_styles

from ._chrome_helpers import CONSOLE, file_section

_NOW = 1790000000
_SUBJECT = "note:project:demo/gotchas"


def _badge_rows(newest: int = 25) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ordinal in range(1, newest + 1):
        rows.append(
            {
                "ordinal": ordinal,
                "commit": f"{ordinal:040d}",
                "blob_oid": f"blob-{ordinal:036d}",
                "committer_time": _NOW - (newest - ordinal) * 86400,
                "class": "authored",
                "path": "sase/memory/gotchas.md",
                "provenance": {"subject": f"change {ordinal}"},
            }
        )
    return rows


def _badge_meta(*, worktree: str, head: str) -> dict[str, object]:
    return {
        "worktree_oid": worktree,
        "head_oid": head,
        "path": "sase/memory/gotchas.md",
    }


def _past_moment(newest: int = 25, shown: int = 24) -> VersionMoment:
    rows = _badge_rows(newest)
    return build_moment(
        rows=rows,
        meta=_badge_meta(worktree="other", head="other-head"),
        visible_ordinals=tuple(range(1, newest + 1)),
        pin=committed_pin_for_ordinal(_SUBJECT, shown),
        status="live",
    )


def _badge_line(moment: VersionMoment, width: int, **state: object) -> Text:
    section = file_section("sase/memory/gotchas.md")
    document = PagerDocument(
        sections=(section,), title="gotchas.md", origin=PagerOrigin.FILE
    )
    history_state: dict[str, object] = {"moment": moment, "age": "1mo"}
    history_state.update(state)
    return subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=1700,
        width=width,
        syntax_hint="md",
        history_state=history_state,
    )


def test_pill_text_and_styles_for_every_kind() -> None:
    styles = default_history_styles()

    past = _past_moment()
    assert past.kind == "past"
    pill = history_badge(past, None, styles, 80)
    assert pill is not None and pill.plain.strip() == "⟲ PAST · v24 of 25"
    color = pill.get_style_at_offset(CONSOLE, 2).bgcolor
    assert color is not None
    assert color.get_truecolor().hex.lower() == styles.past_pill_bg.lower()

    rows = _badge_rows()
    newest_blob = "blob-000000000000000000000000000000000025"
    now = build_moment(
        rows=rows,
        meta=_badge_meta(worktree=newest_blob, head=newest_blob),
        visible_ordinals=tuple(range(1, 26)),
        pin=live_pin_for_subject(_SUBJECT),
        status="live",
    )
    assert now.kind == "now"
    now_pill = history_badge(now, None, styles, 80)
    assert now_pill is not None and now_pill.plain.strip() == "● NOW · v25"

    dirty = build_moment(
        rows=[{"ordinal": 0, "class": "uncommitted"}, *rows],
        meta=_badge_meta(worktree="wt", head="hd"),
        visible_ordinals=tuple(range(1, 26)),
        pin=live_pin_for_subject(_SUBJECT),
        status="dirty-now",
    )
    assert dirty.kind == "now_dirty"
    dirty_pill = history_badge(dirty, None, styles, 80)
    assert dirty_pill is not None and dirty_pill.plain.strip() == "◌ NOW · uncommitted"

    tomb_rows = _badge_rows(12)
    tomb_rows[-1] = {**tomb_rows[-1], "class": "deleted"}
    deleted = build_moment(
        rows=tomb_rows,
        meta=_badge_meta(worktree="wt", head="hd"),
        visible_ordinals=tuple(range(1, 12)),
        pin=live_pin_for_subject(_SUBJECT),
        status="tombstone",
    )
    assert deleted.kind == "deleted"
    deleted_pill = history_badge(deleted, None, styles, 80)
    assert deleted_pill is not None and deleted_pill.plain.strip() == "✖ DELETED · v12"

    loading = build_moment(rows=(), meta={}, visible_ordinals=())
    assert history_badge(loading, None, styles, 80) is None


def test_pill_sheds_through_fixed_forms_and_is_never_cropped() -> None:
    styles = default_history_styles()
    past = _past_moment()
    forms = [
        "⟲ PAST · v24 of 25",
        "⟲ PAST · v24/25",
        "⟲ v24/25",
        "⟲ v24",
    ]
    for index, form in enumerate(forms):
        pill = history_badge(past, None, styles, 60 - index * 3)
        assert pill is not None
    assert history_badge(past, None, styles, 200).plain.strip() == forms[0]  # type: ignore[union-attr]
    assert history_badge(past, None, styles, 0).plain.strip() == forms[-1]  # type: ignore[union-attr]

    pill_pattern = re.compile(r"⟲ (?:PAST · v24 of 25|PAST · v24/25|v24/25|v24)(?: |$)")
    for width in range(30, 201):
        line = _badge_line(past, width)
        assert len(line.plain) == width
        # Some complete pill form always survives intact, never cropped.
        assert pill_pattern.search(line.plain), width


def test_subject_line_sheds_hint_then_count_then_context_then_pill() -> None:
    past = _past_moment()

    wide = _badge_line(past, 200)
    assert "· md" in wide.plain
    assert "⌘ 1.7Kc" in wide.plain
    assert "⟲ PAST · v24 of 25" in wide.plain
    assert "1mo" in wide.plain

    # The syntax hint drops while the full pill and count survive.
    hintless = next(
        line
        for width in range(199, 29, -1)
        if "· md" not in (line := _badge_line(past, width)).plain
    )
    assert "⟲ PAST · v24 of 25" in hintless.plain
    assert "⌘ 1.7Kc" in hintless.plain

    # The character count drops while the full pill survives.
    countless = next(
        line
        for width in range(199, 29, -1)
        if "⌘" not in (line := _badge_line(past, width)).plain
    )
    assert "⟲ PAST · v24 of 25" in countless.plain

    # The context drops while the full pill survives.
    contextless = next(
        line
        for width in range(199, 29, -1)
        if "1mo" not in (line := _badge_line(past, width)).plain
    )
    assert "⟲ PAST · v24 of 25" in contextless.plain

    # The pill shortens through its fixed forms before the title truncates.
    shortened = next(
        line
        for width in range(199, 29, -1)
        if "⟲ PAST · v24 of 25" not in (line := _badge_line(past, width)).plain
    )
    assert "⟲ PAST · v24/25" in shortened.plain

    # Below the shortest pill the title middle-truncates, and the
    # basename's extension survives.
    narrow = _badge_line(past, 22)
    assert len(narrow.plain) == 22
    assert ".md" in narrow.plain
    assert "…" in narrow.plain
    assert "⟲ v24" in narrow.plain


def test_diff_context_keeps_the_delta_segment_longest() -> None:
    rows = _badge_rows()
    moment = build_moment(
        rows=rows,
        meta=_badge_meta(worktree="other", head="other-head"),
        visible_ordinals=tuple(range(1, 26)),
        pin=committed_pin_for_ordinal(_SUBJECT, 24),
        status="live",
    )
    assert moment.view == "read"
    from sase.pager.history.models import VersionPin

    pin = VersionPin(
        subject_id=_SUBJECT,
        ordinal=24,
        view="diff",
        compare_base=None,
        explicit_base=False,
        commit=None,
        blob_oid=None,
        selector=None,
    )
    diff_moment = build_moment(
        rows=rows,
        meta=_badge_meta(worktree="other", head="other-head"),
        visible_ordinals=tuple(range(1, 26)),
        pin=pin,
        status="live",
    )
    assert diff_moment.diff == (23, 24)
    line = _badge_line(diff_moment, 200)
    assert "Δ" in line.plain and "v23" in line.plain and "→" in line.plain
    # The age sheds while the Δ segment survives.
    aged_out = next(
        candidate
        for width in range(199, 29, -1)
        if "1mo" not in (candidate := _badge_line(diff_moment, width)).plain
    )
    assert "Δ" in aged_out.plain


def test_footer_names_step_destinations_in_every_state() -> None:
    past = _past_moment()
    assert [key for key, _label in time_verbs_for_moment(past)] == [
        "( v23",
        ") v25",
        "} now",
        "=",
        "@",
    ]

    rows = _badge_rows()
    newest_blob = "blob-000000000000000000000000000000000025"
    now = build_moment(
        rows=rows,
        meta=_badge_meta(worktree=newest_blob, head=newest_blob),
        visible_ordinals=tuple(range(1, 26)),
        pin=live_pin_for_subject(_SUBJECT),
        status="live",
    )
    assert [key for key, _label in time_verbs_for_moment(now)] == ["( v24", "=", "@"]
    footer = footer_legend(
        section_total=1, label_count=4, time_verbs=time_verbs_for_moment(now)
    )
    assert "@ timeline" in footer.plain and "= diff" in footer.plain

    tomb_rows = _badge_rows(12)
    tomb_rows[-1] = {**tomb_rows[-1], "class": "deleted"}
    deleted = build_moment(
        rows=tomb_rows,
        meta=_badge_meta(worktree="wt", head="hd"),
        visible_ordinals=tuple(range(1, 12)),
        pin=live_pin_for_subject(_SUBJECT),
        status="tombstone",
    )
    # On the deletion itself there is no `}` verb: its destination is here.
    assert [key for key, _label in time_verbs_for_moment(deleted)] == [
        "( v11",
        "=",
        "@",
    ]
