"""Auto-naming sequence and active-agent reservation logic.

The auto sequence (``0, 1, ..., 9, a, ..., z, 00, 01, ...``) plus
child-name reservation that backs ``%r:N`` repeat batches.
"""

import json
import re
from sase.agent.names._common import (
    extract_auto_name_prefix,
    is_process_alive,
)
from sase.agent.names._registry import get_reserved_agent_names
from sase.agent.names._templates import allocate_agent_name_template
from sase.core.paths import sase_projects_dir


def get_next_auto_name() -> str:
    """Return the lowest available permanent auto-generated agent name.

    Uses the durable name registry so every existing agent state keeps its
    slot reserved until the agent is explicitly wiped/deleted.
    """
    return allocate_agent_name_template("@")


def allocate_auto_names(count: int, *, reserved: set[str] | None = None) -> list[str]:
    """Allocate *count* auto names from one active-name snapshot."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    used = get_reserved_agent_names() if reserved is None else reserved
    names: list[str] = []
    for _ in range(count):
        name = allocate_agent_name_template("@", reserved=used)
        names.append(name)
    return names


def get_active_agent_names() -> set[str]:
    """Return the set of names reserved by visible, non-dismissed agents.

    This legacy visible-agent snapshot is kept for retry/repeat collision
    checks. Permanent auto-name allocation uses the durable registry instead.
    """
    projects_dir = sase_projects_dir()
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


def get_active_agent_name_map() -> dict[str, str]:
    """Return ``{name: artifact_dir}`` for visible, non-dismissed agents.

    Sibling of :func:`get_active_agent_names` keyed on full claimed names
    (``name`` and ``workflow_name``) with the owning artifact directory as
    the value, so collision diagnostics can point the user at the offending
    agent. Auto-name prefixes are not included.
    """
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return {}

    dismissed_suffixes = _load_dismissed_suffixes()
    name_map: dict[str, str] = {}
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

            done_path = artifact_dir / "done.json"
            is_done = done_path.exists()
            if not is_done and not is_process_alive(data, artifact_dir):
                continue

            for value in (data.get("name"), data.get("workflow_name")):
                if isinstance(value, str) and value:
                    name_map.setdefault(value, str(artifact_dir))

    return name_map


def get_live_agent_name_map() -> dict[str, str]:
    """Return ``{name: artifact_dir}`` for live, non-dismissed agents only.

    Unlike :func:`get_active_agent_name_map`, terminal done agents do not
    reserve names here. This is for workflows that can intentionally retry a
    completed or failed historical name but must not duplicate a running agent.
    """
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return {}

    dismissed_suffixes = _load_dismissed_suffixes()
    name_map: dict[str, str] = {}
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

            if (artifact_dir / "done.json").exists():
                continue
            if not is_process_alive(data, artifact_dir):
                continue

            for value in (data.get("name"), data.get("workflow_name")):
                if isinstance(value, str) and value:
                    name_map.setdefault(value, str(artifact_dir))

    return name_map


def get_live_agent_name_subset(expected_names: set[str]) -> dict[str, str]:
    """Return live name collisions for a small expected-name set.

    The full live-name map is useful for broad diagnostics. Bead work already
    knows the exact names it wants, so this path avoids liveness checks until a
    metadata file names one of those agents and stops once every expected name
    has been found.
    """
    remaining = set(expected_names)
    if not remaining:
        return {}

    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return {}

    dismissed_suffixes = _load_dismissed_suffixes()
    name_map: dict[str, str] = {}
    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return {}

    for project_dir in project_iter:
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        try:
            artifact_iter = ace_run_dir.iterdir()
        except OSError:
            continue

        for artifact_dir in artifact_iter:
            if not artifact_dir.is_dir():
                continue
            if artifact_dir.name in dismissed_suffixes:
                continue
            if (artifact_dir / "done.json").exists():
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

            names = {
                value
                for value in (data.get("name"), data.get("workflow_name"))
                if isinstance(value, str) and value in remaining
            }
            if not names:
                continue
            if not is_process_alive(data, artifact_dir):
                continue

            for name in names:
                name_map.setdefault(name, str(artifact_dir))
                remaining.discard(name)
            if not remaining:
                return name_map

    return name_map


def _load_dismissed_suffixes() -> set[str]:
    """Return dismissed raw suffixes, ignoring load/import errors."""
    try:
        from sase.ace.dismissed_agents import load_dismissed_agents

        dismissed = load_dismissed_agents()
    except Exception:
        return set()

    return {raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None}


def get_active_child_names(base: str) -> set[str]:
    """Return the set of active agent names matching ``<base>.<digits>``.

    Walks the same artifact tree as :func:`get_active_agent_names` but keys
    on each agent's ``name`` field (not its ``workflow_name``), so callers
    can detect collisions for individual repeat slots like ``sase-z.2``.
    """
    projects_dir = sase_projects_dir()
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
