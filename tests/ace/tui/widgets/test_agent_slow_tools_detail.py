from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from rich.text import Text

from sase.ace.tui.models.fold_scale import AGENT_FOLD_SCALE, FAMILY_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_slow_tools import (
    append_slow_tool_calls_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_slow_tools_detail import (
    SlowToolDetail,
    digest_target,
    slow_tool_detail_level,
)
from tests.ace.tui.widgets._agent_slow_tools_helpers import (
    make_entry as _entry,
    make_source as _source,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


@pytest.mark.parametrize(
    ("summary", "tool_name", "expected"),
    [
        (
            {"file_path": "/home/bryan/project/src/file.py"},
            "Read",
            "…/src/file.py",
        ),
        (
            {"path": "project/src/file.py"},
            "Read",
            "…/src/file.py",
        ),
        (
            {"url": "https://example.com/releases/latest?download=1"},
            "WebFetch",
            "example.com/releases",
        ),
        (
            {"pattern": "needle", "query": "ignored"},
            "Grep",
            "needle",
        ),
        (
            {"description": "install dev dependencies", "command": "uv sync"},
            "Bash",
            "install dev dependencies",
        ),
        (
            {"command": "pytest tests/ace/tui -q\nprintf done"},
            "Bash",
            "pytest tests/ace/tui -q",
        ),
        ({"subagent_type": "reviewer"}, "Agent", "reviewer"),
        ({"input_keys": ["alpha", "beta"]}, None, "alpha, beta"),
    ],
)
def test_digest_target_resolves_input_kinds_without_inherited_markers(
    summary: dict[str, object],
    tool_name: str | None,
    expected: str,
) -> None:
    entry = _entry(tool_name=tool_name, tool_input_summary=summary)

    digest = digest_target(entry)

    assert digest == expected
    assert "...[" not in digest


def test_digest_target_elides_at_a_token_boundary_with_one_ellipsis() -> None:
    entry = _entry(tool_input_summary={"command": "alpha beta gamma"})

    assert digest_target(entry, 12) == "alpha beta…"


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (
            AGENT_FOLD_SCALE,
            (
                SlowToolDetail.COMPACT,
                SlowToolDetail.DETAIL,
                SlowToolDetail.FULL,
            ),
        ),
        (
            FAMILY_FOLD_SCALE,
            (SlowToolDetail.COMPACT, SlowToolDetail.FULL),
        ),
    ],
)
def test_slow_tool_detail_level_follows_scale_position(
    scale: tuple[FoldLevel, ...],
    expected: tuple[SlowToolDetail, ...],
) -> None:
    assert tuple(slow_tool_detail_level(level, scale) for level in scale) == expected


def test_command_block_appears_from_position_two_and_full_facts_at_last() -> None:
    command = "pytest tests/ace/tui -q\nprintf unique-second-line"
    entry = _entry(
        completed_at="2026-07-03T14:00:20+00:00",
        tool_input_summary={"command": command, "timeout": 600},
        tool_response_summary={"exit_code": 0, "stdout_preview": "all green"},
    )

    rendered: dict[FoldLevel, str] = {}
    for level in AGENT_FOLD_SCALE:
        text = Text()
        append_slow_tool_calls_section(
            text,
            sources=(_source(entry),),
            agent=SimpleNamespace(agent_name="root"),
            now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
            panel_level=level,
            scale=AGENT_FOLD_SCALE,
        )
        rendered[level] = text.plain

    assert "unique-second-line" not in rendered[FoldLevel.COLLAPSED]
    assert "full commands hidden" in rendered[FoldLevel.COLLAPSED]
    assert "unique-second-line" in rendered[FoldLevel.EXPANDED]
    assert (
        "│ ran 14:00:00 → 14:00:20 · exit 0 · timeout 600s"
        in rendered[FoldLevel.EXPANDED]
    )
    assert "│ output" not in rendered[FoldLevel.EXPANDED]
    assert "│ output all green" in rendered[FoldLevel.FULLY_EXPANDED]
    assert "#1 slowest · 100% of slow time" in rendered[FoldLevel.FULLY_EXPANDED]


