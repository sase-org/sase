"""Compose the follow-up agent's prompt after a monitor reaches a terminal state.

Pure text formatting -- no I/O -- so the prompt shape is covered by golden
tests without needing a real monitor supervisor or spawned process.

The composed prompt is launched as another agent's initial chat message, so
it goes through the same xprompt/directive expansion as any user-typed
prompt. The routing prefix (``#fork:``, ``%model:``, ``%effort:``) is
deliberately live so the follow-up inherits conversation and model routing.
The rest of the body is enclosed in a disabled xprompt region so monitor
reason, next-action text, table cells, and output are delivered as literal
data. ``Command``/``Directory`` and retained output still use genuine fences
as defense in depth and to keep persisted prompts readable.
"""

from __future__ import annotations

from sase.shells.followup import fork_target_for_settled_starter
from sase.shells.prompt import (
    fenced_block as _fenced_block,
    format_shell_duration as _format_duration,
    shell_routing_prefix,
    untrusted_output_section,
)
from sase.xprompt._disabled_regions import wrap_disabled_region

from .result_projection import (
    DEFAULT_NEXT_OUTPUT,
    NEXT_OUTPUT_CHOICES,
    build_monitor_result_wire,
    output_cell_for_selection,
    select_monitor_result_evidence,
    selected_raw_limits,
)


def _elapsed_with_budget(elapsed_seconds: float, timeout_seconds: float) -> str:
    elapsed = _format_duration(elapsed_seconds)
    if timeout_seconds > 0:
        return f"{elapsed} of a {_format_duration(timeout_seconds)} budget"
    return elapsed


def _outcome_line(
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    timeout_seconds: float,
    idle_timeout_seconds: float,
    timeout_kind: object,
) -> str:
    if monitor_state == "completed":
        return f"COMPLETED — exit {exit_code if exit_code is not None else 0}"
    if monitor_state == "failed":
        code = exit_code if exit_code is not None else "unknown"
        return f"FAILED — exit {code}"
    if monitor_state == "timeout":
        if timeout_kind == "idle":
            return f"TIMED OUT — no output for {_format_duration(idle_timeout_seconds)}"
        budget = _elapsed_with_budget(elapsed_seconds, timeout_seconds)
        return f"TIMED OUT — did not finish after {budget}"
    return monitor_state.upper()


def _tail_section(output_text: str, tail_lines: int, max_chars: int) -> list[str]:
    return untrusted_output_section(
        f"## Last {tail_lines} lines of output",
        output_text,
        tail_lines,
        max_chars=max_chars,
    )


def _routing_prefix(
    starter_name: str | None,
    model: str | None,
    reasoning_effort: str | None,
    next_model: str | None = None,
    family_name: str | None = None,
) -> str:
    fork_target = fork_target_for_settled_starter(
        starter_name=starter_name,
        family_name=family_name,
        settled=starter_name is not None,
        prefer_exact_starter=True,
    )
    return shell_routing_prefix(fork_target, model, reasoning_effort, next_model)


