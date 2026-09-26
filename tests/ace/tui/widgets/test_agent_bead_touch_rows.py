"""Tests for the agent ARTIFACTS Beads prompt-panel rows (bead sase-14j.5)."""

from __future__ import annotations

from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.bead_touches import BeadTouchEntry
from sase.core.bead_touch_index_facade import BeadNotePreview, BeadTouchClose
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_artifacts_lane import (
    append_agent_artifacts_lane,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    MAX_VISIBLE_BEADS,
    _bead_touch_glyph,
    _ordered_bead_verb_chips,
    append_agent_bead_touch_rows,
    _visible_bead_entries,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    ARTIFACT_READ_GLYPH,
    BEAD_CLOSED_GLYPH,
    BEAD_CREATED_GLYPH,
    BEAD_EDITED_GLYPH,
    BEAD_REMOVED_GLYPH,
    BEAD_REOPENED_GLYPH,
    COLOR_BEAD_CLOSED_CAP,
    COLOR_BEAD_CLOSED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_CAP,
    COLOR_BEAD_CLOSED_MUTED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_PILL,
    COLOR_BEAD_CLOSED_PILL,
    COLOR_BEAD_CLOSED_STALE,
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_REOPENED_SINCE,
    COLOR_BEAD_RESOLUTION,
    COLOR_BEAD_SUBHEADER,
    COLOR_REASON,
    COLOR_ROLE,
    COLOR_SUMMARY,
    MEMORY_GLYPH,
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_context import (
    clan_context_entry_hint_target,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
    HeaderHintState,
)
from sase.ace.tui.models._agent_clan_sections import ClanContextEntry
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _entry(
    bead_id: str,
    timestamp: str,
    *,
    verbs: dict[str, int] | None = None,
    title: str = "",
    own: bool = False,
    label: str | None = None,
    read_reasons: tuple[str, ...] = (),
    current_note_count: int = 0,
    note_preview: BeadNotePreview | None = None,
    note_label: str | None = None,
    agent_close: BeadTouchClose | None = None,
) -> BeadTouchEntry:
    return BeadTouchEntry(
        bead_id=bead_id,
        title=title,
        verbs=dict(verbs or {}),
        first_at=timestamp,
        last_at=timestamp,
        own=own,
        agent_label=label,
        read_reasons=read_reasons,
        current_note_count=current_note_count,
        note_preview=note_preview,
        note_agent_label=note_label,
        agent_close=agent_close,
    )


def _close(
    timestamp: str,
    *,
    resolution: str = "done",
    reason: str = "",
    standing: bool = True,
) -> BeadTouchClose:
    return BeadTouchClose(
        closed_at=timestamp,
        resolution=resolution,
        reason=reason,
        standing=standing,
    )


def _read_event(
    *,
    ref: str,
    timestamp: str,
    read_id: str,
    resolved_path: str | None = "/tmp/test/plan.md",
) -> ArtifactReadEvent:
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=read_id,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        ref=ref,
        reason="needed it",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        recorded_link=False,
        resolved_path=resolved_path,
    )


def _display(event: ArtifactReadEvent) -> ArtifactReadDisplayEvent:
    return ArtifactReadDisplayEvent(event=event)


def _hint_state(start: int = 1) -> HeaderHintState:
    return HeaderHintState(
        hint_counter=start,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )


