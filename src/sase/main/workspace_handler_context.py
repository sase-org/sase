"""Project context resolution for the ``sase workspace`` CLI."""

from __future__ import annotations

import subprocess
import sys
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.core.paths import is_valid_sase_project_name
from sase.workflows.utils import get_project_file_path
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import parse_bare_repo_dir, parse_workspace_dir

ConfigLoader = Callable[[], dict[str, Any] | None]
LifecycleReader = Callable[[str], Any]
LifecycleApplier = Callable[[str, str], str]


@dataclass(frozen=True)
class ProjectContext:
    """Cached resolution of a project name to its workspace store."""

    project_name: str
    project_file: str
    primary_workspace_dir: str
    store: WorkspaceStore
    is_sibling: bool = False
    is_configured_linked_repo: bool = False
    linked_host_primary_workspace_dir: str | None = None
    linked_repo_remote_url: str | None = None


@dataclass(frozen=True)
class _LinkedRepoProject:
    name: str
    primary_dir: str
    current_project_file: str | None = None
    current_primary_workspace_dir: str | None = None


def resolve_project_context(
    project: str | None,
    *,
    load_config: ConfigLoader,
    read_project_lifecycle: LifecycleReader,
    apply_project_lifecycle: LifecycleApplier,
) -> ProjectContext:
    """Resolve the project name and build a ``WorkspaceStore`` for it.

    Falls back to managed-checkout marker and sibling-scan inference when
    *project* is omitted.  Exits with a non-zero status when no project
    can be resolved or the project's primary workspace cannot be located.
    """
    project_name = project
    if not project_name:
        from sase.bead.project_name import infer_project_name_from_cwd

        project_name = infer_project_name_from_cwd()

    if not project_name:
        print(
            "Unable to infer project from current directory; pass -p/--project.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    project_file = get_project_file_path(project_name)
    primary = parse_workspace_dir(project_file) or ""
    if not primary:
        try:
            sibling_ctx = _materialize_sibling_project_context(
                project_name,
                project_file,
                load_config=load_config,
                read_project_lifecycle=read_project_lifecycle,
                apply_project_lifecycle=apply_project_lifecycle,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        if sibling_ctx is not None:
            return sibling_ctx
        print(
            f"Project '{project_name}' has no WORKSPACE_DIR in {project_file}.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        sibling_ctx = _heal_sibling_project_context(
            project_name,
            project_file,
            primary,
            load_config=load_config,
            read_project_lifecycle=read_project_lifecycle,
            apply_project_lifecycle=apply_project_lifecycle,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    if sibling_ctx is not None:
        return sibling_ctx

    store = WorkspaceStore(primary, config=load_config())
    return ProjectContext(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=store,
        is_sibling=_is_sibling_project_spec(
            project_file,
            read_project_lifecycle=read_project_lifecycle,
        ),
    )


def _materialize_sibling_project_context(
    project_name: str,
    project_file: str,
    *,
    load_config: ConfigLoader,
    read_project_lifecycle: LifecycleReader,
    apply_project_lifecycle: LifecycleApplier,
) -> ProjectContext | None:
    """Create missing ProjectSpec metadata for a configured linked repo.

    The backing ProjectSpec lifecycle state is still named ``sibling`` (kept as
    legacy backing state for linked-repo bookkeeping during the migration).
    """
    linked_repo = _configured_linked_repo(project_name, load_config=load_config)
    if linked_repo is None:
        return None

    primary = _validate_linked_repo_primary(
        project_name,
        linked_repo.primary_dir,
        current_primary_workspace_dir=linked_repo.current_primary_workspace_dir,
    )
    metadata = _sibling_project_metadata(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        current_project_file=linked_repo.current_project_file,
    )
    _ensure_sibling_project_spec(
        project_file,
        metadata,
        read_project_lifecycle=read_project_lifecycle,
        apply_project_lifecycle=apply_project_lifecycle,
    )

    store = WorkspaceStore(primary, config=load_config())
    return ProjectContext(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=store,
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=linked_repo.current_primary_workspace_dir,
    )


def _heal_sibling_project_context(
    project_name: str,
    project_file: str,
    primary_workspace_dir: str,
    *,
    load_config: ConfigLoader,
    read_project_lifecycle: LifecycleReader,
    apply_project_lifecycle: LifecycleApplier,
) -> ProjectContext | None:
    """Stamp configured linked-repo specs as ``sibling`` when needed."""
    linked_repo = _configured_linked_repo(
        project_name,
        load_config=load_config,
        require_loaded_config_match=True,
    )
    if linked_repo is None:
        return None

    primary = _validate_linked_repo_primary(
        project_name,
        primary_workspace_dir,
        current_primary_workspace_dir=linked_repo.current_primary_workspace_dir,
    )
    metadata = _sibling_project_metadata(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        current_project_file=linked_repo.current_project_file,
    )
    _ensure_sibling_project_spec(
        project_file,
        metadata,
        read_project_lifecycle=read_project_lifecycle,
        apply_project_lifecycle=apply_project_lifecycle,
    )

    store = WorkspaceStore(primary, config=load_config())
    return ProjectContext(
        project_name=project_name,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=store,
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=linked_repo.current_primary_workspace_dir,
    )


def _configured_linked_repo(
    project_name: str,
    *,
    load_config: ConfigLoader,
    require_loaded_config_match: bool = False,
) -> _LinkedRepoProject | None:
    if not is_valid_sase_project_name(project_name):
        return None

    env_repo = _linked_repo_project_from_env(project_name, load_config=load_config)
    if env_repo is not None:
        return env_repo

    if require_loaded_config_match and not _config_names_linked_repo(
        project_name,
        load_config=load_config,
    ):
        return None

    current = _current_project_context(load_config=load_config)
    if current is None or current.project_name == project_name:
        return None

    from sase.linked_repos import resolve_linked_repos_for_project

    resolution = resolve_linked_repos_for_project(
        project_file=current.project_file,
        workspace_dir=current.primary_workspace_dir,
        workspace_num=0,
        materialize=False,
    )
    for warning in resolution.warnings:
        if f"{project_name!r}" in warning:
            raise RuntimeError(warning)

    sibling = next(
        (repo for repo in resolution.repos if repo.name == project_name),
        None,
    )
    if sibling is None:
        return None

    return _LinkedRepoProject(
        name=sibling.name,
        primary_dir=sibling.primary_dir,
        current_project_file=current.project_file,
        current_primary_workspace_dir=current.primary_workspace_dir,
    )


def _linked_repo_project_from_env(
    project_name: str, *, load_config: ConfigLoader
) -> _LinkedRepoProject | None:
    from sase.linked_repos import linked_repo_metadata_from_env

    for item in linked_repo_metadata_from_env(os.environ):
        if project_name not in {item.get("name"), item.get("slug")}:
            continue
        primary_dir = str(item.get("primary_dir") or "").strip()
        if not primary_dir:
            return None
        current = _current_project_context(load_config=load_config)
        return _LinkedRepoProject(
            name=project_name,
            primary_dir=primary_dir,
            current_project_file=(current.project_file if current else None),
            current_primary_workspace_dir=(
                current.primary_workspace_dir if current else None
            ),
        )
    return None


def _config_names_linked_repo(
    project_name: str,
    *,
    load_config: ConfigLoader,
) -> bool:
    try:
        config = load_config() or {}
    except Exception:
        return False
    repos = config.get("repos")
    canonical = repos.get("linked") if isinstance(repos, dict) else None
    for entries in (canonical, config.get("linked_repos"), config.get("sibling_repos")):
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name") == project_name:
                return True
    return False


def _validate_linked_repo_primary(
    project_name: str,
    primary_workspace_dir: str,
    *,
    current_primary_workspace_dir: str | None,
) -> str:
    primary = primary_workspace_dir.rstrip("/") or primary_workspace_dir
    if not Path(primary).is_dir():
        raise RuntimeError(
            f"Configured linked repo '{project_name}' primary path does not exist: "
            f"{primary}"
        )

    git_reference_dir = current_primary_workspace_dir or os.getcwd()
    if _is_git_repo(git_reference_dir) and not _is_git_repo(primary):
        raise RuntimeError(
            f"Configured linked repo '{project_name}' is not a Git checkout: {primary}"
        )
    return primary


def _current_project_context(*, load_config: ConfigLoader) -> ProjectContext | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    current_project = infer_project_name_from_cwd()
    if not current_project or not is_valid_sase_project_name(current_project):
        return None

    project_file = get_project_file_path(current_project)
    primary = parse_workspace_dir(project_file) or ""
    if not primary:
        return None

    return ProjectContext(
        project_name=current_project,
        project_file=project_file,
        primary_workspace_dir=primary,
        store=WorkspaceStore(primary, config=load_config()),
    )


def _is_sibling_project_spec(
    project_file: str,
    *,
    read_project_lifecycle: LifecycleReader,
) -> bool:
    try:
        content = Path(project_file).expanduser().read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        lifecycle = read_project_lifecycle(content)
    except Exception:
        return False
    return getattr(lifecycle, "state", "") == "sibling"


def _sibling_project_metadata(
    *,
    project_name: str,
    project_file: str,
    primary_workspace_dir: str,
    current_project_file: str | None,
) -> dict[str, str]:
    metadata = {
        "WORKSPACE_DIR": primary_workspace_dir,
    }

    existing_bare_repo_dir = parse_bare_repo_dir(project_file)
    if existing_bare_repo_dir:
        metadata["BARE_REPO_DIR"] = existing_bare_repo_dir
        return metadata

    if current_project_file is None:
        return metadata

    current_bare_repo_dir = parse_bare_repo_dir(current_project_file)
    if not current_bare_repo_dir:
        return metadata

    origin = _git_origin_url(primary_workspace_dir)
    if origin and _is_local_git_url(origin):
        metadata["BARE_REPO_DIR"] = str(Path(origin).expanduser())

    return metadata


def _ensure_sibling_project_spec(
    project_file: str,
    metadata: dict[str, str],
    *,
    read_project_lifecycle: LifecycleReader,
    apply_project_lifecycle: LifecycleApplier,
) -> None:
    path = Path(project_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with changespec_lock(str(path)):
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""

        lifecycle = read_project_lifecycle(content)
        if lifecycle.explicit and lifecycle.state != "sibling":
            raise RuntimeError(
                f"ProjectSpec {path} has explicit PROJECT_STATE {lifecycle.state!r}; "
                "refusing to overwrite it with sibling"
            )

        updated = content
        if lifecycle.state != "sibling" or not lifecycle.explicit:
            updated = apply_project_lifecycle(updated, "sibling")
        for key, value in metadata.items():
            updated = _ensure_header_metadata(updated, key, value)

        write_changespec_atomic(
            str(path),
            updated,
            "Materialize sibling ProjectSpec metadata",
        )


def _ensure_header_metadata(content: str, key: str, value: str) -> str:
    prefix = f"{key}:"
    lines = content.splitlines(keepends=True)
    newline = _preferred_newline(lines, content)
    replacement = f"{prefix} {value}"
    header_end = _first_header_end(lines)

    for index, line in enumerate(lines[:header_end]):
        if not line.startswith(prefix):
            continue
        current = line.split(":", 1)[1].strip()
        if current:
            return content
        lines[index] = replacement + _line_ending(line, newline)
        return "".join(lines)

    insert_idx = _metadata_insert_index(lines)
    if insert_idx == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] = lines[-1] + newline
    lines.insert(insert_idx, replacement + newline)
    return "".join(lines)


def _first_header_end(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith("NAME:"):
            return index
    return len(lines)


def _metadata_insert_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            return index
    return len(lines)


def _preferred_newline(lines: list[str], content: str) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\r\n" if "\r\n" in content else "\n"


def _line_ending(line: str, default: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return default


def _is_git_repo(path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_origin_url(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
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


def _is_local_git_url(url: str) -> bool:
    return not url.startswith(("http://", "https://", "git@", "ssh://"))