def test_hidden_commands_tail_only_appears_when_a_primary_value_is_hidden() -> None:
    without_primary = Text()
    append_slow_tool_calls_section(
        without_primary,
        sources=(_source(_entry(tool_input_summary={})),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )
    with_primary = Text()
    append_slow_tool_calls_section(
        with_primary,
        sources=(_source(_entry()),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
    )

    assert "full commands hidden" not in without_primary.plain
    assert "full commands hidden" in with_primary.plain


def test_multiline_command_preserves_lines_and_caps_the_value_block() -> None:
    command = "\n".join(f"command line {index}" for index in range(1, 9))
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(_source(_entry(tool_input_summary={"command": command})),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        panel_level=FoldLevel.EXPANDED,
    )

    assert "      command line 1\n" in text.plain
    assert "      command line 6\n" in text.plain
    assert "command line 7" not in text.plain
    assert "... (+2 more lines)" in text.plain


def test_timing_lines_cover_completed_running_and_did_not_complete() -> None:
    completed = _entry(
        completed_at="2026-07-03T14:00:20+00:00",
        tool_input_summary={"command": "completed"},
        tool_response_summary={"exit_code": 1},
        status="failure",
    )
    running = _entry(
        recorded_at="2026-07-03T14:00:30+00:00",
        duration_ms=None,
        status="pending",
        tool_input_summary={"command": "running"},
    )
    abandoned = _entry(
        recorded_at="2026-07-03T14:00:40+00:00",
        duration_ms=None,
        status="pending",
        tool_input_summary={"command": "abandoned"},
    )
    text = Text()

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(completed),
            _source(running, active=True, palette_index=1),
            _source(
                abandoned,
                end_reference=datetime(2026, 7, 3, 14, 1, 10, tzinfo=UTC),
                palette_index=2,
            ),
        ),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 1, tzinfo=UTC),
        panel_level=FoldLevel.EXPANDED,
    )

    assert "│ ran 14:00:00 → 14:00:20 · exit 1 · failed" in text.plain
    assert "│ started 14:00:30 · running for 30s" in text.plain
    assert "│ started 14:00:40 · did not complete" in text.plain


def test_error_preview_subagent_and_share_lines_are_tier_gated() -> None:
    entry = _entry(
        tool_name="Agent",
        tool_input_summary={"prompt": "Review the implementation"},
        tool_response_summary={
            "agent_type": "reviewer",
            "content_preview": "Looks good",
            "total_tool_use_count": 4,
            "total_tokens": 1_234,
        },
        error="minor warning",
    )

    detail = Text()
    append_slow_tool_calls_section(
        detail,
        sources=(_source(entry),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        panel_level=FoldLevel.EXPANDED,
    )
    full = Text()
    append_slow_tool_calls_section(
        full,
        sources=(_source(entry),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        panel_level=FoldLevel.FULLY_EXPANDED,
    )

    assert "│ error minor warning" in detail.plain
    assert "│ output" not in detail.plain
    assert "│ subagent" not in detail.plain
    assert "slowest" not in detail.plain
    assert "│ output Looks good" in full.plain
    assert "│ subagent reviewer · 4 tool uses · 1,234 tokens" in full.plain
    assert "#1 slowest · 100% of slow time" in full.plain


def test_slow_tool_section_override_beats_the_panel_level() -> None:
    command = "printf compact\nprintf expanded"
    expanded = Text()
    ranges: dict[str, tuple[int, int]] = {}
    append_slow_tool_calls_section(
        expanded,
        sources=(_source(_entry(tool_input_summary={"command": command})),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={"slow-tool-calls": FoldLevel.EXPANDED},
        responsive_ranges=ranges,
    )

    assert "printf expanded" in expanded.plain
    assert expanded.plain.split("SLOW TOOL CALLS", 1)[0].endswith("▾ ")
    assert "slow-tool-calls" in ranges


@pytest.mark.parametrize("width", [60, 120])
def test_responsive_detail_wraps_with_a_hanging_indent(width: int) -> None:
    command = " ".join(f"segment-{index:02d}" for index in range(30))
    text = Text()
    ranges: dict[str, tuple[int, int]] = {}
    section = append_slow_tool_calls_section(
        text,
        sources=(_source(_entry(tool_input_summary={"command": command})),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        panel_level=FoldLevel.EXPANDED,
        responsive_ranges=ranges,
    )
    assert section is not None

    console = Console(width=width, record=True, color_system=None)
    console.print(section, end="")
    rendered = console.export_text()
    lines = rendered.splitlines()
    command_start = next(
        index for index, line in enumerate(lines) if "│ command" in line
    )
    command_end = next(index for index, line in enumerate(lines) if "│ ran" in line)
    command_lines = lines[command_start + 1 : command_end]

    assert len(command_lines) >= 2
    assert all(line.startswith("      ") for line in command_lines)