def _render(header: Text, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def _collapsed_preview(text: str) -> str:
    return " ".join(text.replace("│", " ").split())


def _contains_folded(haystack: str, needle: str) -> bool:
    compact = haystack.replace(" ", "").replace("│", "")
    return needle.replace(" ", "") in compact


# --- glyphs ------------------------------------------------------------------


def test_bead_glyphs_are_single_cell() -> None:
    for glyph in (
        BEAD_CREATED_GLYPH,
        BEAD_CLOSED_GLYPH,
        BEAD_REOPENED_GLYPH,
        BEAD_EDITED_GLYPH,
        BEAD_REMOVED_GLYPH,
        ARTIFACT_READ_GLYPH,
        MEMORY_GLYPH,
    ):
        assert cell_len(glyph) == 1


def test_glyph_precedence_closed_over_created_over_edited_over_read() -> None:
    assert (
        _bead_touch_glyph(
            _entry(
                "sase-1",
                "2026-05-24T14:00:00+00:00",
                verbs={"created": 1, "closed": 1, "noted": 2},
            )
        )
        == BEAD_CLOSED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"closed": 1, "noted": 3}
            )
        )
        == BEAD_CLOSED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry(
                "sase-1", "2026-05-24T14:00:00+00:00", verbs={"reopened": 1, "noted": 1}
            )
        )
        == BEAD_REOPENED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry("sase-1", "2026-05-24T14:00:00+00:00", verbs={"noted": 2, "read": 1})
        )
        == BEAD_EDITED_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry("sase-1", "2026-05-24T14:00:00+00:00", verbs={"read": 2})
        )
        == ARTIFACT_READ_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry("sase-1", "2026-05-24T14:00:00+00:00", verbs={"viewed": 1})
        )
        == MEMORY_GLYPH
    )
    assert (
        _bead_touch_glyph(
            _entry("sase-1", "2026-05-24T14:00:00+00:00", verbs={"removed": 1})
        )
        == BEAD_REMOVED_GLYPH
    )
    assert _bead_touch_glyph(_entry("sase-1", "", own=True)) == MEMORY_GLYPH


def test_verb_chip_order_own_then_durable_then_read_then_viewed() -> None:
    entry = _entry(
        "sase-1",
        "2026-05-24T14:00:00+00:00",
        verbs={"noted": 3, "closed": 1, "read": 2, "viewed": 1},
        own=True,
    )
    assert _ordered_bead_verb_chips(entry) == [
        "own",
        "noted ×3",
        "closed",
        "read ×2",
        "viewed",
    ]


def test_single_counts_carry_no_suffix() -> None:
    entry = _entry(
        "sase-1", "2026-05-24T14:00:00+00:00", verbs={"created": 1, "dep": 1}
    )
    assert _ordered_bead_verb_chips(entry) == ["created", "dep"]


# --- rows --------------------------------------------------------------------


def test_empty_entries_appends_nothing() -> None:
    text = Text()
    append_agent_bead_touch_rows(text, entries=())
    assert text.plain == ""


def test_row_order_palette_and_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14g",
                "2026-05-24T16:41:02+00:00",
                verbs={"created": 1, "noted": 2},
                title="Custom gate with a failed command becomes unreachable",
            ),
            _entry(
                "sase-l6.4",
                "2026-05-24T16:12:55+00:00",
                verbs={"closed": 1, "noted": 3},
                title="Stream SASE CONTEXT lanes progressively",
                own=True,
            ),
        ),
    )
    plain = text.plain
    assert plain.index("sase-14g") < plain.index("sase-l6.4")
    assert "16:41:02  ✚ sase-14g · created · noted ×2" in plain
    assert "16:12:55  ✓ sase-l6.4 · own · closed · noted ×3" in plain
    assert "↳ Custom gate with a failed command becomes unreachable" in plain
    assert "↳ Stream SASE CONTEXT lanes progressively" in plain
    assert_span_covers(text, "✚", COLOR_BEAD_SUBHEADER)
    assert_span_covers(text, "sase-14g", COLOR_BEAD_PRIMARY)
    assert_span_covers(text, "noted ×2", COLOR_SUMMARY)
    assert_span_covers(text, "own", COLOR_ROLE)
    assert_span_covers(text, "Stream SASE CONTEXT lanes progressively", COLOR_REASON)


def test_own_only_bead_renders_without_verbs() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text, entries=(_entry("sase-14j.5", "", own=True, title=""),)
    )
    plain = text.plain
    assert "sase-14j.5 · own" in plain
    assert "×" not in plain
    assert "↳" not in plain
    assert_span_covers(text, "own", COLOR_ROLE)


def test_read_reason_renders_over_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"read": 1},
                title="Bead title",
                read_reasons=("Need the scope",),
            ),
        ),
    )
    plain = text.plain
    assert "↳ Need the scope" in plain
    assert "Bead title" not in plain


def test_title_falls_back_when_no_read_reason() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"noted": 1},
                title="Bead title",
            ),
        ),
    )
    assert "↳ Bead title" in text.plain


def test_no_reason_line_without_reason_or_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"viewed": 1},
            ),
        ),
    )
    assert "↳" not in text.plain


