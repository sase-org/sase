"""Tests for the pager's pure chrome/footer rendering helpers."""

from __future__ import annotations

import re

from rich.console import Console
from rich.text import Span, Text

from sase.pager._chrome import (
    footer_legend,
    goto_command_line,
    section_rule,
    subject_line,
    time_verbs_for_moment,
)
from sase.pager._chrome_history import history_badge
from sase.pager._chrome_sections import section_accent, section_icon
from sase.pager._chrome_subject import _format_char_count
from sase.pager._trail_chrome_model import MUTED_STYLE
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import committed_pin_for_ordinal, live_pin_for_subject
from sase.pager.history.moment import VersionMoment, build_moment
from sase.pager.history.styles import default_history_styles

_CONSOLE = Console(color_system="truecolor")


def _bead_section(title: str = "sase-uk.3: The reading surface") -> PagerSection:
    return PagerSection(
        identity="bead:sase-uk.3",
        title=title,
        kind="bead",
        body="some detail",
        subject_ref="bead:sase-uk.3",
    )


def _file_section(title: str = "artifact_links.py") -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}",
        title=title,
        kind="file",
        body="line one\nline two\n",
        subject_ref=f"file:/tmp/{title}",
    )


def _agent_section(title: str = "IDENTITY") -> PagerSection:
    return PagerSection(
        identity="agent-identity",
        title=title,
        kind="agent",
        body="Name: worker\n",
    )


def test_section_icon_and_accent_use_the_artifacts_tables() -> None:
    assert section_icon("bead") == "◈"
    assert section_icon("file") == "▤"
    assert section_icon("agent") == "⬡"
    assert section_accent("bead") == "#D787FF"
    assert section_accent("file") == "#FFAF5F"
    assert section_accent("agent") == "#0062FF"


def test_section_icon_and_accent_fall_back_for_unknown_kinds() -> None:
    assert section_icon("diff") == "◆"
    assert section_accent("diff") == "#AFAFAF"


def test_format_char_count_scales_with_magnitude() -> None:
    assert _format_char_count(88) == "88c"
    assert _format_char_count(1_234) == "1.2Kc"
    assert _format_char_count(2_500_000) == "2.5Mc"


def test_subject_line_omits_position_for_a_single_section_document() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=41,
        char_count=88,
        width=80,
    )

    assert "◈" in line.plain
    assert document.title in line.plain
    assert "1/1" not in line.plain
    assert "41%" in line.plain
    assert "⌘ 88c" in line.plain


def test_subject_line_shows_position_and_current_section_title_when_multi() -> None:
    sections = (_file_section("a.py"), _file_section("b.py"), _file_section("c.py"))
    document = PagerDocument(
        sections=sections, title="3 files", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        sections[1],
        section_index=2,
        section_total=3,
        scroll_percent=12,
        char_count=42,
        width=80,
    )

    assert "▤" in line.plain
    assert "3 files" in line.plain
    assert "b.py" in line.plain
    assert "2/3" in line.plain
    assert "12%" in line.plain


def test_subject_line_pads_to_the_requested_width_when_it_fits() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=0,
        width=80,
    )

    assert len(line.plain) == 80


def test_subject_line_shows_the_syntax_hint_when_it_fits() -> None:
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint="py",
    )

    assert "· py" in line.plain


def test_subject_line_omits_the_syntax_hint_when_absent() -> None:
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint=None,
    )

    assert "· py" not in line.plain


def test_subject_line_drops_the_syntax_hint_before_the_subject_at_narrow_width() -> (
    None
):
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    without_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint=None,
    )
    with_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint="py",
    )

    assert "· py" not in with_hint.plain
    assert with_hint.plain == without_hint.plain


def test_subject_line_uses_the_agent_glyph_and_accent() -> None:
    section = _agent_section()
    document = PagerDocument(
        sections=(section,), title="worker", origin=PagerOrigin.AGENT
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=13,
        width=80,
    )

    assert "⬡" in line.plain
    color = line.get_style_at_offset(_CONSOLE, 0).color
    assert color is not None
    assert color.get_truecolor().hex == "#0062ff"


