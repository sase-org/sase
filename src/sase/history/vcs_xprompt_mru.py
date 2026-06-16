"""MRU tracking for VCS xprompt workflow prefixes."""

import json
import logging
from pathlib import Path

from sase.core.paths import sase_home, sase_projects_dir

log = logging.getLogger(__name__)

_MRU_FILE: Path | None = None
_MAX_ENTRIES = 100


def _mru_file() -> Path:
    return _MRU_FILE or sase_home() / "vcs_xprompt_mru.json"


def _load_vcs_xprompt_mru() -> list[str]:
    """Load the MRU list from disk.

    Returns:
        Ordered list of VCS prefix strings, most recently used first.
    """
    mru_file = _mru_file()
    if not mru_file.exists():
        return []
    try:
        with open(mru_file, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return [e for e in entries if isinstance(e, str)][:_MAX_ENTRIES]
    except (OSError, json.JSONDecodeError):
        return []


def load_launchable_vcs_xprompt_mru(
    projects_dir: Path | None = None,
    *,
    prune: bool = True,
) -> list[str]:
    """Load MRU prefixes, dropping entries that would no longer launch.

    Two classes of stale entry are pruned so ``<ctrl+p>`` only ever cycles to
    refs that will actually launch (and so the unresolved-ref launch guard is
    never reachable through normal cycling):

    - prefixes for a known but non-launchable project
      (:func:`_is_stale_known_project_prefix`), and
    - prefixes whose ref no longer resolves to any launch target at all
      (:func:`_vcs_prefix_ref_is_gone`), e.g. a ``#gh:<changespec>`` whose
      ChangeSpec has since been submitted/archived.
    """
    entries = _load_vcs_xprompt_mru()
    if not entries:
        return entries

    # An explicit projects root is usually a test or alternate state root.
    # The global ref index is built from the default SASE home and can
    # confidently prune refs only for that default context.
    resolvable_refs = None if projects_dir is not None else _resolvable_vcs_ref_index()
    filtered = [
        entry
        for entry in entries
        if not _is_stale_known_project_prefix(entry, projects_dir)
        and not _vcs_prefix_ref_is_gone(entry, resolvable_refs)
    ]
    if prune and filtered != entries:
        _save_vcs_xprompt_mru(filtered)
    return filtered


def record_vcs_xprompt_usage(prefix: str) -> None:
    """Move/add prefix to the front of the MRU list, cap at 100, save to disk.

    Args:
        prefix: VCS workflow prefix string (e.g. ``"#gh:sase"``).
    """
    entries = _load_vcs_xprompt_mru()
    if _is_stale_known_project_prefix(prefix):
        filtered = [e for e in entries if e != prefix]
        if filtered != entries:
            _save_vcs_xprompt_mru(filtered)
        return

    entries = [e for e in entries if e != prefix]
    entries.insert(0, prefix)
    entries = entries[:_MAX_ENTRIES]
    _save_vcs_xprompt_mru(entries)


def _save_vcs_xprompt_mru(entries: list[str]) -> None:
    try:
        mru_file = _mru_file()
        mru_file.parent.mkdir(parents=True, exist_ok=True)
        with open(mru_file, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, indent=2)
    except OSError:
        pass


def _is_stale_known_project_prefix(
    prefix: str,
    projects_dir: Path | None = None,
) -> bool:
    project_name = _project_name_from_vcs_prefix(prefix)
    if project_name is None:
        return False

    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    projects_base = projects_dir or sase_projects_dir()
    project_file = Path(
        preferred_project_spec_path(str(projects_base / project_name), project_name)
    )
    if not project_file.is_file():
        return False

    from sase.ace.tui.modals.project_discovery import is_launchable_project

    return not is_launchable_project(project_name, projects_base)


def _project_name_from_vcs_prefix(prefix: str) -> str | None:
    from sase.xprompt._parsing import extract_project_from_vcs_tag

    return extract_project_from_vcs_tag(prefix)


def _resolvable_vcs_ref_index() -> tuple[dict[str, Path], set[str]] | None:
    """Snapshot the offline data needed to judge ref resolvability.

    Returns ``(known_projects, active_changespec_names)`` computed once per
    load (cheap, cached, offline), or ``None`` when the snapshot can't be
    built — in which case callers keep every entry rather than risk nuking the
    MRU on a transient error.
    """
    try:
        from sase.ace.changespec.cache import find_all_changespecs_cached
        from sase.xprompt.loader import get_known_project_workspaces

        known_projects = get_known_project_workspaces()
        changespec_names = {cs.name for cs in find_all_changespecs_cached()}
        return known_projects, changespec_names
    except Exception:
        log.debug("VCS MRU resolvability index unavailable", exc_info=True)
        return None


def _workflow_and_ref_for_prefix(prefix: str) -> tuple[str, str] | None:
    """Return ``(workflow_type, ref)`` for *prefix* using registered patterns.

    Only refs for a currently-registered workflow provider match; an
    unrecognized/unregistered tag (e.g. ``#gh`` when the GitHub plugin is not
    loaded) returns ``None`` so the entry is left untouched.
    """
    from sase.workspace_provider import get_ref_patterns

    text = prefix.strip() + " "
    for workflow_type, pattern in get_ref_patterns().items():
        match = pattern.search(text)
        if match is not None:
            ref = match.group(1) or match.group(2)
            if ref:
                return (workflow_type, ref)
    return None


def _vcs_prefix_ref_is_gone(
    prefix: str,
    index: tuple[dict[str, Path], set[str]] | None,
) -> bool:
    """Return whether *prefix*'s ref no longer resolves to any launch target.

    Side-effect-free and offline. It mirrors the read-only resolution modes
    the workspace providers use (known-project shorthand + active ChangeSpec
    name) WITHOUT calling ``resolve_ref`` itself: the bare-git provider's
    resolve path *creates* a project for a missing shorthand, so invoking it
    here (on every ``<ctrl+p>``) would resurrect the very stale entries we
    want to prune.

    Returns ``True`` only when the ref is confidently gone. Structural,
    path/owner-repo, non-workspace (``#cd``), unregistered, or
    snapshot-unavailable cases all keep the entry.
    """
    if index is None:
        return False
    try:
        parsed = _workflow_and_ref_for_prefix(prefix)
        if parsed is None:
            return False
        workflow_type, ref = parsed

        from sase.ace.tui.actions.agent_workflow._ref_resolution import (
            is_non_workspace_workflow,
        )

        if is_non_workspace_workflow(workflow_type):
            return False
        if "/" in ref or ref.startswith("~") or ref == "home":
            return False

        known_projects, changespec_names = index

        from sase.xprompt._parsing import resolve_known_project_ref

        if resolve_known_project_ref(ref, known_projects) is not None:
            return False
        return ref not in changespec_names
    except Exception:
        log.debug("VCS MRU resolvability check failed for %r", prefix, exc_info=True)
        return False
