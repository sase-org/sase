"""GATE detail section rendering for the agent prompt panel."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from rich.text import Text

from sase.ace.hooks.timestamps import format_duration
from sase.agent.artifact_files_cache import get_global_cache
from sase.core.time import local_now
from sase.gate_shell.naming import short_gate_shell_id
from sase.gate_shell.state import (
    GATE_FAILURE_GLYPH_COLOR,
    GATE_GLYPH,
    GATE_SETTLED_GLYPH_COLOR,
)
from sase.gate_shell.status import (
    effective_gate_status,
    gate_status_pair,
    gate_status_style,
)
from sase.notification_gates.branches import GateBranchData

from ...models.agent import Agent
from ...models.fold_scale import AGENT_FOLD_SCALE, FoldScale, effective_fold_level
from ...models.fold_state import FoldLevel
from ...util.axe_log_renderer import render_axe_output
from ...util.lazy_syntax import lazy_renderable
from ._agent_context_common import COLOR_EMPTY, COLOR_REASON, COLOR_SUMMARY
from ._agent_display_content import get_phase_label, render_phase_divider
from ._fold_language import append_fold_section_heading
from ._helpers import append_section_heading

GATE_PHASE_LABEL = "GATE"
GATE_SECTION_ID = "gate"
_COLOR_HEADER = "bold #0BCDEC underline"
_FIELD_LABEL_WIDTH = 15

_STATE_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": (GATE_GLYPH, "bold #0BCDEC"),
    "settling": ("●", "bold green"),
    "answered": ("✓", GATE_SETTLED_GLYPH_COLOR),
    "completed": ("✓", GATE_SETTLED_GLYPH_COLOR),
    "failed": ("✗", f"bold {GATE_FAILURE_GLYPH_COLOR}"),
    "timeout": ("⧖", f"bold {GATE_FAILURE_GLYPH_COLOR}"),
    "stopped": ("⊘", GATE_SETTLED_GLYPH_COLOR),
    "lost": ("?", f"bold {GATE_FAILURE_GLYPH_COLOR}"),
}

GateTextAnnotator = Callable[[str | Text], Text]


def _field_label(label: str) -> str:
    return f"  {label:<{_FIELD_LABEL_WIDTH}}"


def _state_text(gate_state: str | None) -> Text:
    glyph, style = _STATE_DISPLAY.get(gate_state or "", ("?", "dim"))
    return Text(f"{glyph} {gate_state or 'unknown'}", style=style)


def _status_pair_text(agent: Agent) -> Text:
    pair = gate_status_pair(agent.gate_start_status, agent.gate_stop_status)
    style = gate_status_style(
        pair,
        gate_state=agent.gate_state,
        accent=agent.gate_accent,
    )
    effective = effective_gate_status(
        pair,
        gate_state=agent.gate_state,
        settled=False,
    )
    text = Text()
    if pair.start == pair.stop:
        text.append(pair.start, style=style)
        return text
    text.append(pair.start, style=style if effective == pair.start else "dim")
    text.append(" → ", style="dim")
    text.append(pair.stop, style=style if effective == pair.stop else "dim")
    return text


def _gate_output_source_id(agent: Agent) -> str:
    return f"gate:{agent.gate_id or agent.identity}"


def _read_bundle_json(bundle_path: str | None, filename: str) -> Mapping[str, Any]:
    if not bundle_path:
        return {}
    data = get_global_cache().read_json(str(Path(bundle_path) / filename))
    return data if isinstance(data, Mapping) else {}


def _branch_summary(agent: Agent) -> Text:
    envelope = _read_bundle_json(agent.gate_bundle_path, "request.json")
    response = _read_bundle_json(agent.gate_bundle_path, "response.json")
    text = Text(end="")
    if not envelope:
        return text
    try:
        branch_data = GateBranchData.from_envelope(envelope)
    except Exception:
        return text
    selected = response.get("selected_option_ids")
    selected_ids = (
        {str(item) for item in selected} if isinstance(selected, list) else set()
    )
    labels = {option.id: option.label for option in branch_data.options}
    text.append(_field_label("Branches:") + "\n", style=COLOR_SUMMARY)
    for branch in branch_data.branches:
        selected_marker = "x" if selected_ids and selected_ids == set(branch) else " "
        primary = " ★" if branch == branch_data.primary_branch else ""
        label = " + ".join(labels.get(option_id, option_id) for option_id in branch)
        text.append(f"    [{selected_marker}] {label}", style=COLOR_REASON)
        text.append(f" ({'+'.join(branch)}){primary}\n", style="dim")
    return text


def _response_summary(agent: Agent) -> list[object]:
    response = _read_bundle_json(agent.gate_bundle_path, "response.json")
    if not response:
        return []
    parts: list[object] = []
    text = Text(end="")
    feedback = response.get("feedback")
    if isinstance(feedback, str) and feedback:
        text.append(_field_label("Reviewer note:") + "\n", style=COLOR_SUMMARY)
        text.append(feedback.rstrip() + "\n", style=COLOR_REASON)
    option_results = response.get("option_results")
    if isinstance(option_results, list) and option_results:
        text.append(_field_label("Option JSON:") + "\n", style=COLOR_SUMMARY)
        parts.append(text)
        parts.append(lazy_renderable(json.dumps(option_results, indent=2), "json"))
        return parts
    if text.cell_len:
        parts.append(text)
    return parts


def _deadline_text(agent: Agent) -> str | None:
    if agent.gate_timeout_seconds is None:
        return None
    start = agent.run_start_time or agent.start_time
    if start is None:
        return None
    deadline = start + timedelta(seconds=agent.gate_timeout_seconds)
    remaining = (deadline - local_now()).total_seconds()
    if remaining > 0 and agent.gate_state not in {
        "answered",
        "completed",
        "failed",
        "timeout",
        "stopped",
        "lost",
    }:
        return f"{deadline:%Y-%m-%d %H:%M:%S} ({format_duration(remaining)} left)"
    return f"{deadline:%Y-%m-%d %H:%M:%S}"


def _gate_field_parts(
    agent: Agent,
    *,
    prefix: Text | None = None,
) -> list[object]:
    parts: list[object] = []
    text = prefix if prefix is not None else Text(end="")

    text.append(_field_label("Decision:"), style=COLOR_SUMMARY)
    text.append(
        agent.gate_label or agent.gate_kind or agent.gate_id or "gate",
        style=COLOR_REASON,
    )
    text.append("\n")
    if agent.gate_kind:
        text.append(_field_label("Kind:"), style=COLOR_SUMMARY)
        text.append(f"{agent.gate_kind}\n", style=COLOR_REASON)
    text.append(_field_label("Status:"), style=COLOR_SUMMARY)
    text.append_text(_status_pair_text(agent))
    text.append("\n")
    text.append(_field_label("State:"), style=COLOR_SUMMARY)
    text.append_text(_state_text(agent.gate_state))
    text.append("\n")

    if agent.gate_elapsed_seconds is not None:
        text.append(_field_label("Elapsed:"), style=COLOR_SUMMARY)
        text.append(
            f"{format_duration(agent.gate_elapsed_seconds)}\n", style=COLOR_REASON
        )
    deadline = _deadline_text(agent)
    if deadline:
        text.append(_field_label("Deadline:"), style=COLOR_SUMMARY)
        text.append(f"{deadline}\n", style=COLOR_REASON)
    if agent.gate_reason:
        text.append(_field_label("Reason:"), style=COLOR_SUMMARY)
        text.append(f"{agent.gate_reason}\n", style=COLOR_REASON)

    if agent.gate_id:
        text.append(_field_label("Gate id:"), style=COLOR_SUMMARY)
        text.append(agent.gate_id, style=COLOR_REASON)
        text.append(f"  ({short_gate_shell_id(agent.gate_id)})\n", style="dim")
        text.append(_field_label(""), style=COLOR_SUMMARY)
        text.append(
            f"sase gate show {short_gate_shell_id(agent.gate_id)}\n",
            style=COLOR_EMPTY,
        )
    if agent.gate_bundle_path:
        text.append(_field_label("Bundle:"), style=COLOR_SUMMARY)
        text.append(f"{agent.gate_bundle_path}\n", style=COLOR_EMPTY)
    if agent.gate_decision_path:
        text.append(_field_label("Decision file:"), style=COLOR_SUMMARY)
        text.append(f"{agent.gate_decision_path}\n", style=COLOR_EMPTY)
    if agent.gate_next_action:
        text.append(_field_label("Next action:"), style=COLOR_SUMMARY)
        text.append(f"{agent.gate_next_action}\n", style=COLOR_REASON)
    if agent.gate_followup_outcome or agent.gate_followup_error:
        text.append(_field_label("Follow-up:"), style=COLOR_SUMMARY)
        text.append(agent.gate_followup_outcome or "attention", style=COLOR_REASON)
        if agent.gate_followup_error:
            text.append(f" · {agent.gate_followup_error}", style="bold #FFAF00")
        text.append("\n")

    branch_text = _branch_summary(agent)
    if branch_text.cell_len:
        text.append_text(branch_text)
    parts.append(text)
    parts.extend(_response_summary(agent))
    return parts


def build_gate_section(
    agent: Agent,
    *,
    panel_level: FoldLevel = FoldLevel.COLLAPSED,
    scale: FoldScale = AGENT_FOLD_SCALE,
) -> list[object]:
    """Return the GATE section renderables: heading and structured fields."""
    text = Text(end="")
    level = effective_fold_level(panel_level, scale)
    heading = Text(end="")
    append_fold_section_heading(
        heading,
        GATE_PHASE_LABEL,
        section_id=GATE_SECTION_ID,
        level=level,
        scale=scale,
        style=_COLOR_HEADER,
    )
    text.append_text(heading)
    return _gate_field_parts(agent, prefix=text)


def build_gate_output(
    agent: Agent,
    *,
    heading: bool = True,
    annotate: GateTextAnnotator | None = None,
) -> list[object]:
    """Return the captured-output block for a gate row or family phase."""
    output = agent.get_live_reply_content()
    if heading:
        header = Text()
        header.append("\n")
        header.append("─" * 50 + "\n", style="dim")
        header.append("\n")
        append_section_heading(header, "OUTPUT")
        if not output:
            header.append("No output yet.\n", style="dim italic")
            return [header]
        parts: list[object] = [header]
    else:
        header = Text(end="")
        header.append(_field_label("Output:") + "\n", style=COLOR_SUMMARY)
        if not output:
            header.append("No output yet.\n", style="dim italic")
            return [header]
        parts = [header]

    if agent.gate_output_truncated:
        parts.append(
            Text("… output truncated (head + tail retained) …\n", style="yellow")
        )
    body: object = render_axe_output(_gate_output_source_id(agent), output, "ansi")
    if annotate is not None:
        body = annotate(body if isinstance(body, Text) else str(body))
    parts.append(body)
    return parts


def build_gate_phase(
    agent: Agent,
    *,
    annotate: GateTextAnnotator | None = None,
) -> list[object]:
    """Return the family-facing GATE phase: divider, fields, and log."""
    accent = agent.gate_accent or "#0BCDEC"
    parts: list[object] = [
        render_phase_divider(
            get_phase_label(agent),
            agent.run_start_time or agent.start_time,
            accent=accent,
            glyph=GATE_GLYPH,
        )
    ]
    parts.extend(_gate_field_parts(agent))
    parts.extend(build_gate_output(agent, heading=False, annotate=annotate))
    return parts


__all__ = [
    "GATE_PHASE_LABEL",
    "GATE_SECTION_ID",
    "GateTextAnnotator",
    "build_gate_output",
    "build_gate_phase",
    "build_gate_section",
]
