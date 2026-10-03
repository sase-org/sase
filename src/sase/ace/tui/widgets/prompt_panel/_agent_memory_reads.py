"""Agent-specific MEMORY context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    memory_read_report_path,
)
from sase.memory.read_log import memory_read_event_targets

from ._agent_display_state import HeaderHintState
from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_FRONTMATTER,
    COLOR_MEMORY_GLYPH,
    COLOR_MEMORY_PRIMARY,
    COLOR_MEMORY_SUBHEADER,
    COLOR_TRUNCATION,
    FRONTMATTER_MARKER,
    MEMORY_GLYPH,
    append_context_lane_header,
    append_context_reason,
    append_lane_row,
    count_phrase,
    format_local_hhmm,
    format_local_hhmmss,
    normalize_context_display,
    truncate_display,
)
from ._agent_memory_versions import (
    LAUNCH_GLYPH,
    MemoryLaunchRow,
    MemoryVersionChip,
    MemoryVersionPin,
)

MAX_VISIBLE_READS = 5
PATH_LIMIT = 64

__all__ = [
    "MAX_VISIBLE_READS",
    "PATH_LIMIT",
    "append_agent_memory_reads_section",
    "append_context_reason",
    "format_local_hhmm",
    "format_local_hhmmss",
    "normalize_context_display",
    "register_memory_read_report_hint",
    "truncate_display",
]


def register_memory_read_report_hint(
    item: MemoryReadDisplayEvent,
    *,
    hint_state: HeaderHintState | None,
    version_pin: MemoryVersionPin | None = None,
) -> str | None:
    """Register a raw memory path or deferred read report and return the marker."""
    event = item.event
    if hint_state is None:
        return None
    if event.resolved_path:
        target_path = event.resolved_path
        report_spec = None
    elif event.schema_version >= 2 and event.selectors:
        target_path = memory_read_report_path(event)
        report_spec = MemoryReadReportSpec(
            event=event,
            agent_label=item.agent_label,
            report_path=target_path,
        )
    else:
        return None

    hint_number = hint_state.hint_counter
    hint_state.hint_counter += 1
    hint_state.hint_mappings[hint_number] = target_path
    if report_spec is not None:
        hint_state.memory_reports[target_path] = report_spec
    if version_pin is not None:
        hint_state.memory_version_pins[hint_number] = version_pin
    return f"[{hint_number}]"


def _register_memory_version_pin(
    pin: MemoryVersionPin,
    *,
    hint_state: HeaderHintState | None,
    fallback_path: str,
) -> str | None:
    """Register a version-pinned memory hint and return its marker."""
    if hint_state is None:
        return None
    hint_number = hint_state.hint_counter
    hint_state.hint_counter += 1
    hint_state.hint_mappings[hint_number] = fallback_path
    hint_state.memory_version_pins[hint_number] = pin
    return f"[{hint_number}]"


def append_agent_memory_reads_section(
    text: Text,
    *,
    events: tuple[MemoryReadDisplayEvent, ...] = (),
    show_empty: bool = False,
    hint_state: HeaderHintState | None = None,
    chips: dict[str, MemoryVersionChip] | None = None,
    version_pins: dict[str, MemoryVersionPin] | None = None,
    launch_row: MemoryLaunchRow | None = None,
    launch_pin: MemoryVersionPin | None = None,
) -> None:
    """Append a MEMORY sub-section listing the agent_session's audited reads.

    *chips* maps read-event ids to their resolved version chips and
    *version_pins* to single-target pager pins; both append at the row
    end without reflowing the lane. *launch_row* renders first as the
    ``AGENTS.md as launched`` row.
    """
    if not events and launch_row is None:
        if show_empty:
            append_context_lane_header(
                text,
                "MEMORY",
                label_style=COLOR_MEMORY_SUBHEADER,
                details="none recorded",
                details_style=COLOR_EMPTY,
            )
        return

    distinct_paths = len(
        {target for item in events for target in memory_read_event_targets(item.event)}
    )
    distinct_agents = len({item.agent_label for item in events if item.agent_label})
    details = (
        f"{count_phrase(len(events), 'read')} · {count_phrase(distinct_paths, 'file')}"
    )
    if distinct_agents > 1:
        details += f" · {count_phrase(distinct_agents, 'agent')}"
    if launch_row is not None:
        details += " · AGENTS.md as launched"
    append_context_lane_header(
        text,
        "MEMORY",
        label_style=COLOR_MEMORY_SUBHEADER,
        details=details,
    )

    if launch_row is not None:
        _append_launch_row(
            text,
            launch_row,
            hint_state=hint_state,
            launch_pin=launch_pin,
        )

    visible = events[:MAX_VISIBLE_READS]
    show_role_column = any(item.agent_label for item in visible)
    for item in visible:
        event = item.event
        hint_label = None
        pin = (version_pins or {}).get(event.id)
        marker = register_memory_read_report_hint(
            item, hint_state=hint_state, version_pin=pin
        )
        if marker is not None:
            hint_label = Text(f"{marker} ", style="bold #FFFF00")
        reason_indent = append_lane_row(
            text,
            timestamp=event.timestamp,
            glyph=MEMORY_GLYPH,
            glyph_style=COLOR_MEMORY_GLYPH,
            primary=truncate_display(_display_selector(event), PATH_LIMIT),
            primary_style=COLOR_MEMORY_PRIMARY,
            role_label=item.agent_label,
            show_role_column=show_role_column,
            hint_label=hint_label,
        )
        if event.frontmatter_stripped:
            text.append(f"  {FRONTMATTER_MARKER}", style=COLOR_FRONTMATTER)
        chip = (chips or {}).get(event.id)
        if chip is not None:
            text.append_text(chip.as_text())
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1].event
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )


def _append_launch_row(
    text: Text,
    launch_row: MemoryLaunchRow,
    *,
    hint_state: HeaderHintState | None,
    launch_pin: MemoryVersionPin | None,
) -> None:
    """Append the ``AGENTS.md as launched`` row with its version chip."""
    from ._agent_context_common import COLOR_TIMESTAMP

    hint_label = None
    if launch_pin is not None:
        marker = _register_memory_version_pin(
            launch_pin,
            hint_state=hint_state,
            fallback_path=launch_pin.snapshot_path or launch_pin.subject,
        )
        if marker is not None:
            hint_label = Text(f"{marker} ", style="bold #FFFF00")
    text.append("  launch    ", style=COLOR_TIMESTAMP)
    text.append(f"{LAUNCH_GLYPH} ", style=COLOR_MEMORY_GLYPH)
    if hint_label is not None:
        text.append_text(hint_label)
    text.append(
        truncate_display(launch_row.display, PATH_LIMIT),
        style=COLOR_MEMORY_PRIMARY,
    )
    if launch_row.chip is not None:
        text.append_text(launch_row.chip.as_text())
    text.append("\n")


def _display_selector(event: object) -> str:
    selectors = getattr(event, "selectors", ())
    resolved_path = getattr(event, "resolved_path", "")
    if not resolved_path and selectors:
        return ", ".join(selectors)
    canonical_path = getattr(event, "canonical_path", "")
    return str(canonical_path) if canonical_path else "(unknown)"
