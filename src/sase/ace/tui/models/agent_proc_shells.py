"""Agents-tab projection for stand-alone xprompt proc shells."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
import json
import re
from typing import Any

from rich.cells import cell_len

from sase.procs import (
    ACTIVE_PROC_STATUSES,
    PROC_LIFECYCLE_PROC_SHELL,
    XPROMPT_PROC_ORIGIN,
    short_proc_id,
)
from sase.project_display_names import project_display_name_for

from .._proc_observer_models import ObservedProc
from .agent import Agent
from .agent_types import AgentType

_PROC_PREVIEW_MAX_CHARS = 4000
_PROC_LOG_TAIL_MAX_CHARS = 12000
_PROC_COMMAND_TITLE_MAX_CELLS = 48
_PROC_COMMAND_TITLE_PREFIX = "❯ "
_ELLIPSIS = "…"
_SENSITIVE_LINE_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|bearer)\b"
)


def proc_shell_agents_from_observed(
    rows: Sequence[ObservedProc],
    *,
    dismissed_proc_ids: Collection[str] = (),
) -> list[Agent]:
    """Project observer-cached proc-shell rows into presentation-only Agent rows."""
    selected: dict[str, ObservedProc] = {}
    dismissed = set(dismissed_proc_ids)
    for row in rows:
        if not _is_standalone_xprompt_row(row):
            continue
        if row.proc_id in dismissed:
            continue
        selected.setdefault(row.proc_id, row)
    return [_observed_proc_to_agent(row) for row in selected.values()]


def merge_proc_shell_agents(
    agents: Sequence[Agent],
    proc_shells: Sequence[Agent],
) -> list[Agent]:
    """Return *agents* with the proc-shell projection replaced atomically."""
    return [
        *(agent for agent in agents if not agent.is_proc_shell),
        *proc_shells,
    ]


def proc_shell_agent_signature(
    agents: Sequence[Agent],
) -> tuple[tuple[object, ...], ...]:
    """Return a stable equality key for projected proc-shell row state."""
    return tuple(
        (
            agent.identity,
            agent.status,
            agent.status_bucket,
            agent.start_time,
            agent.stop_time,
            agent.monitor_command,
            agent.monitor_cwd,
            agent.monitor_timeout_seconds,
            agent.monitor_idle_timeout_seconds,
            agent.monitor_exit_code,
            agent.proc_status,
            agent.proc_phase,
            agent.proc_label,
            agent.proc_origin,
            agent.proc_language,
            agent.proc_code_digest,
            agent.proc_safe_preview,
            agent.proc_log_path,
            agent.proc_log_tail,
            tuple(agent.proc_waits),
            agent.proc_condition_result,
            agent.proc_supervisor_id,
            agent.proc_settlement_state,
            agent.proc_request_fingerprint,
            agent.project_display_name,
        )
        for agent in agents
    )


def _is_standalone_xprompt_row(row: ObservedProc) -> bool:
    return (
        row.lifecycle == PROC_LIFECYCLE_PROC_SHELL and row.origin == XPROMPT_PROC_ORIGIN
    )


def _observed_proc_to_agent(row: ObservedProc) -> Agent:
    project_key = row.project or row.cl_name or "proc"
    meta = row.xprompt_proc or {}
    label = _explicit_proc_label(row, meta)
    shell_name = row.shell_name or short_proc_id(row.proc_id)
    agent = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name=project_key,
        project_file="",
        status=_display_status_value(row.status),
        status_bucket=_status_bucket_value(row.status),
        start_time=row.started_at or row.reserved_at,
        run_start_time=row.started_at,
        stop_time=row.finished_at or row.settled_at,
        workspace_num=row.workspace_num,
        workspace_dir=row.cwd or None,
        raw_suffix=row.proc_id,
        agent_name=shell_name,
        output_path=row.log_path or None,
        monitor_command=" ".join(row.command or ()),
        monitor_label=label,
        monitor_cwd=row.cwd or None,
        monitor_timeout_seconds=(
            float(row.timeout_seconds) if row.timeout_seconds is not None else None
        ),
        monitor_idle_timeout_seconds=(
            float(row.idle_timeout_seconds)
            if row.idle_timeout_seconds is not None
            else None
        ),
        monitor_exit_code=row.exit_code,
        proc_id=row.proc_id,
        proc_status=row.status,
        proc_phase=row.phase,
        proc_label=label,
        proc_origin=row.origin,
        proc_language=_observed_proc_language(row, meta),
        proc_code_digest=_string_meta(meta, "code_digest"),
        proc_safe_preview=_safe_preview(meta),
        proc_log_path=row.log_path or None,
        proc_log_tail=_bound_and_redact(row.output, _PROC_LOG_TAIL_MAX_CHARS) or "",
        proc_waits=_wait_labels(meta.get("waits")),
        proc_condition_result=_condition_result(meta.get("condition_result")),
        proc_supervisor_id=row.supervisor_id,
        proc_settlement_state=_observed_settlement_state(row),
        proc_request_fingerprint=row.request_fingerprint,
        project_display_name=(
            project_display_name_for(project_key) if project_key != "proc" else None
        ),
    )
    return agent


def proc_shell_command_title(preview: str | None) -> str | None:
    """Return the compact command title for an unlabeled proc shell."""
    if not preview:
        return None
    nonblank_lines = [line for line in preview.splitlines() if line.strip()]
    if not nonblank_lines:
        return None
    first_line = re.sub(r"\s+", " ", nonblank_lines[0]).strip()
    if first_line.endswith("\\"):
        first_line = first_line[:-1].rstrip()
    if not first_line:
        return None
    title = f"{_PROC_COMMAND_TITLE_PREFIX}{first_line}"
    if len(nonblank_lines) > 1 or cell_len(title) > _PROC_COMMAND_TITLE_MAX_CELLS:
        return _ellipsize_cells(title, _PROC_COMMAND_TITLE_MAX_CELLS)
    return title


def _ellipsize_cells(value: str, max_cells: int) -> str:
    ellipsis_cells = cell_len(_ELLIPSIS)
    if max_cells <= ellipsis_cells:
        return _ELLIPSIS
    if cell_len(value) + ellipsis_cells <= max_cells:
        return f"{value}{_ELLIPSIS}"
    budget = max_cells - ellipsis_cells
    out = ""
    cells = 0
    for character in value:
        character_cells = cell_len(character)
        if cells + character_cells > budget:
            break
        out += character
        cells += character_cells
    return f"{out.rstrip()}{_ELLIPSIS}"


def _explicit_proc_label(row: ObservedProc, meta: Mapping[str, Any]) -> str | None:
    label = _string_meta(meta, "label")
    if label:
        return label
    if row.shell_name:
        return row.shell_name
    logical_id = _string_meta(meta, "logical_id")
    if row.display_name and row.display_name != logical_id:
        # Compatibility for proc-shell rows submitted before label provenance existed.
        return row.display_name
    return None


def _display_status_value(status: str) -> str:
    if status == "pending":
        return "STARTING"
    if status == "running":
        return "RUNNING"
    if status == "settling":
        return "SETTLING"
    if status == "success":
        return "DONE"
    if status == "error":
        return "FAILED"
    if status == "killed":
        return "STOPPED"
    return status.upper()


def _status_bucket_value(status: str) -> str:
    if status == "pending":
        return "Starting"
    if status in ACTIVE_PROC_STATUSES:
        return "Running"
    if status == "error":
        return "Failed"
    return "Done"


def _observed_proc_language(
    row: ObservedProc,
    meta: Mapping[str, Any],
) -> str | None:
    value = _string_meta(meta, "code_language") or _string_meta(meta, "language")
    if value:
        return value
    code = meta.get("code")
    if isinstance(code, Mapping):
        value = _string_meta(code, "language") or _string_meta(code, "info_string")
        if value:
            return value
    shell_kind = row.shell_kind or ""
    if shell_kind:
        return shell_kind
    command = " ".join(row.command or ()).casefold()
    if "python" in command:
        return "python"
    if command:
        return "bash"
    return None


def _safe_preview(meta: Mapping[str, Any]) -> str | None:
    preview = _string_meta(meta, "code_preview") or _string_meta(meta, "safe_preview")
    if preview is None:
        code = meta.get("code")
        if isinstance(code, Mapping):
            preview = _string_meta(code, "preview")
    return _bound_and_redact(preview, _PROC_PREVIEW_MAX_CHARS)


def _wait_labels(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    labels: list[str] = []
    for item in raw:
        label = _wait_label(item)
        if label:
            labels.append(label)
    return labels


def _wait_label(item: object) -> str | None:
    if isinstance(item, Mapping):
        kind = _first_string(item, "kind", "type", "wait_type", "mode") or "wait"
        target = _first_string(item, "target", "name", "value", "id", "ref")
        if target:
            return f"{kind}: {target}"
        return kind
    if item is None:
        return None
    return str(item)


def _condition_result(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        status = _first_string(raw, "status", "outcome", "result")
        reason = _first_string(raw, "reason", "message", "summary")
        if status and reason:
            return f"{status}: {reason}"
        return status or reason or _bounded_json(raw, 400)
    return _bound_and_redact(str(raw), 400)


def _observed_settlement_state(row: ObservedProc) -> str | None:
    if row.settled_by:
        when = f" at {row.settled_at}" if row.settled_at else ""
        return f"settled by {row.settled_by}{when}"
    if row.settling_started_at:
        return f"settling since {row.settling_started_at}"
    if row.stop_requested_at:
        who = f" by {row.stop_requested_by}" if row.stop_requested_by else ""
        reason = f": {row.stop_reason}" if row.stop_reason else ""
        return f"stop requested{who}{reason}"
    return None


def _string_meta(meta: Mapping[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _first_string(meta: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _string_meta(meta, key)
        if value:
            return value
    return None


def _bound_and_redact(raw: str | None, max_chars: int) -> str | None:
    if not raw:
        return None
    lines = [
        "<redacted sensitive line>" if _SENSITIVE_LINE_RE.search(line) else line
        for line in raw.splitlines()
    ]
    value = "\n".join(lines)
    if len(value) <= max_chars:
        return value
    return f"{value[-max_chars:]}\n... truncated to last {max_chars} chars ..."


def _bounded_json(value: Mapping[str, Any], max_chars: int) -> str:
    try:
        rendered = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        rendered = str(value)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max_chars - 3] + "..."


__all__ = [
    "merge_proc_shell_agents",
    "proc_shell_command_title",
    "proc_shell_agent_signature",
    "proc_shell_agents_from_observed",
]
