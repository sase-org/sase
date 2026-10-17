"""Shared helpers for the split agent memory-reads tests.

The tests formerly lived in a single ``test_agent_memory_reads`` module.
Helpers needed by more than one split module live here under public names;
the ``test_agent_memory_reads_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent

__all__ = [
    "make_hint_state",
    "make_memory_read_display",
    "make_memory_read_event",
    "pin_memory_reads_timezone",
]


def pin_memory_reads_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the prompt-panel timezone to UTC for deterministic timestamps."""
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def make_memory_read_event(
    *,
    canonical_path: str,
    timestamp: str,
    reason: str = "needed it",
    frontmatter_stripped: bool = False,
    read_id: str | None = None,
    resolved_path: str | None = None,
    kind: str = "note",
    selectors: tuple[str, ...] = (),
    resolved_targets: tuple[str, ...] = (),
    included_targets: tuple[str, ...] = (),
    depth: int | None = None,
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or canonical_path + timestamp,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        canonical_path=canonical_path,
        resolved_path=(
            f"/tmp/test/memory/{canonical_path}"
            if resolved_path is None
            else resolved_path
        ),
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason=reason,
        byte_count=64,
        frontmatter_stripped=frontmatter_stripped,
        kind=kind,  # type: ignore[arg-type]
        selectors=selectors,
        resolved_targets=resolved_targets,
        included_targets=included_targets,
        depth=depth,
    )


def make_memory_read_display(
    event: MemoryReadEvent, label: str | None = None
) -> MemoryReadDisplayEvent:
    return MemoryReadDisplayEvent(event=event, agent_label=label)


def make_hint_state(start: int = 1) -> HeaderHintState:
    return HeaderHintState(
        hint_counter=start,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )
