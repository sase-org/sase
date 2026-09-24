"""Lightweight plan-name helpers shared by the CLI and completion.

This module owns the proposal **name** (an archive file stem such as
``unrelated_red_gate_bead_close``), its shortest-unique display form, and
selector normalization. It imports only the stdlib and
:mod:`sase.core.paths` so the completion fast path can import it without
pulling ``rich``, ``sase.ace``, ``sase.notifications``, or ``sase.sdd``.
"""

from __future__ import annotations

from pathlib import Path

_PLAN_REFERENCE_PREFIX = "plan:"
_LEGACY_PLANS_PREFIX = "plans:"


def plan_name(path: str | Path) -> str:
    """Return the proposal name for an archive or bundle plan path."""
    return Path(str(path)).name.removesuffix(".md")


def normalize_selector(raw: str) -> str:
    """Normalize a user-supplied selector for name/ref comparison."""
    normalized = raw.strip()
    lowered = normalized.lower()
    if lowered.startswith(_PLAN_REFERENCE_PREFIX):
        normalized = normalized[len(_PLAN_REFERENCE_PREFIX) :]
    elif lowered.startswith(_LEGACY_PLANS_PREFIX):
        normalized = normalized[len(_LEGACY_PLANS_PREFIX) :]
    normalized = normalized.strip().removeprefix("./")
    if normalized.lower().endswith(".md"):
        normalized = normalized[: -len(".md")]
    return normalized


def plan_display_names(paths: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Map each path to its shortest unique display form.

    The display form is the bare name, then ``<shard>/<name>`` on collision,
    then the full path as a final fallback.
    """
    names = [plan_name(path) for path in paths]
    shards = [_plan_shard(path) for path in paths]
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    display: dict[str, str] = {}
    for path, name, shard in zip(paths, names, shards, strict=True):
        if counts[name] == 1:
            display[path] = name
            continue
        if shard:
            candidate = f"{shard}/{name}"
        else:
            candidate = name
        display[path] = candidate
    # Resolve any remaining shard-level collisions with the full path.
    seen: dict[str, str] = {}
    for path in paths:
        candidate = display[path]
        if candidate in seen:
            display[path] = path
            display[seen[candidate]] = seen[candidate]
        else:
            seen[candidate] = path
    return display


def _plan_shard(path: str) -> str:
    """Return the ``YYYYMM`` shard directory name for *path*, if any."""
    parts = Path(str(path)).parts
    if len(parts) >= 2:
        parent = parts[-2]
        if len(parent) == 6 and parent.isdigit():
            return parent
    return ""