def test_note_preview_wraps_to_passed_line_cell_limit() -> None:
    body = " ".join(f"wide界word-{index:02d}" for index in range(40))
    preview = BeadNotePreview(
        id="sase-14j.5:7",
        author="owner.machine.coder.with-a-very-long-role-label",
        timestamp="2026-05-24T14:02:00+00:00",
        text=body,
        truncated=True,
    )
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"noted": 2},
                current_note_count=2,
                note_preview=preview,
                note_label="coder",
            ),
        ),
        line_cell_limit=40,
    )

    plain = text.plain
    collapsed = _collapsed_preview(plain)
    body_lines = [line for line in plain.splitlines() if "wide界word" in line]
    assert len(body_lines) == 3
    assert "… full note in bead detail" in collapsed
    assert "+1 earlier note in bead detail" in collapsed
    assert _contains_folded(
        collapsed, "owner.machine.coder.with-a-very-long-role-label"
    )
    for line in plain.splitlines():
        assert cell_len(line) <= 40


def test_note_preview_physical_body_stays_three_lines_at_card_widths() -> None:
    body = " ".join(f"word-{index:02d}" for index in range(80))
    preview = BeadNotePreview(
        id="sase-14j.5:7",
        author="owner.machine.coder",
        timestamp="2026-05-24T14:02:00+00:00",
        text=f"{body} 界終",
        truncated=True,
    )
    header, _ = build_header_text(
        make_agent(agent_name="worker"),
        summary=DetailHeaderSummary(
            bead_touch_entries=(
                _entry(
                    "sase-14j.5",
                    "2026-05-24T14:00:00+00:00",
                    verbs={"noted": 2},
                    title="Fallback title must not repeat",
                    current_note_count=3,
                    note_preview=preview,
                    note_label="coder",
                    read_reasons=("Inspect the regression",),
                ),
            ),
        ),
        hint_state=_hint_state(start=4),
    )

    for width in (120, 56, 40):
        lines = _render(header, width=width)
        collapsed = _collapsed_preview("\n".join(lines))
        body_lines = [line for line in lines if "word-" in line or "界終" in line]
        assert 1 <= len(body_lines) <= 3, width
        assert "full note in bead detail" in collapsed
        assert "earlier notes in bead detail" in collapsed
        assert _contains_folded(collapsed, "owner.machine.coder")
        assert "sase-14j.5" in collapsed
        for line in lines:
            assert cell_len(line) <= width, line


def test_read_reason_yields_indent_before_words_in_narrow_cards() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"viewed": 1},
                read_reasons=("Render compact Context-card note previews",),
            ),
        ),
        line_cell_limit=26,
    )

    reason_lines = [
        line
        for line in text.plain.splitlines()
        if line.strip() and "sase-14j.5" not in line
    ]
    assert 1 <= len(reason_lines) <= 3
    assert any("Context-card" in line for line in reason_lines)
    for line in reason_lines:
        assert cell_len(line) <= 26, line


def test_note_preview_is_attributed_bounded_and_keeps_read_reason() -> None:
    body = " ".join(f"wide界word-{index:02d}" for index in range(40))
    preview = BeadNotePreview(
        id="sase-14j.5:7",
        author="owner.machine.coder",
        timestamp="2026-05-24T14:02:00+00:00",
        text=f"{body}\n\x1b[31m[not markup]",
        edited_at="2026-05-24T14:03:00+00:00",
        truncated=True,
    )
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"noted": 2},
                title="Fallback title must not repeat",
                current_note_count=2,
                note_preview=preview,
                note_label="coder",
                read_reasons=("Inspect the regression",),
            ),
        ),
    )

    plain = text.plain
    assert "14:02 · owner.machine.coder · coder · edited" in plain
    assert len([line for line in plain.splitlines() if "wide界word" in line]) == 3
    assert "… full note in bead detail" in plain
    assert "+1 earlier note in bead detail" in plain
    assert "↳ read: Inspect the regression" in plain
    assert "Fallback title" not in plain
    assert "\x1b" not in plain
    assert "[not markup]" not in plain
    for line in plain.splitlines():
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_overflow_footer_and_cap() -> None:
    entries = tuple(
        _entry(
            f"sase-{index}",
            f"2026-05-24T14:{30 - index:02d}:00+00:00",
            verbs={"noted": 1},
            title=f"title {index}",
        )
        for index in range(MAX_VISIBLE_BEADS + 2)
    )
    text = Text()
    append_agent_bead_touch_rows(text, entries=entries)

    assert text.plain.count("↳") == MAX_VISIBLE_BEADS
    overflow = len(entries) - MAX_VISIBLE_BEADS
    assert f"+ {overflow} more" in text.plain
    assert f"· {entries[-1].last_at[11:16]} earliest" in text.plain


