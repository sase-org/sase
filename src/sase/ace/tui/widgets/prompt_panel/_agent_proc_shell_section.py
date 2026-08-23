"""PROC SHELL detail section rendering for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text

from sase.ace.hooks.timestamps import format_duration
from sase.procs import TERMINAL_PROC_STATUSES, short_proc_id

from ...models.agent import Agent
from ...models.agent_time import compute_row_runtime
from ...models.fold_scale import AGENT_FOLD_SCALE, FoldScale, effective_fold_level
from ...models.fold_state import FoldLevel
from ...util.axe_log_renderer import render_axe_output
from ...util.lazy_syntax import lazy_renderable
from ._agent_context_common import COLOR_EMPTY, COLOR_REASON, COLOR_SUMMARY
from ._fold_language import append_fold_section_heading
from ._helpers import append_section_heading

PROC_SHELL_SECTION_ID = "proc-shell"
_COLOR_HEADER = "bold #5FD7FF underline"
_FIELD_LABEL_WIDTH = 15
_DIAGNOSTIC_LEVELS = frozenset({FoldLevel.FULLY_EXPANDED, FoldLevel.EXHAUSTIVE})

ProcShellTextAnnotator = Callable[[str | Text], Text]


def _field_label(label: str) -> str:
    return f"  {label:<{_FIELD_LABEL_WIDTH}}"


def _status_text(agent: Agent) -> Text:
    raw = agent.proc_status or agent.status.casefold()
    style = {
        "pending": "bold #87D7FF",
        "running": "bold #FFD700",
        "settling": "bold #FFAF5F",
        "success": "bold #5FD75F",
        "error": "bold #FF5F5F",
        "killed": "bold #AF87FF",
    }.get(raw, "dim")
    return Text(f"{agent.display_status} ({raw})", style=style)


def _append_label_value(
    text: Text,
    label: str,
    value: object | None,
    *,
    value_style: str = COLOR_REASON,
) -> None:
    if value is None or value == "":
        return
    text.append(_field_label(f"{label}:"), style=COLOR_SUMMARY)
    text.append(f"{value}\n", style=value_style)


def _proc_output_source_id(agent: Agent) -> str:
    return f"proc-shell:{agent.proc_id or agent.identity}"


def _show_proc_phase(agent: Agent) -> bool:
    return bool(
        agent.proc_phase and (agent.proc_status or "") not in TERMINAL_PROC_STATUSES
    )


def _diagnostic_count(agent: Agent) -> int:
    values = (
        agent.proc_origin,
        agent.proc_code_digest,
        agent.proc_request_fingerprint,
        agent.proc_supervisor_id,
        agent.proc_settlement_state,
        agent.monitor_command,
    )
    return sum(1 for value in values if value)


def _diagnostic_summary(agent: Agent) -> str | None:
    count = _diagnostic_count(agent)
    return f"+{count} diagnostics" if count else None


def _proc_field_parts(
    agent: Agent,
    *,
    include_diagnostics: bool,
    annotate: ProcShellTextAnnotator | None = None,
    prefix: Text | None = None,
) -> list[object]:
    parts: list[object] = []
    text = prefix if prefix is not None else Text(end="")

    text.append(_field_label("Status:"), style=COLOR_SUMMARY)
    text.append_text(_status_text(agent))
    if agent.monitor_exit_code is not None:
        exit_style = "dim" if agent.monitor_exit_code == 0 else "bold red"
        text.append(f"  (exit {agent.monitor_exit_code})", style=exit_style)
    text.append("\n")
    _append_label_value(text, "Language", agent.proc_language, value_style="#87D7FF")
    if _show_proc_phase(agent):
        _append_label_value(text, "Phase", agent.proc_phase, value_style="#FFAF5F")

    _, elapsed = compute_row_runtime(agent)
    if agent.monitor_timeout_seconds is not None:
        timeout_label = format_duration(agent.monitor_timeout_seconds)
        text.append(_field_label("Timeout:"), style=COLOR_SUMMARY)
        text.append(f"{elapsed or '-'} of {timeout_label} budget\n", style=COLOR_REASON)
    elif elapsed:
        _append_label_value(text, "Elapsed", elapsed)
    if agent.monitor_idle_timeout_seconds is not None:
        idle_label = format_duration(agent.monitor_idle_timeout_seconds)
        text.append(_field_label("Idle timeout:"), style=COLOR_SUMMARY)
        text.append(f"{idle_label} without output\n", style=COLOR_REASON)

    if agent.proc_waits:
        text.append(_field_label("Waits:"), style=COLOR_SUMMARY)
        text.append(", ".join(agent.proc_waits[:8]), style=COLOR_REASON)
        if len(agent.proc_waits) > 8:
            text.append(f" +{len(agent.proc_waits) - 8}", style="dim")
        text.append("\n")
    if agent.proc_condition_result:
        _append_label_value(text, "Condition", agent.proc_condition_result)

    if agent.proc_id:
        proc_short = short_proc_id(agent.proc_id)
        text.append(_field_label("Proc id:"), style=COLOR_SUMMARY)
        text.append(agent.proc_id, style=COLOR_REASON)
        text.append(f"  ({proc_short})\n", style="dim")
        text.append(_field_label(""), style=COLOR_SUMMARY)
        text.append(f"sase proc show {proc_short} --follow\n", style=COLOR_EMPTY)
    if agent.proc_log_path:
        _append_label_value(text, "Log path", agent.proc_log_path)

    if include_diagnostics:
        _append_label_value(text, "Origin", agent.proc_origin, value_style="#D7D7FF")
        _append_label_value(
            text, "Digest", agent.proc_code_digest, value_style="#D7D7FF"
        )
        _append_label_value(
            text,
            "Fingerprint",
            agent.proc_request_fingerprint,
            value_style="#D7D7FF",
        )
        _append_label_value(text, "Supervisor", agent.proc_supervisor_id)
        _append_label_value(text, "Settlement", agent.proc_settlement_state)
        if agent.monitor_command:
            text.append(_field_label("Runtime argv:") + "\n", style=COLOR_SUMMARY)
            parts.append(text)
            command = agent.monitor_command + "\n"
            if annotate is None:
                parts.append(lazy_renderable(command, "bash"))
            else:
                parts.append(annotate(command))
            text = Text(end="")

    parts.append(text)
    return parts


def build_proc_shell_section(
    agent: Agent,
    *,
    panel_level: FoldLevel = FoldLevel.COLLAPSED,
    scale: FoldScale = AGENT_FOLD_SCALE,
    annotate: ProcShellTextAnnotator | None = None,
) -> list[object]:
    """Return the foldable proc-shell metadata section."""
    text = Text(end="")
    level = effective_fold_level(panel_level, scale)
    include_diagnostics = level in _DIAGNOSTIC_LEVELS
    heading = Text(end="")
    append_fold_section_heading(
        heading,
        "PROC DETAILS",
        section_id=PROC_SHELL_SECTION_ID,
        level=level,
        scale=scale,
        summary=None if include_diagnostics else _diagnostic_summary(agent),
        style=_COLOR_HEADER,
    )
    text.append_text(heading)
    return _proc_field_parts(
        agent,
        include_diagnostics=include_diagnostics,
        annotate=annotate,
        prefix=text,
    )


def build_proc_shell_preview(
    agent: Agent,
    *,
    annotate: ProcShellTextAnnotator | None = None,
) -> list[object]:
    """Return the safe source preview block for one proc shell."""
    if not agent.proc_safe_preview:
        return []
    header = Text()
    header.append("\n")
    header.append("─" * 50 + "\n", style="dim")
    header.append("\n")
    append_section_heading(header, "COMMAND")
    language = agent.proc_language or "bash"
    if annotate is not None:
        return [header, annotate(agent.proc_safe_preview + "\n")]
    return [header, lazy_renderable(agent.proc_safe_preview, language)]


def build_proc_shell_output(
    agent: Agent,
    *,
    annotate: ProcShellTextAnnotator | None = None,
) -> list[object]:
    """Return the bounded combined-log tail for one proc shell."""
    header = Text()
    header.append("\n")
    header.append("─" * 50 + "\n", style="dim")
    header.append("\n")
    append_section_heading(header, "LOG TAIL")
    output = agent.proc_log_tail
    if not output:
        header.append("No output yet.\n", style="dim italic")
        return [header]
    parts: list[object] = [header]
    if agent.proc_output_truncated:
        parts.append(
            Text(
                "... output truncated (head + tail retained) ...\n",
                style="yellow",
            )
        )
    body: object = render_axe_output(_proc_output_source_id(agent), output, "ansi")
    if annotate is not None:
        body = annotate(body if isinstance(body, Text) else str(body))
    parts.append(body)
    return parts


__all__ = [
    "PROC_SHELL_SECTION_ID",
    "ProcShellTextAnnotator",
    "build_proc_shell_output",
    "build_proc_shell_preview",
    "build_proc_shell_section",
]
