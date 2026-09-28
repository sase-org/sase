"""Run-block jump targets and hint labels for run-links."""

from __future__ import annotations

from typing import Any

__all__ = [
    "TOOLRUN_JUMP_TARGET_PREFIX",
    "run_id_from_jump_target",
    "run_jump_hint_label",
    "tool_run_jump_target",
    "visible_tool_run_jump_targets",
]

#: Pseudo-target prefix for run-block jumps (never a real path). Mirrors
#: the ``toolrun-log:`` scheme in
#: :mod:`sase.ace.tui.tool_runs.hints`; the suffix click handler and
#: ``v`` hint mode both resolve through it.
TOOLRUN_JUMP_TARGET_PREFIX = "toolrun-jump:"


def tool_run_jump_target(run_id: str) -> str | None:
    """Return the ``toolrun-jump:<run_id>`` target, or None when blank."""

    clean = str(run_id or "").strip()
    if not clean:
        return None
    return f"{TOOLRUN_JUMP_TARGET_PREFIX}{clean}"


def run_id_from_jump_target(target: str) -> str | None:
    """Return the run id carried by a ``toolrun-jump:`` target, if any."""

    if not isinstance(target, str):
        return None
    if not target.startswith(TOOLRUN_JUMP_TARGET_PREFIX):
        return None
    run_id = target[len(TOOLRUN_JUMP_TARGET_PREFIX) :].strip()
    return run_id or None


def run_jump_hint_label(run_id: str) -> str:
    """Return the ``⚒ run <8hex>`` hint label for one run."""

    return f"⚒ run {str(run_id or '')[:8]}"


def visible_tool_run_jump_targets(
    runs: Any,
) -> list[tuple[str, str]]:
    """Return ``(label, target)`` jump pairs for *runs* in order."""

    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for run in runs or ():
        run_id = str(getattr(run, "run_id", "") or "").strip()
        if not run_id or run_id in seen:
            continue
        target = tool_run_jump_target(run_id)
        if target is None:
            continue
        seen.add(run_id)
        entries.append((run_jump_hint_label(run_id), target))
    return entries