def test_hints_map_bead_refs_and_skip_invalid_ids() -> None:
    state = _hint_state(start=3)
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5", "2026-05-24T14:00:00+00:00", verbs={"noted": 1}, title="t"
            ),
            _entry(
                "not a bead id!!",
                "2026-05-24T13:00:00+00:00",
                verbs={"noted": 1},
                title="t",
            ),
        ),
        hint_state=state,
    )
    assert "[3] sase-14j.5" in text.plain
    assert "[4]" not in text.plain
    assert state.hint_mappings == {3: "bead:sase-14j.5"}
    assert state.hint_counter == 4


def test_attributed_rows_render_role_labels() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-1",
                "2026-05-24T14:22:08+00:00",
                verbs={"noted": 1},
                title="t",
                label="coder",
            ),
            _entry(
                "sase-2",
                "2026-05-24T14:21:00+00:00",
                verbs={"noted": 1},
                title="t",
                label="plan",
            ),
        ),
    )
    assert "14:22:08  coder  ✎ sase-1" in text.plain
    assert "14:21:00  plan   ✎ sase-2" in text.plain


# --- lane --------------------------------------------------------------------


def test_beads_lead_reads_in_lane_and_header() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(
            _display(
                _read_event(
                    ref="plan:202608/design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                    read_id="read-1",
                )
            ),
        ),
        bead_touch_entries=(
            _entry(
                "sase-14g", "2026-05-24T16:41:02+00:00", verbs={"created": 1}, title="t"
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 1 bead · 1 read\n" in plain
    assert plain.index("  Beads:") < plain.index("  Reads:")
    assert_span_covers(text, "  Beads:", COLOR_SUMMARY)


def test_bead_read_migrates_out_of_reads() -> None:
    bead_read = _display(
        _read_event(
            ref="bead:sase-14j.4",
            timestamp="2026-05-24T14:22:08+00:00",
            read_id="read-bead",
            resolved_path=None,
        )
    )
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(bead_read,),
        bead_touch_entries=(
            _entry(
                "sase-14j.4", "2026-05-24T14:22:08+00:00", verbs={"read": 1}, title="t"
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 1 bead\n" in plain
    assert "  Reads:" not in plain
    assert plain.count("sase-14j.4") == 1
    assert "← bead:sase-14j.4" not in plain
    assert "← sase-14j.4" in plain


def test_empty_beads_renders_no_subsection_or_count() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        artifact_reads=(
            _display(
                _read_event(
                    ref="plan:202608/design.md",
                    timestamp="2026-05-24T14:22:08+00:00",
                    read_id="read-1",
                )
            ),
        ),
        bead_touch_entries=(),
    )
    assert "  Beads:" not in text.plain
    assert "bead" not in text.plain.splitlines()[0]


def test_bead_id_never_truncates_at_narrow_widths() -> None:
    header, _ = build_header_text(
        make_agent(agent_name="worker"),
        summary=DetailHeaderSummary(
            bead_touch_entries=(
                _entry(
                    "sase-14j.5",
                    "2026-05-24T16:41:02+00:00",
                    verbs={"created": 1, "noted": 2},
                    title="Custom gate with a failed command becomes unreachable",
                ),
            ),
        ),
    )
    for width in (120, 28):
        rendered = "\n".join(_render(header, width=width))
        assert "sase-14j.5" in rendered
        row = next(line for line in rendered.splitlines() if "sase-14j.5" in line)
        assert "…" not in row


def test_long_title_wraps_within_cell_limit() -> None:
    long_title = " ".join(f"title-word-{index:02d}" for index in range(18))
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-14j.5",
                "2026-05-24T14:00:00+00:00",
                verbs={"noted": 1},
                title=long_title,
            ),
        ),
    )
    assert "…" not in text.plain
    assert long_title in " ".join(text.plain.split())
    for line in text.plain.splitlines():
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_cheap_header_renders_beads_without_index_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cheap header must not read the touch index")

    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context", fail
    )
    monkeypatch.setattr("sase.ace.tui.bead_touches.query_touch_index", fail)
    header, _ = build_header_text(
        make_agent(agent_name="worker"),
        cheap=True,
        summary=DetailHeaderSummary(
            bead_touch_entries=(
                _entry(
                    "sase-14j.5",
                    "2026-05-24T16:41:02+00:00",
                    verbs={"created": 1},
                    title="t",
                ),
            ),
        ),
    )
    assert "  Beads:\n" in header.plain
    assert "sase-14j.5" in header.plain


