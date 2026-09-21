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
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_artifacts_lane import (
    append_agent_artifacts_lane,
)
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    MAX_VISIBLE_BEADS,
    _bead_touch_glyph,
    _ordered_bead_verb_chips,
    append_agent_bead_touch_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    ARTIFACT_READ_GLYPH,
    BEAD_CLOSED_GLYPH,
    BEAD_CREATED_GLYPH,
    BEAD_EDITED_GLYPH,
    BEAD_REMOVED_GLYPH,
    BEAD_REOPENED_GLYPH,
    COLOR_BEAD_PRIMARY,
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
from sase.bead_pages.paths import bead_page_path
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


def test_glyph_precedence_created_over_closed_over_edited_over_read() -> None:
    assert (
        _bead_touch_glyph(
            _entry(
                "sase-1",
                "2026-05-24T14:00:00+00:00",
                verbs={"created": 1, "closed": 1, "noted": 2},
            )
        )
        == BEAD_CREATED_GLYPH
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


def test_hints_map_bead_pages_and_skip_invalid_ids() -> None:
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
    assert state.hint_mappings == {3: bead_page_path("sase-14j.5")}
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


def test_clan_hint_target_returns_bead_page() -> None:
    entry = ClanContextEntry(
        key="sase-14j.5",
        label="sase-14j.5",
        member_labels=("a",),
        values=(_entry("sase-14j.5", "2026-05-24T14:00:00+00:00", verbs={"noted": 1}),),
    )
    assert clan_context_entry_hint_target(
        "ARTIFACTS",
        entry,
        member_workspaces={},
        fallback_workspace=None,
    ) == bead_page_path("sase-14j.5")


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
