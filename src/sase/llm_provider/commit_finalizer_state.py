"""Dirty repository discovery for commit finalization."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
from pathlib import Path

from sase.commit_instructions import build_commit_details
from sase.linked_repos import (
    HIDDEN_SIDECAR_ROLES,
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    linked_repo_metadata_from_env,
    is_legacy_static_linked_repo_record,
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_workspace_dirs,
)

from . import commit_finalizer_git as finalizer_git
from .commit_finalizer_baseline import DirtyBaseline, load_dirty_baseline
from .commit_finalizer_git import (
    filter_sase_reserved_paths,
    git_changed_files,
    is_prompt_archive_path,
    split_pre_existing_changed_files,
)
from .commit_finalizer_prompting import build_dirty_details, build_pre_existing_details
from .commit_finalizer_types import (
    BaselineRepo,
    DirtyRepo,
    DirtyState,
    SiblingTarget,
)

_logger = logging.getLogger(__name__)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)
_BASELINE_CHECKOUT_SCAN_LIMIT = 128
_BASELINE_CHECKOUT_SCAN_MAX_DEPTH = 5

# Precedence when the same repo path is reached through more than one
# discovery source (e.g. a configured sibling that is also an SDD sidecar
# target): the more specific kind wins, since the machine auto-commit and
# prompt-rendering paths key off ``kind``.
_DIRTY_REPO_KIND_PRIORITY: dict[str, int] = {
    "main": 0,
    "sdd": 1,
    "external": 2,
    "sibling": 3,
}


def collect_baseline_repositories(project_dir: str) -> tuple[BaselineRepo, ...]:
    """Return every repository checkout visible at runner-start baseline time."""

    repos: list[BaselineRepo] = []
    main = _baseline_main_repo(project_dir)
    if main is not None:
        repos.append(main)
    repos.extend(_baseline_configured_sibling_repos(project_dir))
    repos.extend(_baseline_sdd_store_repos(project_dir))
    repos.extend(_baseline_agents_prompt_archive_repo(project_dir))
    repos.extend(_baseline_workspace_repo_checkouts(project_dir))
    return tuple(_dedupe_baseline_repos_by_path(repos))


def _baseline_main_repo(project_dir: str) -> BaselineRepo | None:
    path = Path(project_dir).expanduser()
    if not _has_git_entry(path):
        return None
    return BaselineRepo(
        name="main",
        path=finalizer_git.normalize_path(str(path)),
        kind="main",
    )


def _baseline_configured_sibling_repos(project_dir: str) -> list[BaselineRepo]:
    repos: list[BaselineRepo] = []
    for target in _configured_sibling_targets(project_dir):
        path = Path(target.workspace_dir).expanduser()
        if not _has_git_entry(path):
            continue
        repos.append(
            BaselineRepo(
                name=target.name,
                path=finalizer_git.normalize_path(str(path)),
                kind="sibling",
            )
        )
    return repos


def _baseline_sdd_store_repos(project_dir: str) -> list[BaselineRepo]:
    """Return existing SDD repository checkouts, including clean ones."""

    try:
        from sase.sdd._commit_store import sdd_commit_targets, sdd_store_label
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        workspace_num = None
        if project_file:
            workspace_num = _workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is None:
            workspace_num = _workspace_num_from_env()
        store = resolve_sdd_store(project_dir, workspace_num or 1)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return []

        repos: list[BaselineRepo] = []
        for target_store, _paths in sdd_commit_targets(store, None):
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not _has_git_entry(repo_root):
                continue
            repos.append(
                BaselineRepo(
                    name=(
                        sdd_store_label(target_store)
                        or target_store.sidecar_role
                        or "sdd"
                    ),
                    path=finalizer_git.normalize_path(str(repo_root)),
                    kind="sdd",
                )
            )
        return repos
    except Exception:
        return []


def _baseline_agents_prompt_archive_repo(project_dir: str) -> list[BaselineRepo]:
    """Return the agents prompt-archive sidecar checkout, if one is present."""

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return []
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not _has_git_entry(agents_root):
            return []
        return [
            BaselineRepo(
                name="agents prompt archive",
                path=finalizer_git.normalize_path(str(agents_root)),
                kind="sdd",
            )
        ]
    except Exception:
        return []


def _baseline_workspace_repo_checkouts(project_dir: str) -> list[BaselineRepo]:
    """Return pre-existing checkouts below ``sase/repos``."""

    repos_root = Path(project_dir).expanduser() / "sase" / "repos"
    if not repos_root.is_dir():
        return []

    repos: list[BaselineRepo] = []
    for repo_root in _iter_workspace_repo_checkouts(repos_root):
        repos.append(
            BaselineRepo(
                name=_workspace_checkout_name(repos_root, repo_root),
                path=finalizer_git.normalize_path(str(repo_root)),
                kind="external",
            )
        )
    return repos


def _iter_workspace_repo_checkouts(repos_root: Path) -> list[Path]:
    checkouts: list[Path] = []
    try:
        for current, dirnames, filenames in os.walk(repos_root):
            current_path = Path(current)
            if ".git" in dirnames or ".git" in filenames:
                checkouts.append(current_path)
                dirnames[:] = []
                if len(checkouts) >= _BASELINE_CHECKOUT_SCAN_LIMIT:
                    _logger.warning(
                        "Commit finalizer baseline checkout scan reached the %d "
                        "checkout limit under %s; skipped remaining directories "
                        "after %s",
                        _BASELINE_CHECKOUT_SCAN_LIMIT,
                        repos_root,
                        current_path,
                    )
                    break
                continue

            if _relative_depth(current_path, repos_root) >= (
                _BASELINE_CHECKOUT_SCAN_MAX_DEPTH
            ):
                dirnames[:] = []
            else:
                dirnames[:] = sorted(name for name in dirnames if name != ".git")
    except OSError:
        return checkouts
    return checkouts


def _workspace_checkout_name(repos_root: Path, repo_root: Path) -> str:
    try:
        return repo_root.relative_to(repos_root).as_posix()
    except ValueError:
        return repo_root.name


def _relative_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return _BASELINE_CHECKOUT_SCAN_MAX_DEPTH


def _has_git_entry(path: Path) -> bool:
    return (path / ".git").exists()


def _dedupe_baseline_repos_by_path(repos: list[BaselineRepo]) -> list[BaselineRepo]:
    order: list[str] = []
    by_path: dict[str, BaselineRepo] = {}
    for repo in repos:
        key = finalizer_git.normalize_path(repo.path)
        existing = by_path.get(key)
        if existing is None:
            order.append(key)
            by_path[key] = repo
            continue
        if (
            _DIRTY_REPO_KIND_PRIORITY[repo.kind]
            < _DIRTY_REPO_KIND_PRIORITY[existing.kind]
        ):
            by_path[key] = repo
    return [by_path[key] for key in order]


def _dedupe_dirty_repos_by_path(repos: list[DirtyRepo]) -> list[DirtyRepo]:
    """Collapse ``repos`` sharing a normalized path into a single entry.

    The winning entry keeps the most specific ``kind`` (see
    ``_DIRTY_REPO_KIND_PRIORITY``) and the union of both entries'
    ``changed_files``, in first-seen order.
    """
    order: list[str] = []
    by_path: dict[str, DirtyRepo] = {}
    for repo in repos:
        key = finalizer_git.normalize_path(repo.path)
        existing = by_path.get(key)
        if existing is None:
            order.append(key)
            by_path[key] = repo
            continue
        merged_files = tuple(
            dict.fromkeys((*existing.changed_files, *repo.changed_files))
        )
        winner = (
            repo
            if _DIRTY_REPO_KIND_PRIORITY[repo.kind]
            < _DIRTY_REPO_KIND_PRIORITY[existing.kind]
            else existing
        )
        by_path[key] = DirtyRepo(
            name=winner.name,
            path=winner.path,
            changed_files=merged_files,
            kind=winner.kind,
        )
    return [by_path[key] for key in order]


def collect_dirty_state(
    project_dir: str,
    *,
    artifact_root: Path | None = None,
) -> DirtyState:
    has_main_changes, main_files, main_instruction, main_details = (
        _build_commit_details(project_dir)
    )

    main_repo = (
        DirtyRepo(
            name="main",
            path=finalizer_git.normalize_path(project_dir),
            changed_files=tuple(main_files),
            kind="main",
        )
        if has_main_changes
        else None
    )
    sibling_targets = _configured_sibling_targets(project_dir)
    opened_names = opened_linked_repo_names(artifact_root)
    opened_workspace_dirs = opened_linked_repo_workspace_dirs(artifact_root)
    if opened_names:
        opened_workspace_dirs = {
            **dict.fromkeys(sorted(opened_names), ""),
            **opened_workspace_dirs,
        }
    sibling_repos = tuple(
        _dirty_configured_sibling_repos(
            sibling_targets,
            opened_workspace_dirs=opened_workspace_dirs,
        )
    )
    external_repos = tuple(
        _dirty_opened_external_repos(opened_external_repo_records(artifact_root))
    )
    sdd_repos = (
        *_dirty_sdd_store_repos(project_dir),
        *_dirty_agents_prompt_archive_repo(project_dir),
    )
    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    repos.extend(external_repos)
    repos.extend(sdd_repos)
    repos = _dedupe_dirty_repos_by_path(repos)

    repos, pre_existing_repos = _exclude_pre_existing_baseline(
        repos, load_dirty_baseline(artifact_root)
    )
    main_repo = next((repo for repo in repos if repo.kind == "main"), None)
    if main_repo is None:
        main_details = ""
    elif main_repo.changed_files != tuple(main_files):
        main_details = _render_main_details(
            list(main_repo.changed_files), main_instruction
        )
    sibling_repos = tuple(repo for repo in repos if repo.kind == "sibling")
    external_repos = tuple(repo for repo in repos if repo.kind == "external")
    sdd_repos = tuple(repo for repo in repos if repo.kind == "sdd")

    details = build_dirty_details(
        main_details=main_details,
        main_instruction=main_instruction,
        main_repo=main_repo,
        sibling_repos=sibling_repos,
        external_repos=external_repos,
        sdd_repos=sdd_repos,
    )
    details = build_pre_existing_details(details, pre_existing_repos)
    return DirtyState(
        project_dir=finalizer_git.normalize_path(project_dir),
        repos=tuple(repos),
        details=details,
    )


def _exclude_pre_existing_baseline(
    repos: list[DirtyRepo],
    baseline: DirtyBaseline | None,
) -> tuple[list[DirtyRepo], tuple[DirtyRepo, ...]]:
    """Split *repos* into (still relevant, unchanged-since-baseline).

    Only paths whose git status and content hash are provably unchanged
    since the baseline are excluded; a baseline-dirty path this run edited
    again keeps its current fingerprint and so stays in the must-commit set.
    """
    if not baseline:
        return repos, ()

    still: list[DirtyRepo] = []
    pre_existing: list[DirtyRepo] = []
    for repo in repos:
        baseline_fingerprints = baseline.get(finalizer_git.normalize_path(repo.path))
        still_files, pre_existing_files = split_pre_existing_changed_files(
            repo.path, list(repo.changed_files), baseline_fingerprints
        )
        if still_files:
            still.append(
                repo
                if still_files == list(repo.changed_files)
                else DirtyRepo(
                    name=repo.name,
                    path=repo.path,
                    changed_files=tuple(still_files),
                    kind=repo.kind,
                )
            )
        if pre_existing_files:
            pre_existing.append(
                DirtyRepo(
                    name=repo.name,
                    path=repo.path,
                    changed_files=tuple(pre_existing_files),
                    kind=repo.kind,
                )
            )
    return still, tuple(pre_existing)


def _render_main_details(changed_files: list[str], instruction: str) -> str:
    details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
    if instruction:
        details += f"\n\n{instruction}"
    return details


def _dirty_opened_external_repos(
    records: Mapping[str, Mapping[str, str]],
) -> list[DirtyRepo]:
    """Return dirty external repositories recorded in this agent run."""

    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for name, record in records.items():
        canonical_name = (record.get("ref") or name).strip()
        workspace_dir = record.get("workspace_dir", "").strip()
        if not canonical_name or not workspace_dir:
            continue
        workspace_dir = finalizer_git.normalize_path(workspace_dir)
        if canonical_name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue
        dirty.append(
            DirtyRepo(
                name=canonical_name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="external",
            )
        )
        seen_names.add(canonical_name)
        seen_paths.add(workspace_dir)
    return dirty


def _dirty_sdd_store_repos(project_dir: str) -> list[DirtyRepo]:
    """Return dirty external SDD repositories owned by this workspace."""

    try:
        from sase.sdd._commit_store import sdd_commit_targets, sdd_store_label
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        workspace_num = None
        if project_file:
            workspace_num = _workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is None:
            workspace_num = _workspace_num_from_env()
        store = resolve_sdd_store(project_dir, workspace_num or 1)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return []

        dirty: list[DirtyRepo] = []
        targets = sdd_commit_targets(store, None)
        for target_store, _paths in targets:
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not (repo_root / ".git").exists():
                continue
            changed_files = git_changed_files(str(repo_root))
            if not changed_files:
                continue
            dirty.append(
                DirtyRepo(
                    name=(
                        sdd_store_label(target_store)
                        or target_store.sidecar_role
                        or "sdd"
                    ),
                    path=finalizer_git.normalize_path(str(repo_root)),
                    changed_files=tuple(changed_files),
                    kind="sdd",
                )
            )
        return dirty
    except Exception:
        return []


def _dirty_agents_prompt_archive_repo(project_dir: str) -> list[DirtyRepo]:
    """Return a dirty agents sidecar only for canonical prompt-file edits."""

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return []
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not (agents_root / ".git").exists():
            return []
        changed_files = git_changed_files(str(agents_root))
        if not changed_files or not all(
            is_prompt_archive_path(path) for path in changed_files
        ):
            return []
        return [
            DirtyRepo(
                name="agents prompt archive",
                path=finalizer_git.normalize_path(str(agents_root)),
                changed_files=tuple(changed_files),
                kind="sdd",
            )
        ]
    except Exception:
        return []


def _build_commit_details(project_dir: str) -> tuple[bool, list[str], str, str]:
    has_changes, changed_files, instruction, details = build_commit_details(project_dir)
    if not has_changes:
        return (False, [], "", "")

    filtered = filter_sase_reserved_paths(changed_files)
    if not filtered:
        return (False, [], "", "")
    if filtered == changed_files:
        return (has_changes, changed_files, instruction, details)

    return (True, filtered, instruction, _render_main_details(filtered, instruction))


def _dirty_configured_sibling_repos(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str] | None = None,
    opened_names: set[str] | None = None,
) -> list[DirtyRepo]:
    if opened_workspace_dirs is None:
        opened_workspace_dirs = dict.fromkeys(sorted(opened_names or set()), "")

    targets_by_name = {target.name: target for target in sibling_targets}
    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()

    for name, workspace_dir in _blocking_sibling_candidates(
        sibling_targets,
        opened_workspace_dirs=opened_workspace_dirs,
        targets_by_name=targets_by_name,
    ):
        if name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue

        dirty.append(
            DirtyRepo(
                name=name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="sibling",
            )
        )
        seen_names.add(name)
        seen_paths.add(workspace_dir)
    return dirty


def _blocking_sibling_candidates(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str],
    targets_by_name: Mapping[str, SiblingTarget],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    for raw_name, recorded_workspace_dir in opened_workspace_dirs.items():
        name = raw_name.strip()
        if not name:
            continue

        target = targets_by_name.get(name)

        workspace_dir = recorded_workspace_dir.strip()
        if workspace_dir:
            workspace_dir = finalizer_git.normalize_path(workspace_dir)
        elif target is not None:
            workspace_dir = target.workspace_dir
        else:
            continue

        candidates.append((name, workspace_dir))

    for target in sibling_targets:
        candidates.append((target.name, target.workspace_dir))

    return candidates


def _configured_sibling_targets(
    project_dir: str,
) -> list[SiblingTarget]:
    # Prefer the canonical linked env var and fall back to the deprecated
    # sibling env var so old launches still drive finalizer behavior.
    if LINKED_REPOS_JSON_ENV in os.environ or SIBLING_REPOS_JSON_ENV in os.environ:
        return _sibling_targets_from_env()
    return _sibling_targets_from_config(project_dir)


def _sibling_targets_from_env() -> list[SiblingTarget]:
    targets: list[SiblingTarget] = []
    for index, item in enumerate(linked_repo_metadata_from_env(os.environ), start=1):
        if is_legacy_static_linked_repo_record(item):
            continue
        workspace_dir = item.get("workspace_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir.strip():
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"sibling_{index}"
        targets.append(
            SiblingTarget(
                name=name.strip(),
                workspace_dir=finalizer_git.normalize_path(workspace_dir),
            )
        )
    return targets


def _sibling_targets_from_config(
    project_dir: str,
) -> list[SiblingTarget]:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if not project_file:
        return []

    workspace_num = _workspace_num_for_project_file(project_file, project_dir)
    if workspace_num is None:
        return []

    try:
        from sase.linked_repos import resolve_linked_repos_for_project

        resolution = resolve_linked_repos_for_project(
            project_file=project_file,
            workspace_dir=project_dir,
            workspace_num=workspace_num,
            materialize=False,
        )
    except Exception:
        return []

    return [
        SiblingTarget(
            name=repo.name,
            workspace_dir=finalizer_git.normalize_path(repo.workspace_dir),
        )
        for repo in resolution.repos
    ]


def _workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = _workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(finalizer_git.normalize_path(primary_dir))
    project_path = Path(finalizer_git.normalize_path(project_dir))
    if project_path == primary_path:
        return 0
    if project_path.parent != primary_path.parent:
        return None

    prefix = f"{primary_path.name}_"
    if not project_path.name.startswith(prefix):
        return None
    suffix = project_path.name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _workspace_num_from_env() -> int | None:
    for key in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None
