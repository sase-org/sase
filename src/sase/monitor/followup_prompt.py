"""Compose the follow-up agent's prompt after a monitor reaches a terminal state.

Pure text formatting -- no I/O -- so the prompt shape is covered by golden
tests without needing a real monitor supervisor or spawned process.
"""

from __future__ import annotations


def _format_duration(seconds: float) -> str:
    """Render *seconds* as a compact ``1h 2m 3s``-style duration."""
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


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


def _widen_fence(text: str) -> str:
    """Return a backtick fence at least one longer than any run in *text*."""
    longest_run = 0
    current_run = 0
    for char in text:
        if char == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return "`" * max(3, longest_run + 1)


def _tail_lines(text: str, count: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-count:]) if count > 0 else ""


def _format_output_summary(total_bytes: int, truncated: bool) -> str:
    kib = total_bytes / 1024
    summary = f"{kib:,.0f} KiB" if kib >= 1 else f"{total_bytes} bytes"
    return f"{summary} (retained output truncated)" if truncated else summary


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
) -> str:
    """Compose the follow-up agent's full prompt.

    ``starter_name`` set to ``None`` omits the ``#fork:`` prefix -- used when
    the starter did not settle to a terminal marker in time.
    """
    log_pointer = f"sase monitor show {monitor_id} --all-lines"
    rows = [
        ("Command", f"`{command}`"),
        ("Directory", f"`{cwd}`"),
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
            f"{_format_output_summary(total_bytes, output_truncated)} · "
            f"full log: `{log_pointer}`",
        ),
    ]
    table = "\n".join(f"| **{label}** | {value} |" for label, value in rows)

    tail = _tail_lines(output_text, tail_lines)
    fence = _widen_fence(tail)

    sections = [
        "# Monitored command finished",
        "",
        "| | |",
        "| --- | --- |",
        table,
        "",
        f"**Why this was monitored:** {reason}",
        "",
        f"## Last {tail_lines} lines of output",
        "",
        f"{fence}text",
        tail,
        fence,
        "",
        "## Your next action",
        "",
        next_action,
    ]
    body = "\n".join(sections)
    return f"#fork:{starter_name}\n\n{body}" if starter_name else body


__all__ = ["compose_followup_prompt"]
