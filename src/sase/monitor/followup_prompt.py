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

from collections.abc import Mapping
import json
from typing import Any

from sase.llm_provider.continuation_budget_spans import open_reducible_span_marker
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
    command_text_for_monitor_result,
    output_cell_for_selection,
    retained_log_is_truncated,
    retained_log_locator_for_monitor_result,
    retained_log_total_bytes,
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
        if timeout_kind in {"idle", "no_progress"}:
            return f"TIMED OUT — no output for {_format_duration(idle_timeout_seconds)}"
        budget = _elapsed_with_budget(elapsed_seconds, timeout_seconds)
        return f"TIMED OUT — did not finish after {budget}"
    return monitor_state.upper()


def _tail_section(output_text: str, tail_lines: int, max_chars: int) -> list[str]:
    rendered = untrusted_output_section(
        f"## Last {tail_lines} lines of output",
        output_text,
        tail_lines,
        max_chars=max_chars,
    )
    heading, *body = rendered
    return [heading, *_reducible_span("old_raw_excerpts", body)]


def _reducible_span(kind: str, body: list[str]) -> list[str]:
    open_marker, close_marker = open_reducible_span_marker(kind=kind)
    return [open_marker, *body, close_marker]


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
    monitor_result: Mapping[str, Any] | None = None,
    checkpoint_ref: str | None = None,
    checkpoint_body: Mapping[str, Any] | None = None,
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
    frozen_result = dict(monitor_result or {})
    if frozen_result:
        monitor_id = _result_text(frozen_result, "monitor_id", monitor_id) or monitor_id
        monitor_state = _monitor_state_from_result(frozen_result, monitor_state)
        exit_code = _result_int(frozen_result, "exit_code", exit_code)
        command = command_text_for_monitor_result(frozen_result, fallback=command)
        cwd = _result_text(frozen_result, "cwd", cwd) or cwd
        started_at = _result_text(frozen_result, "started_at", started_at)
        stopped_at = _result_text(frozen_result, "ended_at", stopped_at)
        elapsed_seconds = _seconds_from_ms(
            frozen_result.get("elapsed_ms"),
            elapsed_seconds,
        )
        timeout_seconds = _seconds_from_ms(
            frozen_result.get("timeout_budget_ms"),
            timeout_seconds,
        )
        timeout_kind = frozen_result.get("timeout_kind") or timeout_kind
        total_bytes = retained_log_total_bytes(frozen_result, fallback=total_bytes)
        output_truncated = retained_log_is_truncated(
            frozen_result,
            fallback=output_truncated,
        )
        output_log_path = retained_log_locator_for_monitor_result(
            frozen_result,
            fallback=output_log_path,
        )
        retained = frozen_result.get("retained_log")
        if isinstance(retained, Mapping):
            retained_log_metadata = dict(retained)

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
    result = (
        frozen_result
        if frozen_result
        else build_monitor_result_wire(
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
                *_reducible_span(
                    "newest_diagnostics",
                    _fenced_block(
                        "Diagnostics (untrusted program output)",
                        selected_diagnostics_text,
                    ),
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
    if checkpoint_ref or checkpoint_body:
        sections.extend(_checkpoint_section(checkpoint_ref, checkpoint_body))
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


def _checkpoint_section(
    checkpoint_ref: str | None,
    checkpoint_body: Mapping[str, Any] | None,
) -> list[str]:
    rows = ["## Continuation checkpoint", ""]
    if checkpoint_ref:
        rows.extend([f"- **Ref:** `{checkpoint_ref}`", ""])
    if checkpoint_body:
        rows.extend(
            [
                *_fenced_block(
                    "Checkpoint (JSON)",
                    json.dumps(
                        checkpoint_body,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                ),
                "",
            ]
        )
    else:
        rows.extend(["_Checkpoint body was unavailable from the frozen ref._", ""])
    return rows


def _monitor_state_from_result(
    result: Mapping[str, Any],
    fallback: str,
) -> str:
    outcome = result.get("outcome")
    return outcome if isinstance(outcome, str) and outcome else fallback


def _result_text(
    result: Mapping[str, Any],
    key: str,
    fallback: str | None,
) -> str | None:
    value = result.get(key)
    return value if isinstance(value, str) and value else fallback


def _result_int(
    result: Mapping[str, Any],
    key: str,
    fallback: int | None,
) -> int | None:
    value = result.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _seconds_from_ms(value: object, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return fallback
    return max(0.0, float(value) / 1000.0)


__all__ = ["DEFAULT_NEXT_OUTPUT", "NEXT_OUTPUT_CHOICES", "compose_followup_prompt"]
