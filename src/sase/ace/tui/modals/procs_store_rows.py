"""Durable task-store operations for the Admin Center Tasks tab."""

from __future__ import annotations

from sase.procs import kill_proc


def kill_store_task(proc_id: str) -> str | None:
    """Kill a store-backed task, returning an error message on failure."""
    try:
        kill_proc(proc_id)
    except Exception as exc:
        return " ".join(str(exc).splitlines()) or type(exc).__name__
    return None


__all__ = ["kill_store_task"]
