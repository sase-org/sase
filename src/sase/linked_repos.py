"""Configured linked repository resolution for launched agents.

This module is the stable public facade for linked-repository support. Focused
environment, marker-persistence, and configuration helpers live in neighboring
internal modules; resolution and materialization remain here because callers
patch these public functions at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import uuid

from sase._linked_repo_config import (
    DEFAULT_LINKED_REPOS_CONFIG_KEY,
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    LINKED_REPOS_CONFIG_KEY,
    REPOS_CONFIG_KEY,
    SIBLING_REPOS_CONFIG_KEY,
    _DEFAULT_LINKED_REPO_MARKER,
    _SIDECAR_REMOTE_URL_KEY,
    _SIDECAR_REPO_MARKER,
    _SIDECAR_ROLE_KEY,
    _SIDECAR_SLUG_KEY,
    inject_default_linked_repos,
    merged_repo_entries_from_config,
    merged_sidecar_entries_from_config,
    normalize_path,
    read_project_local_config,
    resolution_config,
    resolve_config_path,
)
from sase._linked_repo_env import (
    LINKED_REPO_ENV_PREFIX,
    LINKED_REPO_ENV_SUFFIXES,
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPO_ENV_PREFIX,
    SIBLING_REPO_ENV_SUFFIXES,
    SIBLING_REPOS_JSON_ENV,
    LinkedRepoResolution,
    ResolvedLinkedRepo as _ResolvedLinkedRepo,
    apply_linked_repo_env,
    is_legacy_static_linked_repo_record,
    linked_repo_metadata_from_env,
    scrub_linked_repo_env,
)
from sase._linked_repo_markers import (
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    OpenedRepoKind,
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_records,
    opened_linked_repo_workspace_dirs,
    opened_repo_records,
    record_opened_external_repo,
    record_opened_linked_repo,
    record_opened_repo,
)

# Host-scoped linked and sidecar clones are launch-scoped in numbered
# workspaces. Their primary-checkout counterparts remain durable local sources.
SIDECAR_REPO_CLONES_SUBDIR = ("sase", "repos")
LINKED_REPO_CLONES_SUBDIR = ("sase", "repos", "linked")
EXTERNAL_REPO_CLONES_SUBDIR = ("sase", "repos", "external")

# Preserve the historical class identity for introspection and pickling even
# though their implementations now live in the environment helper module.
LinkedRepoResolution.__module__ = __name__
_ResolvedLinkedRepo.__module__ = __name__

__all__ = [
    "DEFAULT_LINKED_REPOS_CONFIG_KEY",
    "DEFAULT_PLANS_DESCRIPTION",
    "DEFAULT_RESEARCH_DESCRIPTION",
    "EXTERNAL_REPO_CLONES_SUBDIR",
    "SIDECAR_REPO_CLONES_SUBDIR",
    "LINKED_REPO_CLONES_SUBDIR",
    "LINKED_REPO_ENV_PREFIX",
    "LINKED_REPO_ENV_SUFFIXES",
    "LINKED_REPOS_CONFIG_KEY",
    "LINKED_REPOS_JSON_ENV",
    "OPENED_LINKED_FILENAME",
    "OPENED_SIBLINGS_FILENAME",
    "OpenedRepoKind",
    "REPOS_CONFIG_KEY",
    "SIBLING_REPO_ENV_PREFIX",
    "SIBLING_REPO_ENV_SUFFIXES",
    "SIBLING_REPOS_CONFIG_KEY",
    "SIBLING_REPOS_JSON_ENV",
    "LinkedRepoResolution",
    "apply_linked_repo_env",
    "clear_workspace_repos",
    "external_repo_clone_dir",
    "sidecar_repo_clone_dir",
    "is_legacy_static_linked_repo_record",
    "linked_repo_clone_dir",
    "linked_repo_metadata_from_env",
    "materialize_linked_repo_workspace",
    "opened_external_repo_records",
    "opened_linked_repo_names",
    "opened_linked_repo_records",
    "opened_linked_repo_workspace_dirs",
    "opened_repo_records",
    "record_opened_external_repo",
    "record_opened_linked_repo",
    "record_opened_repo",
    "resolve_linked_repos_for_project",
    "sdd_sidecar_clone_dirname",
    "scrub_linked_repo_env",
]


def resolve_linked_repos_for_project(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any] | None = None,
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve configured linked repos for a launched project workspace."""

    primary_workspace_dir = _primary_workspace_dir(project_file, workspace_dir)
    local_config = read_project_local_config(primary_workspace_dir)
    resolved_config = resolution_config(primary_workspace_dir, config)
    entries, merge_warnings = merged_repo_entries_from_config(
        resolved_config,
        primary_workspace_dir=primary_workspace_dir,
    )
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        local_config=config if config is not None else local_config,
    )
    resolution = _resolve_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        workspace_num=workspace_num,
        config=resolved_config,
        materialize=materialize,
    )
    if merge_warnings:
        return LinkedRepoResolution(
            resolution.repos,
            (*merge_warnings, *resolution.warnings),
        )
    return resolution


