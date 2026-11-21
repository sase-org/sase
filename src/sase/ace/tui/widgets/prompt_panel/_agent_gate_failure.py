"""Accepted-but-failed gate failure fields for the GATE detail section.

Use-site helper: imported lazily from
:mod:`sase.ace.tui.widgets.prompt_panel._agent_gate_section` so the
failure rendering stays out of the TUI startup closure. Render paths
must not stat/glob; loaders already project
``agent.gate_execution_failure``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.text import Text

    from ...models.agent import Agent


def _field_label(label: str) -> str:
    # Mirrors _agent_gate_section._field_label (width 15); use-site import
    # of that module would be circular at render time, so the one-line
    # format lives here instead.
    return f"  {label:<15}"


def execution_failure_for(agent: Agent) -> dict[str, object] | None:
    """Return the loader-projected execution failure, if any."""
    failure = getattr(agent, "gate_execution_failure", None)
    return failure if isinstance(failure, dict) else None


def append_failure_fields(text: Text, agent: Agent) -> None:
    """Append the failure line and recovery commands to *text*."""
    # Use-site import: these modules stay out of the TUI startup closure.
    from ._agent_context_common import COLOR_EMPTY, COLOR_REASON, COLOR_SUMMARY

    failure = execution_failure_for(agent)
    if not isinstance(failure, dict):
        return
    stage = failure.get("stage") or "execution"
    code = failure.get("code") or "failed"
    message = failure.get("message") or ""
    text.append(_field_label("Failed:"), style=COLOR_SUMMARY)
    text.append(f"{stage}/{code}", style="bold #FF5F5F")
    if isinstance(message, str) and message:
        text.append(f" · {message}", style=COLOR_REASON)
    text.append("\n")
    report = failure.get("error_report_path")
    if isinstance(report, str) and report:
        text.append(_field_label("Error report:"), style=COLOR_SUMMARY)
        text.append(f"{report}\n", style=COLOR_EMPTY)
    for key, label in (
        ("resume_command", "Resume"),
        ("restart_command", "Restart"),
        ("cancel_command", "Cancel"),
    ):
        command = failure.get(key)
        if isinstance(command, str) and command:
            text.append(_field_label(f"{label}:"), style=COLOR_SUMMARY)
            text.append(f"{command}\n", style=COLOR_EMPTY)
    text.append(_field_label("Recovery:"), style=COLOR_SUMMARY)
    text.append("Enter reuses the gate-failure recovery dialog\n", style="dim")


__all__ = ["append_failure_fields", "execution_failure_for"]
