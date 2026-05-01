"""Enforce agent-name uniqueness across artifact directories."""

import json
from pathlib import Path

from sase.plan_chain import plan_chain_suffix_from_meta


def claim_agent_name(name: str, claiming_dir: str, *, explicit: bool = False) -> None:
    """Enforce agent name uniqueness.

    When ``explicit`` is ``False`` (default; auto-named flows): scans
    ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`` and
    removes the ``"name"`` field from any non-done file that carries
    *name* but does **not** live in *claiming_dir*. Done agents are
    skipped — they need their identity for ``#resume`` and historical
    lookups.

    When ``explicit`` is ``True`` (the launching agent typed
    ``%name:<name>``): renames the colliding agent — running OR done —
    by appending ``.2``, ``.3``, ... so the launching agent keeps the
    requested name and the existing agent stays visible on the Agents
    tab under a dedup'd name. Wait/resume references in other agents'
    on-disk markers are rewritten via
    :func:`sase.agent.dismissed_name_rewrites.rewrite_dismissed_references`
    so historical pointers follow the rename.

    All I/O errors are silently caught (best-effort: name reservation
    must never block agent launch).

    Args:
        name: The agent name being claimed.
        claiming_dir: Absolute path of the artifact directory that owns
            the name now.
        explicit: True iff the caller is honoring an explicit
            ``%name:<name>`` user directive.
    """
    if explicit:
        _claim_explicit(name, claiming_dir)
    else:
        _claim_strip(name, claiming_dir)


def _claim_strip(name: str, claiming_dir: str) -> None:
    """Auto-name path: strip stale ``name`` fields from non-done collisions."""
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    claiming = Path(claiming_dir).resolve()

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        ace_run_dir = project_dir / "artifacts" / "ace-run"
        if not ace_run_dir.exists():
            continue

        for artifact_dir in ace_run_dir.iterdir():
            if not artifact_dir.is_dir():
                continue

            if artifact_dir.resolve() == claiming:
                continue

            # Don't strip names from completed agents — they need their
            # identity for #resume and historical lookups.
            if (artifact_dir / "done.json").exists():
                continue

            # Strip name from agent_meta.json
            _strip_name_from_json(artifact_dir / "agent_meta.json", name)
            # Strip name from done.json too
            _strip_name_from_json(artifact_dir / "done.json", name)


def _claim_explicit(name: str, claiming_dir: str) -> None:
    """Explicit-claim path: rename colliding agents to ``<name>.<n>``."""
    from sase.agent.names._auto import dedup_name, get_active_agent_names

    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.exists():
        return

    claiming = Path(claiming_dir).resolve()

    dismissed_suffixes = _load_dismissed_suffixes()

    # The claimer owns *name*; mark it reserved so colliding agents are
    # renamed to ``<name>.2``, ``<name>.3``, ... (and never reuse the
    # base name itself). The claimer's own ``agent_meta.json`` was just
    # written so ``get_active_agent_names`` typically already lists
    # *name* — the explicit ``add`` is defensive against ordering churn.
    reserved = get_active_agent_names()
    reserved.add(name)

    name_map: dict[str, str] = {}
    workflow_renames: dict[str, str] = {}

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
            try:
                if artifact_dir.resolve() == claiming:
                    continue
            except OSError:
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

            matched_name = data.get("name") == name
            matched_workflow = data.get("workflow_name") == name
            if not (matched_name or matched_workflow):
                continue

            if matched_workflow:
                new_name = workflow_renames.get(name)
                if new_name is None:
                    new_name = dedup_name(name, reserved)
                    workflow_renames[name] = new_name
            else:
                new_name = dedup_name(name, reserved)
            try:
                if matched_name:
                    data["name"] = new_name
                if matched_workflow:
                    data["workflow_name"] = new_name
                    # When workflow_name matched, the agent's own name is
                    # derived from the workflow. Rewrite exact root names and
                    # independent plan-chain phase names such as
                    # ``foo.plan`` / ``foo.coder`` to keep the renamed chain
                    # under one prefix.
                    if data.get("name") == name:
                        data["name"] = new_name
                    else:
                        _rewrite_plan_chain_name_prefix(data, name, new_name)
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except (OSError, KeyError):
                continue

            # Mirror the rewrite into done.json's name field if present.
            done_path = artifact_dir / "done.json"
            if done_path.exists():
                _rename_in_done_json(done_path, name, new_name)

            name_map[name] = new_name

    if name_map:
        try:
            from sase.agent.dismissed_name_rewrites import (
                rewrite_dismissed_references,
            )

            rewrite_dismissed_references(name_map)
        except Exception:
            pass


def _rewrite_plan_chain_name_prefix(
    data: dict[str, object],
    old_prefix: str,
    new_prefix: str,
) -> bool:
    """Rewrite ``name`` from ``old_prefix.<phase>`` to ``new_prefix.<phase>``."""
    current = data.get("name")
    if not isinstance(current, str):
        return False
    suffix = current[len(old_prefix) :] if current.startswith(old_prefix) else ""
    if not suffix or not isinstance(data.get("workflow_name"), str):
        return False
    if plan_chain_suffix_from_meta({**data, "role_suffix": suffix}) is None:
        return False
    data["name"] = f"{new_prefix}{suffix}"
    return True


def _rename_in_done_json(path: Path, old: str, new: str) -> None:
    """Rewrite ``name``/``workflow_name`` fields in *path* from *old* to *new*."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        changed = False
        if data.get("name") == old:
            data["name"] = new
            changed = True
        if data.get("workflow_name") == old:
            data["workflow_name"] = new
            changed = True
            if _rewrite_plan_chain_name_prefix(data, old, new):
                changed = True
        if not changed:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass


def _load_dismissed_suffixes() -> set[str]:
    """Return dismissed raw suffixes, ignoring load/import errors."""
    try:
        from sase.ace.dismissed_agents import load_dismissed_agents

        dismissed = load_dismissed_agents()
    except Exception:
        return set()

    return {raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None}


def _strip_name_from_json(path: Path, name: str) -> None:
    """Remove name-related keys from a JSON file if ``name`` or ``workflow_name`` matches.

    When ``workflow_name`` matches, both ``name`` and ``workflow_name`` are
    stripped since the child agent's name is derived from the workflow name.
    """
    try:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        changed = False
        if data.get("name") == name:
            del data["name"]
            changed = True
        if data.get("workflow_name") == name:
            data.pop("name", None)
            del data["workflow_name"]
            changed = True
        if not changed:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError, KeyError):
        pass