def _resolve_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve merged linked-repo config entries into concrete paths."""

    primary_root = normalize_path(primary_workspace_dir)
    resolved: list[_ResolvedLinkedRepo] = []
    resolution_warnings: list[str] = []
    used_env_names: set[str] = set()

    for entry in entries:
        name = entry.get("name")
        raw_path = entry.get("path")
        auto_clone = entry.get("auto_clone") is True
        is_sidecar = entry.get(_SIDECAR_REPO_MARKER) is True
        disabled = entry.get("disabled") is True
        sidecar_role = _entry_text(entry, _SIDECAR_ROLE_KEY)
        sidecar_slug = _entry_text(entry, _SIDECAR_SLUG_KEY)
        remote_url = _entry_text(entry, _SIDECAR_REMOTE_URL_KEY)
        if disabled:
            continue
        if not isinstance(name, str) or not name.strip():
            kind = "sidecar" if is_sidecar else "linked repo"
            resolution_warnings.append(f"Skipping {kind} with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            resolution_warnings.append(
                f"Skipping {'sidecar' if is_sidecar else 'linked repo'} "
                f"{name!r} with missing path"
            )
            continue

        if "workspace" in entry:
            resolution_warnings.append(
                f"Linked repo {name!r} uses deprecated workspace configuration; "
                "ignoring it because linked workspaces are now host-scoped"
            )

        primary_dir = resolve_config_path(raw_path, relative_to=primary_root)
        if not Path(primary_dir).is_dir():
            if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True:
                continue
            if not is_sidecar:
                resolution_warnings.append(
                    f"Skipping linked repo {name!r}: primary path does not exist: "
                    f"{primary_dir}"
                )
                continue

        try:
            resolved_workspace_dir = _resolve_workspace_dir(
                primary_dir,
                name=name,
                host_primary_dir=primary_root,
                workspace_num=workspace_num,
                config=config,
                materialize=materialize,
                sidecar_dirname=sidecar_role if is_sidecar else None,
                expected_remote_url=remote_url,
            )
        except RuntimeError as exc:
            resolution_warnings.append(f"Skipping linked repo {name!r}: {exc}")
            continue

        env_name = _unique_env_name(_sanitize_env_name(name), used_env_names)
        used_env_names.add(env_name)
        resolved.append(
            _ResolvedLinkedRepo(
                name=name,
                env_name=env_name,
                primary_dir=primary_dir,
                workspace_dir=resolved_workspace_dir,
                workspace_num=workspace_num,
                auto_clone=auto_clone,
                kind="sidecar" if is_sidecar else "linked",
                slug=sidecar_slug or None,
                remote_url=remote_url or None,
            )
        )

    return LinkedRepoResolution(tuple(resolved), tuple(resolution_warnings))


def _primary_workspace_dir(project_file: str, workspace_dir: str) -> str:
    from sase.workspace_provider.utils import parse_workspace_dir

    parsed = parse_workspace_dir(project_file)
    if parsed:
        return normalize_path(parsed)
    fallback = workspace_dir or os.getcwd()
    return normalize_path(fallback)


def linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Return the canonical host-scoped clone path for linked repo *name*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*LINKED_REPO_CLONES_SUBDIR, name))
    )


def external_repo_clone_dir(
    host_checkout: str | Path,
    scheme_or_projects: str,
    *parts: str,
) -> str:
    """Return a host-scoped clone path below ``sase/repos/external``."""

    components = (scheme_or_projects, *parts)
    if any(
        not component
        or component in {".", ".."}
        or component != component.strip()
        or "/" in component
        or "\\" in component
        for component in components
    ):
        raise ValueError("external repo clone path components must be safe names")
    return normalize_path(
        str(Path(host_checkout).joinpath(*EXTERNAL_REPO_CLONES_SUBDIR, *components))
    )


def sidecar_repo_clone_dir(host_checkout: str | Path, dirname: str) -> str:
    """Return the durable host-scoped clone path for SDD sidecar *dirname*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*SIDECAR_REPO_CLONES_SUBDIR, dirname))
    )


