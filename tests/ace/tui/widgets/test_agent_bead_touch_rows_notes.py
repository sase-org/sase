"""Note-preview and overflow tests for agent bead-touch rows (bead sase-14j.5).

Split from ``test_agent_bead_touch_rows``; shared helpers live in
``_agent_bead_touch_rows_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    MAX_VISIBLE_BEADS,
    append_agent_bead_touch_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.core.bead_touch_index_facade import BeadNotePreview
from tests.ace.tui.widgets._agent_bead_touch_rows_shared import (
    collapsed_preview_text,
    contains_folded_text,
    make_bead_touch_entry,
    make_header_hint_state,
    pin_utc_timezone,
    render_header_lines,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

__all__ = [
    "test_attributed_rows_render_role_labels",
    "test_hints_map_bead_refs_and_skip_invalid_ids",
    "test_no_reason_line_without_reason_or_title",
    "test_note_preview_is_attributed_bounded_and_keeps_read_reason",
    "test_note_preview_physical_body_stays_three_lines_at_card_widths",
    "test_note_preview_wraps_to_passed_line_cell_limit",
    "test_overflow_footer_and_cap",
    "test_read_reason_yields_indent_before_words_in_narrow_cards",
    "test_title_falls_back_when_no_read_reason",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_utc_timezone(monkeypatch)


def test_title_falls_back_when_no_read_reason() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
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
            make_bead_touch_entry(
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
            make_bead_touch_entry(
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
    collapsed = collapsed_preview_text(plain)
    body_lines = [line for line in plain.splitlines() if "wide界word" in line]
    assert len(body_lines) == 3
    assert "… full note in bead detail" in collapsed
    assert "+1 earlier note in bead detail" in collapsed
    assert contains_folded_text(
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
                make_bead_touch_entry(
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
        hint_state=make_header_hint_state(start=4),
    )

    for width in (120, 56, 40):
        lines = render_header_lines(header, width=width)
        collapsed = collapsed_preview_text("\n".join(lines))
        body_lines = [line for line in lines if "word-" in line or "界終" in line]
        assert 1 <= len(body_lines) <= 3, width
        assert "full note in bead detail" in collapsed
        assert "earlier notes in bead detail" in collapsed
        assert contains_folded_text(collapsed, "owner.machine.coder")
        assert "sase-14j.5" in collapsed
        for line in lines:
            assert cell_len(line) <= width, line


def test_read_reason_yields_indent_before_words_in_narrow_cards() -> None:
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
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
            make_bead_touch_entry(
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
    assert "↳ Fallback title must not repeat" in plain
    assert "\x1b" not in plain
    assert "[not markup]" not in plain
    for line in plain.splitlines():
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_overflow_footer_and_cap() -> None:
    entries = tuple(
        make_bead_touch_entry(
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
    state = make_header_hint_state(start=3)
    text = Text()
    append_agent_bead_touch_rows(
        text,
        entries=(
            make_bead_touch_entry(
                "sase-14j.5", "2026-05-24T14:00:00+00:00", verbs={"noted": 1}, title="t"
            ),
            make_bead_touch_entry(
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
            make_bead_touch_entry(
                "sase-1",
                "2026-05-24T14:22:08+00:00",
                verbs={"noted": 1},
                title="t",
                label="coder",
            ),
            make_bead_touch_entry(
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
