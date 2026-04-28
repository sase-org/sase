"""Auto-naming sequence and active-agent reservation logic.

The auto sequence (``a, b, ..., z, aa, ab, ...``) plus child-name reservation
that backs ``%r:N`` repeat batches and revive-time name allocation.
"""

import itertools
import json
import re
import string
from collections.abc import Iterator
from pathlib import Path

from sase.agent.names._common import (
    extract_auto_name_prefix,
    is_process_alive,
    strip_dismissed_prefix,
)


def get_next_auto_name() -> str:
    """Return the lowest available alphabetic agent name.

    Scans visible, non-dismissed agents across all projects and returns the
    first name in the sequence ``a, b, ..., z, aa, ab, ...`` that is not
    currently in use. Completed agents keep reserving their slot until
    dismissed because they remain visible on the Agents tab.
    """
    used = get_active_agent_names()
    return _next_available_name(used)


def get_active_agent_names() -> set[str]:
    """Return the set of names reserved by visible, non-dismissed agents.

    Names of running or done agents are reserved so a fresh auto-named
    agent does not collide with entries that still appear on the Agents
    tab. Dismissed agents (or deleted artifact dirs) and dead non-done
    agents do not block reuse — their slots are released.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return set()

    dismissed_suffixes = _load_dismissed_suffixes()
    names: set[str] = set()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue
            if artifact_dir.name in dismissed_suffixes:
                continue

            meta_path = artifact_dir / "agent_meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            # Prefer workflow_name for multi-agent workflows so the
            # base name (e.g. "a") is reserved, not the child name ("a.1").
            name_field = data.get("name")
            workflow_name_field = data.get("workflow_name")
            name = workflow_name_field or name_field
            if not name:
                continue

            # Any active agent whose name (or workflow name) starts with
            # ``<base>.`` reserves the auto-name slot ``<base>``: a fresh
            # ``m`` agent next to ``m.claude.plan`` would visually collide on
            # the Agents tab and become ambiguous when typing ``@m`` in
            # prompts. This also covers the legacy repeat-batch case where
            # ``<letter>.<digits>`` reserves ``<letter>``.
            prefix = extract_auto_name_prefix(name_field, workflow_name_field)

            done_path = artifact_dir / "done.json"
            is_done = done_path.exists()

            # Non-done artifacts only reserve a name while their process is
            # actually alive. Done artifacts do not need a live PID because
            # dismissal controls their visible lifecycle.
            if not is_done and not is_process_alive(data, artifact_dir):
                continue

            # Follow-up agents (coder/epic steps spawned after plan
            # approval) share their parent's name and are sub-steps of
            # the parent workflow — they should not independently
            # reserve their full name. They still reserve the auto-name
            # prefix while live so a fresh ``<base>`` agent does not
            # collide with them.
            if data.get("parent_timestamp"):
                if prefix is not None:
                    names.add(prefix)
                continue

            names.add(name)
            if prefix is not None:
                names.add(prefix)

    return names


def _load_dismissed_suffixes() -> set[str]:
    """Return dismissed raw suffixes, ignoring load/import errors."""
    try:
        from sase.ace.dismissed_agents import load_dismissed_agents

        dismissed = load_dismissed_agents()
    except Exception:
        return set()

    return {raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None}


def _name_sequence() -> Iterator[str]:
    """Yield alphabetic names: a, b, ..., z, aa, ab, ..."""
    length = 1
    while True:
        for combo in itertools.product(string.ascii_lowercase, repeat=length):
            yield "".join(combo)
        length += 1


def _next_available_name(used: set[str]) -> str:
    """Return the first name from the alphabetic sequence not in *used*."""
    for name in _name_sequence():
        if name not in used:
            return name
    # Unreachable — infinite generator
    raise AssertionError("unreachable")


def get_active_child_names(base: str) -> set[str]:
    """Return the set of active agent names matching ``<base>.<digits>``.

    Walks the same artifact tree as :func:`get_active_agent_names` but keys
    on each agent's ``name`` field (not its ``workflow_name``), so callers
    can detect collisions for individual repeat slots like ``sase-z.2``.
    """
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return set()

    dismissed_suffixes = _load_dismissed_suffixes()
    pattern = re.compile(rf"^{re.escape(base)}\.\d+$")
    names: set[str] = set()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue
            if artifact_dir.name in dismissed_suffixes:
                continue

            meta_path = artifact_dir / "agent_meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            name = data.get("name")
            if not isinstance(name, str) or not pattern.match(name):
                continue

            done_path = artifact_dir / "done.json"
            if done_path.exists():
                names.add(name)
                continue

            if is_process_alive(data, artifact_dir):
                names.add(name)

    return names


def dedup_name(base: str, reserved: set[str]) -> str:
    """Return *base* if free, else the lowest ``<base>.<n>`` (n >= 2) not in *reserved*.

    Mutates *reserved* in place with the chosen name so callers can chain
    allocations across a batch (mirrors :func:`allocate_revived_name`'s
    ``reserved`` contract).
    """
    if base not in reserved:
        reserved.add(base)
        return base
    n = 2
    while True:
        candidate = f"{base}.{n}"
        if candidate not in reserved:
            reserved.add(candidate)
            return candidate
        n += 1


def allocate_revived_name(
    prefixed_name: str,
    *,
    reserved: set[str] | None = None,
) -> tuple[str, str | None]:
    """Allocate the live name for *prefixed_name* on revive.

    Strips the ``YYmmdd.`` prefix from *prefixed_name*. When the stripped
    name is already claimed (by *reserved* or, when ``None``, by the
    current active-agent set), falls back to ``<base>.<n>`` via
    :func:`dedup_name` and returns the originally requested name as the
    second tuple element so the caller can surface "original name was
    taken" feedback. When the stripped name is free the second element
    is ``None``.

    *reserved* is mutated in place with the allocated name so a caller
    can chain allocations across a batch revive without re-scanning.
    """
    candidate = strip_dismissed_prefix(prefixed_name)
    pool = get_active_agent_names() if reserved is None else reserved
    fallback: str | None = None
    if candidate in pool:
        fallback = candidate
        candidate = dedup_name(candidate, pool)
    else:
        pool.add(candidate)
    return candidate, fallback