def _repo_basename(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def _sdd_sidecar_repo_dirnames(
    primary_workspace_dir: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Map configured/store/fallback sidecar names to clone directory names."""

    from sase.sdd.store import read_sdd_store_record

    primary = Path(primary_workspace_dir).expanduser().resolve(strict=False)
    configured: dict[str, str] = {}
    configured_roles: set[str] = set()
    disabled: set[str] = set()
    try:
        resolved_config = resolution_config(str(primary), config)
        configured_entries = merged_sidecar_entries_from_config(
            resolved_config,
            primary_workspace_dir=str(primary),
        )
    except Exception:
        configured_entries = []
    for entry in configured_entries:
        role = _entry_text(entry, _SIDECAR_ROLE_KEY)
        slug = _entry_text(entry, _SIDECAR_SLUG_KEY)
        tokens = {token for token in (role, slug) if token}
        if role:
            configured_roles.add(role)
        if entry.get("disabled") is True:
            disabled.update(tokens)
            continue
        if role:
            configured.update(dict.fromkeys(tokens, role))

    record = read_sdd_store_record(primary)
    if record is not None:
        store_mapping = {
            _repo_basename(sidecar.repo): kind
            for kind in ("plans", "research")
            if (sidecar := record.sidecar_for_kind(kind)) is not None
            and kind not in configured_roles
            and kind not in disabled
            and _repo_basename(sidecar.repo) not in disabled
        }
        return {**store_mapping, **configured}

    project_name = primary.name
    if not project_name:
        return configured
    fallbacks = {
        slug: kind
        for kind in ("plans", "research")
        if kind not in configured_roles
        if kind not in disabled
        if (slug := f"{project_name}--{kind}") not in disabled
    }
    return {**fallbacks, **configured}


def sdd_sidecar_clone_dirname(
    primary_workspace_dir: str | Path,
    name: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Return the clone dirname for sidecar entry *name*, if it is one."""

    return _sdd_sidecar_repo_dirnames(
        primary_workspace_dir,
        config=config,
    ).get(name)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


_DELETE_PATHS_SCRIPT = """
from pathlib import Path
import shutil
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass
"""


def _delete_paths_in_background(paths: Sequence[Path]) -> None:
    """Best-effort delete *paths* outside the workspace-prep critical path."""

    if not paths:
        return
    try:
        kwargs: dict[str, Any] = {"start_new_session": True}
        if os.name == "nt":
            kwargs = {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            }
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _DELETE_PATHS_SCRIPT,
                *(str(path) for path in paths),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError:
        for path in paths:
            _remove_path(path)


def clear_workspace_repos(
    workspace_dir: str | Path,
    workspace_num: int,
) -> None:
    """Remove launch-scoped repositories from a numbered host workspace."""

    if workspace_num <= 1:
        return

    workspace = Path(workspace_dir)
    repos_root = workspace.joinpath(*SIDECAR_REPO_CLONES_SUBDIR)
    trash_root = workspace / ".sase" / "trash"
    stale_trash = (
        list(trash_root.iterdir())
        if trash_root.is_dir() and not trash_root.is_symlink()
        else []
    )

    if not os.path.lexists(repos_root):
        _delete_paths_in_background(stale_trash)
        return

    if not repos_root.is_dir() or repos_root.is_symlink():
        _remove_path(repos_root)
        _delete_paths_in_background(stale_trash)
        return

    trash_root.mkdir(parents=True, exist_ok=True)
    trashed_repos = trash_root / f"repos-{uuid.uuid4().hex}"
    os.rename(repos_root, trashed_repos)
    _delete_paths_in_background([*stale_trash, trashed_repos])


def _linked_repo_clone_location(
    workspace_dir: str | Path,
) -> tuple[Path, str, bool] | None:
    """Return ``(host_checkout, name, is_sidecar)`` for a known layout."""

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    layouts = (
        (LINKED_REPO_CLONES_SUBDIR, False),
        (SIDECAR_REPO_CLONES_SUBDIR, True),
    )
    for subdir, is_sidecar in layouts:
        parent_parts = path.parent.parts
        if len(parent_parts) < len(subdir):
            continue
        if tuple(parent_parts[-len(subdir) :]) != subdir:
            continue
        host_checkout = path.parent
        for _ in subdir:
            host_checkout = host_checkout.parent
        return host_checkout, path.name, is_sidecar
    return None


def _resolve_workspace_dir(
    primary_dir: str,
    *,
    name: str,
    host_primary_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool,
    sidecar_dirname: str | None = None,
    expected_remote_url: str = "",
) -> str:
    if workspace_num <= 1:
        if materialize and sidecar_dirname is not None and expected_remote_url:
            return materialize_linked_repo_workspace(
                primary_dir=primary_dir,
                workspace_dir=primary_dir,
                workspace_num=workspace_num,
                expected_remote_url=expected_remote_url,
            )
        return primary_dir

    from sase.workspace_provider.store import WorkspaceStore

    host_workspace_dir = (
        WorkspaceStore(host_primary_dir, config=config)
        .resolve(workspace_num)
        .checkout_dir.rstrip("/")
    )
    sidecar_dirname = sidecar_dirname or sdd_sidecar_clone_dirname(
        host_primary_dir,
        name,
        config=config,
    )
    target = (
        sidecar_repo_clone_dir(host_workspace_dir, sidecar_dirname)
        if sidecar_dirname is not None
        else linked_repo_clone_dir(host_workspace_dir, name)
    )
    if not materialize:
        return target

    return materialize_linked_repo_workspace(
        primary_dir=primary_dir,
        workspace_dir=target,
        workspace_num=workspace_num,
        expected_remote_url=expected_remote_url or None,
    )


def materialize_linked_repo_workspace(
    *,
    primary_dir: str,
    workspace_dir: str,
    workspace_num: int,
    expected_remote_url: str | None = None,
) -> str:
    """Clone a host-scoped linked workspace and initialize its SDD sidecar."""

    from sase.workspace_provider.utils import ensure_git_clone_at

    location = _linked_repo_clone_location(workspace_dir)
    if location is not None:
        host_checkout, name, is_sidecar = location
        from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

        ensure_git_info_exclude_entry(str(host_checkout), "/sase/repos/")
        if is_sidecar:
            workspace_dir = sidecar_repo_clone_dir(host_checkout, name)
        else:
            workspace_dir = linked_repo_clone_dir(host_checkout, name)

    if expected_remote_url:
        checkout_dir = _materialize_remote_identified_sidecar(
            primary_dir=primary_dir,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            expected_remote_url=expected_remote_url,
        )
    else:
        checkout_dir = ensure_git_clone_at(primary_dir, workspace_num, workspace_dir)
    from sase.workspace_provider.git_exclude import ensure_sase_git_info_excludes

    ensure_sase_git_info_excludes(checkout_dir)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return normalize_path(checkout_dir)


def _materialize_remote_identified_sidecar(
    *,
    primary_dir: str,
    workspace_dir: str,
    workspace_num: int,
    expected_remote_url: str,
) -> str:
    """Materialize a sidecar, replacing stale clones of another remote."""

    target = Path(workspace_dir).expanduser()
    source = Path(primary_dir).expanduser()
    if target.is_dir() and _clone_origin_matches(target, expected_remote_url):
        return str(target)

    if workspace_num <= 1:
        if os.path.lexists(target):
            if not (target / ".git").is_dir():
                raise RuntimeError(
                    f"Sidecar path at {target} is not a Git clone; refusing to "
                    "replace it during remote cutover"
                )
            clean = _git_worktree_is_clean(target)
            if clean is not True:
                detail = (
                    "has local changes" if clean is False else "could not be inspected"
                )
                raise RuntimeError(
                    f"Sidecar clone at {target} {detail}; refusing to replace "
                    "it during remote cutover"
                )
        from sase.sdd._store_link import ensure_sidecar_sdd_clone

        ensure_sidecar_sdd_clone(target, expected_remote_url, strict=True)
        return str(target)

    if os.path.lexists(target):
        _remove_path(target)
    if source.is_dir() and _clone_origin_matches(source, expected_remote_url):
        from sase.workspace_provider.utils import ensure_git_clone_at

        return ensure_git_clone_at(str(source), workspace_num, str(target))

    from sase.sdd._store_link import ensure_sidecar_sdd_clone

    ensure_sidecar_sdd_clone(target, expected_remote_url, strict=True)
    return str(target)


def _clone_origin_matches(path: Path, expected_remote_url: str) -> bool:
    origin = _git_origin_url(path)
    return origin is not None and _git_remote_identity(origin) == _git_remote_identity(
        expected_remote_url
    )


def _git_origin_url(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_worktree_is_clean(path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return not result.stdout.strip()


def _git_remote_identity(url: str) -> str:
    value = url.strip().rstrip("/")
    if value.endswith(".git"):
        value = value[: -len(".git")]
    ssh_match = re.match(r"^[^@\s]+@([^:]+):(.+)$", value)
    if ssh_match:
        return f"{ssh_match.group(1).casefold()}/{ssh_match.group(2).strip('/')}"
    url_match = re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$",
        value,
    )
    if url_match:
        return f"{url_match.group(1).casefold()}/{url_match.group(2).strip('/')}"
    return normalize_path(value)


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _sanitize_env_name(name: str) -> str:
    env_name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return env_name or "REPO"


def _unique_env_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"
