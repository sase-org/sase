"""Summary, attribution, and version tests for the MEMORY sub-section.

Split from ``test_agent_memory_reads``; shared builders live in
``_agent_memory_reads_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_memory_reads import (
    append_agent_memory_reads_section,
)
from tests.ace.tui.widgets._agent_memory_reads_helpers import (
    make_hint_state,
    make_memory_read_display,
    make_memory_read_event,
    pin_memory_reads_timezone,
)

__all__ = [
    "test_attributed_reason_aligns_under_primary_text",
    "test_attributed_rows_render_role_labels",
    "test_batch_header_ignores_included_targets",
    "test_batch_plus_overlapping_single_read_counts_distinct_files",
    "test_chips_append_at_row_end_without_reflow",
    "test_distinct_path_count_in_summary",
    "test_explicit_launch_row_header_says_instructions_as_launched",
    "test_frontmatter_marker_absent_when_not_stripped",
    "test_frontmatter_marker_present_when_stripped",
    "test_launch_row_alone_renders_without_reads",
    "test_launch_row_renders_first_with_chip",
    "test_past_chip_appends_version_and_newer_count",
    "test_pathless_batch_header_counts_each_requested_file",
    "test_role_column_padded_for_unlabeled_rows_in_attributed_lane",
    "test_single_producer_summary_omits_agent_count",
    "test_version_pin_registers_hint_number",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_memory_reads_timezone(monkeypatch)


def test_frontmatter_marker_present_when_stripped() -> None:
    text = Text()
    event = make_memory_read_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        frontmatter_stripped=True,
    )
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    assert "↩ frontmatter" in text.plain


def test_frontmatter_marker_absent_when_not_stripped() -> None:
    text = Text()
    event = make_memory_read_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        frontmatter_stripped=False,
    )
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    assert "↩ frontmatter" not in text.plain


def test_distinct_path_count_in_summary() -> None:
    events = (
        make_memory_read_event(
            canonical_path="a.md",
            timestamp="2026-05-24T14:05:00+00:00",
            read_id="id-1",
        ),
        make_memory_read_event(
            canonical_path="a.md",
            timestamp="2026-05-24T14:04:00+00:00",
            read_id="id-2",
        ),
        make_memory_read_event(
            canonical_path="b.md",
            timestamp="2026-05-24T14:03:00+00:00",
            read_id="id-3",
        ),
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=tuple(make_memory_read_display(event) for event in events)
    )

    assert "▸ MEMORY · 3 reads · 2 files\n" in text.plain
    assert "last 14:05:00" not in text.plain


def test_attributed_rows_render_role_labels() -> None:
    text = Text()
    events = (
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="cli_rules.md",
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    plain = text.plain
    assert "▸ MEMORY · 2 reads · 2 files · 2 agents\n" in plain
    assert "14:22:08  coder  ◇ tui_perf.md" in plain
    assert "14:21:00  plan   ◇ cli_rules.md" in plain


def test_role_column_padded_for_unlabeled_rows_in_attributed_lane() -> None:
    text = Text()
    events = (
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="cli_rules.md",
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            None,
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    lines = text.plain.splitlines()
    labeled = next(line for line in lines if "tui_perf.md" in line)
    unlabeled = next(line for line in lines if "cli_rules.md" in line)
    # Glyph stays column-aligned even though the second row has no label.
    assert labeled.index("◇") == unlabeled.index("◇")


def test_single_producer_summary_omits_agent_count() -> None:
    text = Text()
    events = (
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="a.md",
                timestamp="2026-05-24T14:05:00+00:00",
                read_id="id-1",
            ),
            "plan",
        ),
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="b.md",
                timestamp="2026-05-24T14:04:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    assert "▸ MEMORY · 2 reads · 2 files\n" in text.plain
    assert "agents" not in text.plain


def test_pathless_batch_header_counts_each_requested_file() -> None:
    event = make_memory_read_event(
        canonical_path="sase_flags.md",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="batch-three",
        resolved_path="",
        kind="note",
        selectors=("sase_flags.md", "tui_perf.md", "lint_and_test.md"),
        resolved_targets=("sase_flags.md", "tui_perf.md", "lint_and_test.md"),
    )
    text = Text()
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    assert "▸ MEMORY · 1 read · 3 files\n" in text.plain


def test_batch_plus_overlapping_single_read_counts_distinct_files() -> None:
    batch = make_memory_read_event(
        canonical_path="sase_flags.md",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="batch-three",
        resolved_path="",
        kind="note",
        selectors=("sase_flags.md", "tui_perf.md", "lint_and_test.md"),
        resolved_targets=("sase_flags.md", "tui_perf.md", "lint_and_test.md"),
    )
    single = make_memory_read_event(
        canonical_path="tui_perf.md",
        timestamp="2026-05-24T14:21:00+00:00",
        read_id="single-tui",
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(batch), make_memory_read_display(single))
    )

    assert "▸ MEMORY · 2 reads · 3 files\n" in text.plain


def test_batch_header_ignores_included_targets() -> None:
    event = make_memory_read_event(
        canonical_path="sase_flags.md",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="batch-included",
        resolved_path="",
        kind="note",
        selectors=("sase_flags.md", "tui_perf.md"),
        resolved_targets=("sase_flags.md", "tui_perf.md"),
        included_targets=("glossary:stitch", "decisions:memory-webs"),
    )
    text = Text()
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    assert "▸ MEMORY · 1 read · 2 files\n" in text.plain


def test_attributed_reason_aligns_under_primary_text() -> None:
    text = Text()
    events = (
        make_memory_read_display(
            make_memory_read_event(
                canonical_path="tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                reason="perf budget context",
                read_id="id-1",
            ),
            "coder",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    lines = text.plain.splitlines()
    row = next(line for line in lines if "tui_perf.md" in line)
    reason = next(line for line in lines if "↳" in line)
    assert reason.index("↳") == row.index("tui_perf.md")


def test_chips_append_at_row_end_without_reflow() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryVersionChip,
    )

    event = make_memory_read_event(
        canonical_path="gotchas.md",
        timestamp="2026-05-24T14:20:08+00:00",
        read_id="chip-read",
    )
    text = Text()
    append_agent_memory_reads_section(
        text,
        events=(make_memory_read_display(event),),
        chips={"chip-read": MemoryVersionChip("≡ now", "dim")},
    )

    assert "gotchas.md  ≡ now" in text.plain


def test_past_chip_appends_version_and_newer_count() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryVersionChip,
    )

    event = make_memory_read_event(
        canonical_path="dispatch.md",
        timestamp="2026-05-24T14:20:08+00:00",
        read_id="past-read",
    )
    text = Text()
    append_agent_memory_reads_section(
        text,
        events=(make_memory_read_display(event),),
        chips={"past-read": MemoryVersionChip("v12 ⟲ 2 newer", "#9d7cd8")},
    )

    assert "dispatch.md  v12 ⟲ 2 newer" in text.plain


def test_version_pin_registers_hint_number() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryVersionPin,
    )

    event = make_memory_read_event(
        canonical_path="gotchas.md",
        timestamp="2026-05-24T14:20:08+00:00",
        read_id="pin-read",
    )
    pin = MemoryVersionPin(
        scope_key="project:sase",
        repo_root="/tmp/repo",
        subject="gotchas.md",
        revision="v24",
        title="gotchas.md",
    )
    state = make_hint_state()
    text = Text()
    append_agent_memory_reads_section(
        text,
        events=(make_memory_read_display(event),),
        hint_state=state,
        version_pins={"pin-read": pin},
    )

    assert state.memory_version_pins == {1: pin}
    assert state.hint_mappings[1] == event.resolved_path


def test_launch_row_renders_first_with_chip() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryLaunchRow,
        MemoryVersionChip,
    )

    event = make_memory_read_event(
        canonical_path="gotchas.md",
        timestamp="2026-05-24T14:20:08+00:00",
        read_id="launch-read",
    )
    launch = MemoryLaunchRow(
        display="AGENTS.md",
        chip=MemoryVersionChip("v258 ⟲ 2 newer since launch", "#9d7cd8"),
        blob_oid="a" * 40,
        ordinal=258,
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(event),), launch_row=launch
    )

    lines = text.plain.splitlines()
    assert "AGENTS.md as launched" in lines[0]
    launch_index = next(
        index for index, line in enumerate(lines) if line.startswith("  launch")
    )
    read_index = next(index for index, line in enumerate(lines) if "gotchas.md" in line)
    assert launch_index < read_index
    launch_line = lines[launch_index]
    assert "AGENTS.md" in launch_line
    assert "v258 ⟲ 2 newer since launch" in launch_line


def test_launch_row_alone_renders_without_reads() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryLaunchRow,
        MemoryVersionChip,
    )

    launch = MemoryLaunchRow(
        display="AGENTS.md",
        chip=MemoryVersionChip("◌ as launched · not in git", "#FFAF00"),
        blob_oid="a" * 40,
        ordinal=None,
    )
    text = Text()
    append_agent_memory_reads_section(text, events=(), launch_row=launch)

    assert "AGENTS.md as launched" in text.plain
    assert "◌ as launched · not in git" in text.plain


def test_explicit_launch_row_header_says_instructions_as_launched() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_memory_versions import (
        MemoryLaunchRow,
        MemoryVersionChip,
    )

    launch = MemoryLaunchRow(
        display="Instructions as launched · 00-claude",
        chip=MemoryVersionChip(
            "claude.append_system_prompt_file · 128 · bytes match", "dim"
        ),
        blob_oid=None,
        ordinal=None,
        kind="bundle",
        snapshot_path="/tmp/00-claude.md",
        logical_filename="00-claude.md",
    )
    text = Text()
    append_agent_memory_reads_section(text, events=(), launch_row=launch)
    assert "Instructions as launched" in text.plain
    assert "AGENTS.md as launched" not in text.plain
    assert "00-claude" in text.plain
    assert "bytes match" in text.plain
