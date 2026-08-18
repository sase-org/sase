"""MRU tracking for VCS xprompt workflow prefixes."""

import json
import logging
from pathlib import Path

from sase.core.paths import sase_home, sase_projects_dir

log = logging.getLogger(__name__)

_MRU_FILE: Path | None = None
_MAX_ENTRIES = 100


def vcs_xprompt_mru_path() -> Path:
    """Return the on-disk VCS xprompt MRU path.

    Honors the module-level ``_MRU_FILE`` test hook so isolated tests and
    the current-project peek share one override.
    """
    return _MRU_FILE or sase_home() / "vcs_xprompt_mru.json"


def _mru_file() -> Path:
    return vcs_xprompt_mru_path()


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

    Display-only convenience wrapper around
    :func:`load_launchable_vcs_xprompt_mru_pairs`; see that function for the
    pruning rules. Callers that also need the canonical (on-disk) form of
    each entry -- e.g. to build a ``history_sort_key`` -- should call the
    pairs accessor directly instead.
    """
    return [
        display
        for _, display in load_launchable_vcs_xprompt_mru_pairs(
            projects_dir, prune=prune
        )
    ]


def load_launchable_vcs_xprompt_mru_pairs(
    projects_dir: Path | None = None,
    *,
    prune: bool = True,
) -> list[tuple[str, str]]:
    """Load MRU prefixes as ``(canonical_prefix, display_prefix)`` pairs.

    Four classes of non-cyclable entry are pruned so ``<ctrl+p>`` only ever
    cycles to explicit refs that will actually launch (and so the
    unresolved-ref launch guard is never reachable through normal cycling):

    - the implicit default prefix (:func:`_is_default_vcs_xprompt_prefix`),
      which is normalized data rather than a user MRU choice,
    - prefixes for a known but non-launchable project
      (:func:`_is_stale_known_project_prefix`),
    - prefixes whose ref no longer resolves to any launch target at all
      (:func:`_vcs_prefix_ref_is_gone`), e.g. a ``#gh:<patch>`` whose
      Patch has since been submitted/archived, and
    - prefixes whose workflow tag no longer matches their project's actual
      provider (:func:`_vcs_prefix_provider_mismatched`), e.g. a stale
      ``#git:<gh-project>`` entry recorded before a project's spec was
      repaired back to its real provider.

    ``canonical_prefix`` is the on-disk directory-key form (the correct
    ``history_sort_key`` source); ``display_prefix`` is humanized to the
    configured project name (the correct prefill/label source -- users must
    never see a directory key). Deduping is keyed on the display form,
    first-wins, so this and :func:`load_launchable_vcs_xprompt_mru` can never
    disagree on ordering or length.
    """
    entries = _load_vcs_xprompt_mru()
    if not entries:
        return []

    # An explicit projects root is usually a test or alternate state root.
    # The global ref index is built from the default SASE home and can
    # confidently prune refs only for that default context.
    resolvable_refs = None if projects_dir is not None else _resolvable_vcs_ref_index()
    # Resolve alias/display-form prefixes to their canonical project before
    # pruning so they are judged by the real project rather than wrongly
    # dropped. Built once per call (reusing the index's map when available) so
    # the per-keystroke ``<ctrl+p>`` path never re-reads project records per
    # entry.
    alias_map = (
        resolvable_refs[2]
        if resolvable_refs is not None
        else _project_alias_map_or_empty(projects_dir)
    )
    filtered = [
        entry
        for entry in entries
        if not _is_default_vcs_xprompt_prefix(entry)
        and not _is_stale_known_project_prefix(entry, projects_dir, alias_map=alias_map)
        and not _vcs_prefix_ref_is_gone(entry, resolvable_refs)
        and not _vcs_prefix_provider_mismatched(entry, resolvable_refs)
    ]
    if prune and filtered != entries:
        _save_vcs_xprompt_mru(filtered)
    # Disk stays canonical (written above); the returned pairs' display half
    # is humanized to the configured project name and deduped in MRU order so
    # callers that render/cycle them never surface directory keys.
    return _dedupe_mru_pairs(filtered, projects_dir)


def record_vcs_xprompt_usage(prefix: str) -> None:
    """Move/add prefix to the front of the MRU list, cap at 100, save to disk.

    The implicit default prefix (e.g. ``#git:home``) is never recorded as a
    cyclable choice: launching a bare prompt normalizes to it, but it is the
    implicit fallback rather than an explicit selection. If a default entry is
    already present it is removed instead of re-added.

    The incoming prefix is canonicalized (alias/``PROJECT_NAME`` form ->
    directory key) before the default-prefix check and dedup/insert, so the
    on-disk MRU stays in canonical form and spelling variants of the same
    project collapse to one entry. (``home`` is excluded from the alias map, so
    the ``#git:home`` default handling is unaffected.)

    Args:
        prefix: VCS workflow prefix string (e.g. ``"#gh:sase"``).
    """
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prefix = canonicalize_project_aliases_in_prompt(prefix)
    entries = _load_vcs_xprompt_mru()
    if _is_default_vcs_xprompt_prefix(prefix):
        filtered = [e for e in entries if not _is_default_vcs_xprompt_prefix(e)]
        if filtered != entries:
            _save_vcs_xprompt_mru(filtered)
        return
    if _is_stale_known_project_prefix(prefix):
        filtered = [e for e in entries if e != prefix]
        if filtered != entries:
            _save_vcs_xprompt_mru(filtered)
        return
    if _vcs_prefix_provider_mismatched(prefix, _resolvable_vcs_ref_index()):
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


def _project_alias_map_or_empty(projects_dir: Path | None) -> dict[str, str]:
    """Return the ``alias/PROJECT_NAME -> directory key`` map, or ``{}`` on error.

    ``load_project_alias_map`` drops conflicting refs instead of raising, but
    an unreadable projects dir can still fail here; an empty map degrades
    pruning to today's canonical-only behavior instead of nuking the whole MRU.
    """
    try:
        from sase.project_aliases import load_project_alias_map

        return load_project_alias_map(projects_dir)
    except Exception:
        log.debug("VCS MRU alias map unavailable", exc_info=True)
        return {}


def _dedupe_mru_pairs(
    entries: list[str], projects_dir: Path | None
) -> list[tuple[str, str]]:
    """Pair each canonical entry with its humanized display form.

    Deduped on the display form, first-wins, in MRU order.
    """
    from sase.project_display_names import humanize_vcs_refs_in_text

    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for entry in entries:
        display = humanize_vcs_refs_in_text(entry, projects_dir)
        if display not in seen:
            seen.add(display)
            pairs.append((entry, display))
    return pairs


def _is_default_vcs_xprompt_prefix(prefix: str) -> bool:
    """Return whether *prefix* is the implicit default workflow prefix.

    The bare-prompt default (``#git:home``) is normalized data, not a user
    selection, so it must never appear as a cyclable MRU candidate, a recorded
    MRU entry, or a saved ``Ctrl+Space`` replay target even when an earlier
    launch persisted it. Underscore refs are normalized on both sides so legacy
    spellings (e.g. ``#git_home``) compare equal to the default.
    """
    from sase.xprompt._parsing import (
        DEFAULT_VCS_WORKFLOW_PREFIX,
        normalize_vcs_underscore_refs,
    )

    return normalize_vcs_underscore_refs(
        prefix.strip()
    ) == normalize_vcs_underscore_refs(DEFAULT_VCS_WORKFLOW_PREFIX)


def _is_stale_known_project_prefix(
    prefix: str,
    projects_dir: Path | None = None,
    *,
    alias_map: dict[str, str] | None = None,
) -> bool:
    project_name = _project_name_from_vcs_prefix(prefix)
    if project_name is None:
        return False

    projects_base = projects_dir or sase_projects_dir()
    # Resolve an alias/display-form ref (e.g. ``#gh:widgets``) to its directory
    # key so the spec-path and launchability checks below judge the real
    # project instead of short-circuiting on a nonexistent ``widgets/`` dir.
    if alias_map is None:
        alias_map = _project_alias_map_or_empty(projects_base)
    project_name = alias_map.get(project_name, project_name)

    from sase.ace.patch.project_spec_path import preferred_project_spec_path

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


def _resolvable_vcs_ref_index() -> (
    tuple[dict[str, Path], set[str], dict[str, str]] | None
):
    """Snapshot the offline data needed to judge ref resolvability.

    Returns ``(known_projects, active_patch_names, alias_map)`` computed
    once per load (cheap, cached, offline), or ``None`` when the snapshot can't
    be built — in which case callers keep every entry rather than risk nuking
    the MRU on a transient error. ``alias_map`` maps alias/``PROJECT_NAME`` refs
    to their directory key so display-form entries resolve without a per-entry
    project-records read.
    """
    try:
        from sase.ace.patch.cache import find_all_patches_cached
        from sase.xprompt.loader import get_known_project_workspaces

        known_projects = get_known_project_workspaces()
        patch_names = {patch.name for patch in find_all_patches_cached()}
        alias_map = _project_alias_map_or_empty(None)
        return known_projects, patch_names, alias_map
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
    index: tuple[dict[str, Path], set[str], dict[str, str]] | None,
) -> bool:
    """Return whether *prefix*'s ref no longer resolves to any launch target.

    Side-effect-free and offline. It mirrors the read-only resolution modes
    the workspace providers use (known-project shorthand + active Patch
    name) WITHOUT calling ``resolve_ref`` itself: the bare-git provider's
    resolve path *creates* a project for a missing shorthand, so invoking it
    here (on every ``<ctrl+p>``) would resurrect the very stale entries we
    want to prune.

    Returns ``True`` only when the ref is confidently gone. Structural,
    path/owner-repo, unregistered, or snapshot-unavailable cases all keep the
    entry.
    """
    if index is None:
        return False
    try:
        parsed = _workflow_and_ref_for_prefix(prefix)
        if parsed is None:
            return False
        workflow_type, ref = parsed

        if "/" in ref or ref.startswith("~") or ref == "home":
            return False

        known_projects, patch_names, alias_map = index
        # Resolve an alias/display-form ref (e.g. ``#gh:widgets``) to its
        # directory key so it is judged by its real project and not wrongly
        # pruned as gone. Canonical refs pass through unchanged.
        canonical_ref = alias_map.get(ref, ref)

        from sase.xprompt._parsing import resolve_known_project_ref

        if resolve_known_project_ref(canonical_ref, known_projects) is not None:
            return False
        return canonical_ref not in patch_names
    except Exception:
        log.debug("VCS MRU resolvability check failed for %r", prefix, exc_info=True)
        return False


def _vcs_prefix_provider_mismatched(
    prefix: str,
    index: tuple[dict[str, Path], set[str], dict[str, str]] | None,
) -> bool:
    """Return whether *prefix*'s workflow tag mismatches its project's real provider.

    Offline and side-effect-free like :func:`_vcs_prefix_ref_is_gone`: it
    reads the resolved project's spec file to detect its actual provider via
    :func:`~sase.workspace_provider.detect_workflow_type` instead of calling
    ``resolve_ref``, so cycling or recording an MRU entry never creates or
    mutates a project.

    Returns ``True`` only when a provider is confidently detected and differs
    from the tag's workflow type. Structural, unresolvable, unregistered, or
    error cases all keep the entry.
    """
    if index is None:
        return False
    try:
        parsed = _workflow_and_ref_for_prefix(prefix)
        if parsed is None:
            return False
        workflow_type, ref = parsed

        if "/" in ref or ref.startswith("~") or ref == "home":
            return False

        known_projects, _patch_names, alias_map = index
        canonical_ref = alias_map.get(ref, ref)

        from sase.xprompt._parsing import resolve_known_project_ref

        project_name = resolve_known_project_ref(canonical_ref, known_projects)
        if project_name is None:
            return False

        from sase.ace.patch.project_spec_path import preferred_project_spec_path
        from sase.workspace_provider import detect_workflow_type

        project_dir = sase_projects_dir() / project_name
        project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
        if not project_file.is_file():
            return False

        actual_workflow_type = detect_workflow_type(str(project_file))
        return actual_workflow_type != workflow_type
    except Exception:
        log.debug(
            "VCS MRU provider-mismatch check failed for %r", prefix, exc_info=True
        )
        return False
