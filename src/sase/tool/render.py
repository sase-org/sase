"""Human rendering helpers for ``sase tool`` list/runs/show."""

from __future__ import annotations

from typing import Any


EMPTY = "—"


def format_state(run: object) -> str:
    """Render LAST-style ``state`` or ``state/exit``."""

    if not isinstance(run, dict):
        return EMPTY
    state = str(run.get("state") or "").strip()
    if not state:
        return EMPTY
    exit_code = run.get("exit_code")
    if exit_code is not None and state in {"failed", "signaled", "interrupted"}:
        return f"{state}/{exit_code}"
    return state


def format_typical(duration_ms: object, sample_count: int) -> str:
    if duration_ms is None or sample_count <= 0:
        return EMPTY
    if type(duration_ms) is not int:
        return EMPTY
    return f"{format_duration_ms(duration_ms)} (n={sample_count})"


def format_duration_ms(duration_ms: int | None) -> str:
    if duration_ms is None:
        return EMPTY
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000
    if seconds < 60:
        if seconds == int(seconds):
            return f"{int(seconds)}s"
        return f"{seconds:.1f}s"
    minutes, rem = divmod(int(seconds), 60)
    if rem == 0:
        return f"{minutes}m"
    return f"{minutes}m {rem}s"


def format_argv(run: dict[str, Any]) -> str:
    argv = run.get("display_argv") or ()
    if not argv:
        return EMPTY
    return " ".join(str(part) for part in argv)


def format_tool_name(run: dict[str, Any]) -> str:
    name = run.get("tool_name")
    if name:
        return str(name)
    return "(ad-hoc)"


__all__ = [
    "EMPTY",
    "format_argv",
    "format_duration_ms",
    "format_state",
    "format_tool_name",
    "format_typical",
]