# --- clan --------------------------------------------------------------------


def test_clan_hint_target_returns_bead_ref() -> None:
    entry = ClanContextEntry(
        key="sase-14j.5",
        label="sase-14j.5",
        member_labels=("a",),
        values=(_entry("sase-14j.5", "2026-05-24T14:00:00+00:00", verbs={"noted": 1}),),
    )
    assert (
        clan_context_entry_hint_target(
            "ARTIFACTS",
            entry,
            member_workspaces={},
            fallback_workspace=None,
        )
        == "bead:sase-14j.5"
    )


def test_clan_hint_target_rejects_invalid_bead_id() -> None:
    entry = ClanContextEntry(
        key="bad",
        label="bad",
        member_labels=("a",),
        values=(_entry("not a bead id!!", "", verbs={"noted": 1}),),
    )
    assert (
        clan_context_entry_hint_target(
            "ARTIFACTS",
            entry,
            member_workspaces={},
            fallback_workspace=None,
        )
        is None
    )


# --- closed pill (sase-19p.3) --------------------------------------------------


def test_standing_done_row_shows_pill_and_drops_closed_chip() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1, "noted": 2},
                title="Render agent-closed beads distinctly",
                own=True,
                agent_close=_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
    )
    plain = text.plain
    assert "✓ sase-19f.2 ▐CLOSED▌ · own · noted ×2" in plain
    assert "· closed" not in plain
    assert_span_covers(text, "✓", COLOR_BEAD_CLOSED_GLYPH)
    assert_span_covers(text, "▐", COLOR_BEAD_CLOSED_CAP)
    assert_span_covers(text, "CLOSED", COLOR_BEAD_CLOSED_PILL)
    assert_span_covers(text, "▌", COLOR_BEAD_CLOSED_CAP)
    assert_span_covers(text, "own", COLOR_ROLE)


def test_standing_canceled_row_shows_grey_pill_and_resolution() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-1a2",
                "2026-09-25T17:20:45+00:00",
                verbs={"closed": 1, "created": 1},
                title="duplicate",
                agent_close=_close(
                    "2026-09-25T17:20:45+00:00",
                    resolution="canceled",
                    reason="duplicate of sase-19z",
                ),
            ),
        ),
    )
    plain = text.plain
    assert "✓ sase-1a2 ▐CLOSED▌ · canceled · created" in plain
    assert_span_covers(text, "✓", COLOR_BEAD_CLOSED_MUTED_GLYPH)
    assert_span_covers(text, "▐", COLOR_BEAD_CLOSED_MUTED_CAP)
    assert_span_covers(text, "CLOSED", COLOR_BEAD_CLOSED_MUTED_PILL)
    assert_span_covers(text, "canceled", COLOR_BEAD_RESOLUTION)
    assert "↳ canceled: duplicate of sase-19z" in plain


def test_non_standing_row_keeps_struck_closed_and_reopened_since() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-17m.4",
                "2026-09-25T16:02:55+00:00",
                verbs={"noted": 1, "closed": 1},
                title="Legacy close attribution",
                agent_close=_close("2026-09-25T16:02:55+00:00", standing=False),
            ),
        ),
    )
    plain = text.plain
    assert "▐CLOSED▌" not in plain
    assert "· noted · closed · reopened since" in plain
    assert "↳ Legacy close attribution" in plain
    assert_span_covers(text, "✓", COLOR_BEAD_SUBHEADER)
    assert_span_covers(text, "closed", COLOR_BEAD_CLOSED_STALE)
    assert_span_covers(text, "reopened since", COLOR_BEAD_REOPENED_SINCE)


def test_no_close_row_renders_exactly_as_before() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="Agent-closed beads in the Context card",
            ),
        ),
    )
    plain = text.plain
    assert "✎ sase-19f · noted" in plain
    assert "▐CLOSED▌" not in plain
    assert "↳ Agent-closed beads in the Context card" in plain
    assert_span_covers(text, "✎", COLOR_BEAD_SUBHEADER)