def compose_followup_prompt(
    *,
    starter_name: str | None,
    command: str,
    cwd: str,
    reason: str,
    monitor_state: str,
    exit_code: int | None,
    started_at: str | None,
    stopped_at: str | None,
    elapsed_seconds: float,
    timeout_seconds: float,
    monitor_id: str,
    output_text: str,
    tail_lines: int,
    total_bytes: int,
    output_truncated: bool,
    next_action: str,
    idle_timeout_seconds: float = 0.0,
    timeout_kind: object = None,
    next_output: str = DEFAULT_NEXT_OUTPUT,
    output_log_path: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    next_model: str | None = None,
    family_name: str | None = None,
    workspace_degraded_reason: str | None = None,
    diagnostic_manifest: dict[str, object] | None = None,
    retained_log_metadata: dict[str, object] | None = None,
    evidence_selection: dict[str, object] | None = None,
    selected_diagnostics_text: str | None = None,
    starter_execution_id: str | None = None,
    workspace_identity: str | None = None,
) -> str:
    """Compose the follow-up agent's full prompt.

    ``starter_name`` set to ``None`` omits the ``#fork:`` prefix -- used when
    the starter did not settle to a terminal marker in time. ``model`` /
    ``reasoning_effort`` (the lane's newest member's routing, inherited onto
    this monitor member) become ``%model:`` / ``%effort:`` prefix directives
    so the follow-up launches with the same routing as the starter; both are
    stripped before the model sees the prompt. A nonempty ``next_model``
    (the ``sase monitor start --model`` selection) replaces that inherited
    pair with a single formatted ``%model:`` expression instead.

    ``next_output`` controls how retained output is projected: ``"auto"``
    (default) uses the outcome-aware Rust selector, ``"tail"`` embeds a
    bounded raw tail, ``"file"`` exposes refs/locators only, and ``"none"``
    leaves only facts plus the ``sase monitor show --all-lines`` pointer.
    """
    log_pointer = f"sase monitor show {monitor_id} --all-lines"
    diagnostic_ref = (
        diagnostic_manifest.get("manifest_ref") if diagnostic_manifest else None
    )
    retained_log = dict(retained_log_metadata or {})
    if not retained_log:
        retained_log = {
            "log_ref": f"file:monitor-retained-log:{monitor_id}",
            "local_locator": output_log_path,
            "total_observed_bytes": total_bytes,
            "complete": not output_truncated,
            "drain_confirmed": True,
        }
    result = build_monitor_result_wire(
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        exit_code=exit_code,
        command=command,
        cwd=cwd,
        started_at=started_at,
        stopped_at=stopped_at,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=timeout_seconds,
        timeout_kind=timeout_kind,
        starter_execution_id=starter_execution_id or starter_name or family_name,
        workspace_identity=workspace_identity or cwd,
        diagnostic_manifest_ref=diagnostic_ref,
        retained_log=retained_log,
    )
    selection = evidence_selection or select_monitor_result_evidence(
        result,
        next_output=next_output,
        diagnostic_manifest=diagnostic_manifest,
    )
    rows = [
        (
            "Outcome",
            _outcome_line(
                monitor_state,
                exit_code,
                elapsed_seconds,
                timeout_seconds,
                idle_timeout_seconds,
                timeout_kind,
            ),
        ),
        ("Started", started_at or "unknown"),
        ("Finished", stopped_at or "unknown"),
        ("Elapsed", _elapsed_with_budget(elapsed_seconds, timeout_seconds)),
        (
            "Output",
            output_cell_for_selection(
                total_bytes=total_bytes,
                output_truncated=output_truncated,
                selection=selection,
                log_pointer=log_pointer,
                output_log_path=output_log_path,
            ),
        ),
    ]
    table = "\n".join(f"| **{label}** | {value} |" for label, value in rows)

    sections = [
        "# Monitored command finished",
        "",
        *_fenced_block("Command", command),
        *_fenced_block("Directory", cwd),
        "| | |",
        "| --- | --- |",
        table,
        "",
        f"**Why this was monitored:** {reason}",
        "",
    ]
    raw_limits = selected_raw_limits(selection, requested_tail_lines=tail_lines)
    if selected_diagnostics_text and selection.get("diagnostic_stage_ids"):
        sections.extend(
            [
                "## Selected diagnostics",
                "",
                *_fenced_block(
                    "Diagnostics (untrusted program output)",
                    selected_diagnostics_text,
                ),
                "",
            ]
        )
    if raw_limits is not None:
        selected_tail_lines, max_chars = raw_limits
        sections.extend(_tail_section(output_text, selected_tail_lines, max_chars))
    if workspace_degraded_reason:
        sections.extend(
            [
                "## Follow-up workspace",
                "",
                workspace_degraded_reason,
                "",
            ]
        )
    sections.extend(
        [
            "## Your next action",
            "",
            next_action,
        ]
    )
    body = wrap_disabled_region("\n".join(sections))
    prefix = _routing_prefix(
        starter_name,
        model,
        reasoning_effort,
        next_model,
        family_name=family_name,
    )
    return f"{prefix}\n{body}" if prefix else body


__all__ = ["DEFAULT_NEXT_OUTPUT", "NEXT_OUTPUT_CHOICES", "compose_followup_prompt"]
