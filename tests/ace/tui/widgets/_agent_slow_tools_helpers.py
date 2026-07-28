from __future__ import annotations

from datetime import datetime

from sase.ace.tui.tools import SlowToolSource, ToolCallEntry


def make_entry(**overrides: object) -> ToolCallEntry:
    kwargs = {
        "recorded_at": "2026-07-03T14:00:00+00:00",
        "runtime": "codex",
        "event": "ToolUse",
        "status": "success",
        "tool_name": "Bash",
        "tool_use_id": "call_1",
        "duration_ms": 20_000,
        "tool_input_summary": {"command": "just test"},
        "tool_response_summary": {"exit_code": 0},
    }
    kwargs.update(overrides)
    return ToolCallEntry(**kwargs)  # type: ignore[arg-type]


def make_source(
    *entries: ToolCallEntry,
    label: str | None = None,
    active: bool = False,
    end_reference: datetime | None = None,
    palette_index: int = 0,
) -> SlowToolSource:
    return SlowToolSource(
        label=label,
        entries=tuple(entries),
        agent_is_active=active,
        end_reference=end_reference,
        palette_index=palette_index,
    )