def test_standing_close_reason_beats_read_reason_and_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="Bead title",
                read_reasons=("Need the scope",),
                agent_close=_close(
                    "2026-09-25T17:34:01+00:00", reason="Phase checks green"
                ),
            ),
        ),
    )
    plain = text.plain
    assert "↳ closed: Phase checks green" in plain
    assert "Need the scope" not in plain
    assert "Bead title" not in plain


def test_standing_close_without_reason_falls_back_to_title() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="Bead title",
                agent_close=_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
    )
    assert "↳ Bead title" in text.plain


def test_lane_header_announces_standing_close_count() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        bead_touch_entries=(
            _entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1},
                title="t",
                agent_close=_close("2026-09-25T17:34:01+00:00"),
            ),
            _entry(
                "sase-1a2",
                "2026-09-25T17:20:45+00:00",
                verbs={"closed": 1},
                title="t",
                agent_close=_close("2026-09-25T17:20:45+00:00", resolution="canceled"),
            ),
            _entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="t",
            ),
        ),
    )
    plain = text.plain
    assert "▸ ARTIFACTS · 3 beads (✓ 2 closed)\n" in plain
    assert_span_covers(text, "✓ 2 closed", COLOR_BEAD_CLOSED_GLYPH)


def test_lane_header_without_closes_is_unchanged() -> None:
    text = Text()
    append_agent_artifacts_lane(
        text,
        bead_touch_entries=(
            _entry(
                "sase-19f",
                "2026-09-25T16:58:02+00:00",
                verbs={"noted": 1},
                title="t",
            ),
        ),
    )
    assert "▸ ARTIFACTS · 1 bead\n" in text.plain
    assert "closed" not in text.plain.splitlines()[0]


def test_visible_selection_keeps_older_standing_close_and_hints() -> None:
    entries = tuple(
        _entry(
            f"sase-{index}",
            f"2026-05-24T14:{30 - index:02d}:00+00:00",
            verbs={"noted": 1},
            title=f"title {index}",
        )
        for index in range(MAX_VISIBLE_BEADS + 1)
    ) + (
        _entry(
            "sase-old",
            "2026-05-24T13:00:00+00:00",
            verbs={"closed": 1},
            title="old close",
            agent_close=_close("2026-05-24T13:00:00+00:00"),
        ),
    )
    visible = _visible_bead_entries(entries)
    assert len(visible) == MAX_VISIBLE_BEADS
    assert visible[-1].bead_id == "sase-old"

    state = _hint_state(start=7)
    text = Text()
    append_agent_bead_touch_rows(text, entries=entries, hint_state=state)
    plain = text.plain
    assert "sase-old" in plain
    assert "▐CLOSED▌" in plain
    assert state.hint_mappings[7 + MAX_VISIBLE_BEADS - 1] == "bead:sase-old"
    assert state.hint_counter == 7 + MAX_VISIBLE_BEADS


def test_overflow_footer_uses_hidden_earliest_and_hidden_closed() -> None:
    many = tuple(
        _entry(
            f"sase-c{index}",
            f"2026-05-24T14:{30 - index:02d}:00+00:00",
            verbs={"closed": 1},
            title="t",
            agent_close=_close(f"2026-05-24T14:{30 - index:02d}:00+00:00"),
        )
        for index in range(MAX_VISIBLE_BEADS + 2)
    )
    text = Text()
    append_agent_bead_touch_rows(text, entries=many)
    plain = text.plain
    assert f"+ 2 more · {many[-1].last_at[11:16]} earliest (✓ 2 closed)" in plain
    assert_span_covers(text, "✓ 2 closed", COLOR_BEAD_CLOSED_GLYPH)


def test_narrow_console_keeps_pill_contiguous() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            _entry(
                "sase-19f.2",
                "2026-09-25T17:34:01+00:00",
                verbs={"closed": 1, "noted": 2},
                title="Render agent-closed beads distinctly",
                own=True,
                agent_close=_close("2026-09-25T17:34:01+00:00"),
            ),
        ),
        line_cell_limit=40,
    )
    output = StringIO()
    console = Console(file=output, width=40, color_system=None)
    console.print(text, end="")
    rendered = output.getvalue()
    assert "▐CLOSED▌" in rendered
    assert "▐CLOSED" not in rendered.replace("▐CLOSED▌", "")
    for line in rendered.splitlines():
        assert cell_len(line) <= 40 or "sase-19f.2" in line