def test_subject_line_mutes_an_intact_ws_root_token() -> None:
    section = _file_section("~ws/acme_3/a.py")
    document = PagerDocument(
        sections=(section,), title="~ws/acme_3/a.py", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
    )

    start = line.plain.index("~ws/acme_3/a.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_subject_line_mutes_the_current_sections_ws_token_when_multi() -> None:
    first = _file_section("a.py")
    second = _file_section("~ws/acme_3/b.py")
    document = PagerDocument(
        sections=(first, second), title="2 files", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        second,
        section_index=2,
        section_total=2,
        scroll_percent=0,
        char_count=10,
        width=80,
    )

    start = line.plain.index("~ws/acme_3/b.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_section_rule_mutes_an_intact_ws_root_token() -> None:
    section = _file_section("~ws/acme_3/b.py")

    line = section_rule(section, index=2, total=2, width=80)

    start = line.plain.index("~ws/acme_3/b.py")
    end = start + len("~ws/")
    assert Span(start, end, MUTED_STYLE) in line.spans


def test_section_rule_renders_the_agent_kind() -> None:
    section = _agent_section("MODEL")

    line = section_rule(section, index=2, total=7, width=80)

    assert line.plain.startswith("━━ 2/7 ━ ⬡ MODEL")
    assert len(line.plain) == 80


def test_section_rule_shape_matches_the_design_doc() -> None:
    section = _file_section("artifact_links.py")

    line = section_rule(section, index=2, total=3, width=80)

    assert line.plain.startswith("━━ 2/3 ━ ▤ artifact_links.py")
    assert line.plain.endswith("━")
    assert len(line.plain) == 80


def test_footer_legend_hides_entity_nav_for_a_single_section_document() -> None:
    line = footer_legend(section_total=1)

    assert "^N/^P" not in line.plain
    assert "/ search" in line.plain
    assert "? keys" in line.plain
    assert "q close" in line.plain


def test_footer_legend_shows_entity_nav_for_a_multi_section_document() -> None:
    line = footer_legend(section_total=3)

    assert "^N/^P entity" in line.plain


def test_footer_legend_names_trail_sheet_when_history_exists() -> None:
    line = footer_legend(section_total=1, trail_forward_count=2)

    assert "^I forward" in line.plain
    assert "<tab> forward" not in line.plain
    assert "? trail/keys" in line.plain
    assert "? keys" not in line.plain


def test_footer_legend_shows_follow_only_when_labels_exist() -> None:
    no_labels = footer_legend(section_total=1, label_count=0)
    labels = footer_legend(section_total=1, label_count=3)

    assert "follow" not in no_labels.plain
    assert "0-9a-z follow" in labels.plain


def test_footer_legend_promotes_pending_prefix_over_follow_hint() -> None:
    line = footer_legend(section_total=1, label_count=60, pending_prefix="Z")

    assert "Z… link" in line.plain
    assert "follow" not in line.plain


def test_footer_legend_names_other_pane_arm() -> None:
    line = footer_legend(section_total=1, label_count=3, pending_action="other")

    assert "^W… other pane" in line.plain
    assert "follow" not in line.plain


def test_goto_command_line_idle_shows_range_and_gold_sigil() -> None:
    line = goto_command_line(
        digits="",
        line_count=12,
        section_title=None,
        section_kind=None,
        width=80,
    )

    assert line.plain.startswith(":")
    assert "line 1-12" in line.plain
    assert line.get_style_at_offset(_CONSOLE, 0).bold is True


def test_goto_command_line_typing_keeps_digits_white() -> None:
    line = goto_command_line(
        digits="4",
        line_count=12,
        section_title=None,
        section_kind=None,
        width=80,
    )

    assert ":4" in line.plain
    assert "out of range" not in line.plain
    style = line.get_style_at_offset(_CONSOLE, 1)
    assert style.bold is not True


def test_goto_command_line_invalid_restyles_digits_and_range() -> None:
    line = goto_command_line(
        digits="0",
        line_count=12,
        section_title="alpha.py",
        section_kind="file",
        width=80,
    )

    assert "out of range · 1-12" in line.plain
    assert "alpha.py" not in line.plain
    style = line.get_style_at_offset(_CONSOLE, 1)
    assert style.bold is True


def test_goto_command_line_multi_section_shows_glyph_and_title() -> None:
    line = goto_command_line(
        digits="",
        line_count=30,
        section_title="alpha.py",
        section_kind="file",
        width=80,
    )

    assert section_icon("file") in line.plain
    assert "alpha.py" in line.plain
    assert "line 1-30" in line.plain


def test_goto_command_line_truncates_title_before_dropping_the_range() -> None:
    line = goto_command_line(
        digits="",
        line_count=12,
        section_title="very-long-section-title.py",
        section_kind="file",
        width=28,
    )

    assert "line 1-12" in line.plain
    assert "very-long-section-title.py" not in line.plain
    assert "…" in line.plain


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
    section = _file_section("sase/memory/gotchas.md")
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
    color = pill.get_style_at_offset(_CONSOLE, 2).bgcolor
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


def test_footer_shows_a_single_edit_verb() -> None:
    verbs = [("( v23", ""), (") v25", ""), ("@", "timeline"), ("=", "diff")]
    pinned = footer_legend(
        section_total=1, label_count=4, history_pinned=True, time_verbs=verbs
    )
    assert "E edit now" in pinned.plain
    assert pinned.plain.count("E edit") == 1

    unpinned = footer_legend(section_total=1, label_count=4, time_verbs=verbs)
    assert "E edit" in unpinned.plain
    assert "E edit now" not in unpinned.plain
    assert unpinned.plain.count("E edit") == 1
