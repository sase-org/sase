"""Resolution and atomic materialization for external repository opens."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Protocol
import uuid

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.external_repos import (
    ExternalRepoRef,
    ExternalRepoRefError,
    external_repo_clone_parts_from_name,
    parse_external_repo_ref,
)
from sase.linked_repos import external_repo_clone_dir, record_opened_external_repo
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoInventory
from sase.workspace_provider import clone_external_repo, get_external_repo_schemes


class ExternalRepoOpenError(ValueError):
    """Raised when an external repo cannot be resolved or materialized."""


class _CheckoutResolver(Protocol):
    """Resolve or materialize one host workspace checkout."""

    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


@dataclass(frozen=True)
class _ExternalRepoOpenResult:
    """Canonical identity and path for one successful external open."""

    canonical_name: str
    path: str


@dataclass(frozen=True)
class _ExternalRepoTarget:
    canonical_name: str
    dest_dir: str
    project_source_dir: str | None = None
    provider_ref: ExternalRepoRef | None = None


def open_external_repo(
    name: str,
    *,
    host_ctx: ProjectContext,
    workspace_num: int,
    inventory: RepoInventory,
    reason: str,
    resolve_checkout: _CheckoutResolver,
) -> _ExternalRepoOpenResult:
    """Resolve, materialize, and marker-record an external repository."""

    host_checkout = _resolve_host_checkout(
        host_ctx,
        workspace_num,
        resolve_checkout=resolve_checkout,
    )
    target = _resolve_external_repo_target(
        name,
        host_ctx=host_ctx,
        host_checkout=host_checkout,
        inventory=inventory,
    )
    path = _materialize_external_repo(target)
    record_opened_external_repo(
        target.canonical_name,
        path,
        reason=reason,
        opened_at=datetime.now(tz=UTC).isoformat(),
    )
    return _ExternalRepoOpenResult(target.canonical_name, path)


def _resolve_host_checkout(
    host_ctx: ProjectContext,
    workspace_num: int,
    *,
    resolve_checkout: _CheckoutResolver,
) -> str:
    """Resolve the host checkout that owns the workspace-local clone tree."""

    try:
        with contextlib.redirect_stdout(sys.stderr):
            path = resolve_checkout(host_ctx, workspace_num, materialize=True)
    except (RuntimeError, ValueError) as exc:
        raise ExternalRepoOpenError(str(exc)) from exc
    return str(Path(path).expanduser().resolve(strict=False))


def _resolve_external_repo_target(
    name: str,
    *,
    host_ctx: ProjectContext,
    host_checkout: str,
    inventory: RepoInventory,
) -> _ExternalRepoTarget:
    """Resolve tier 2 (registered project) then tier 3 (provider ref)."""

    requested = name.strip()
    project_record = _resolve_external_project_record(requested, host_ctx=host_ctx)
    if project_record is not None:
        canonical_name = effective_project_name(project_record)
        source = (project_record.workspace_dir or "").strip()
        if not source or not Path(source).expanduser().is_dir():
            raise ExternalRepoOpenError(
                f"Project '{canonical_name}' has no available primary checkout."
            )
        try:
            clone_parts = external_repo_clone_parts_from_name(canonical_name)
            dest_dir = external_repo_clone_dir(
                host_checkout,
                clone_parts[0],
                *clone_parts[1:],
            )
        except (ExternalRepoRefError, ValueError) as exc:
            raise ExternalRepoOpenError(
                f"Project '{canonical_name}' cannot be used as an external repo: {exc}"
            ) from exc
        return _ExternalRepoTarget(
            canonical_name=canonical_name,
            dest_dir=dest_dir,
            project_source_dir=str(Path(source).expanduser().resolve(strict=False)),
        )

    try:
        provider_ref = parse_external_repo_ref(requested)
    except ExternalRepoRefError as exc:
        raise _unknown_repo_error(
            requested,
            host_ctx=host_ctx,
            inventory=inventory,
        ) from exc

    dest_dir = external_repo_clone_dir(
        host_checkout,
        *provider_ref.clone_parts,
    )
    return _ExternalRepoTarget(
        canonical_name=provider_ref.canonical_name,
        dest_dir=dest_dir,
        provider_ref=provider_ref,
    )


def _resolve_external_project_record(
    requested: str,
    *,
    host_ctx: ProjectContext,
) -> ProjectRecordWire | None:
    """Return one exact registered project match, excluding the host project."""

    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception as exc:
        raise ExternalRepoOpenError(
            f"Unable to inspect registered SASE projects: {exc}"
        ) from exc
    matches = [
        record
        for record in records
        if requested
        in {
            record.project_name,
            effective_project_name(record),
            *record.aliases,
        }
        and not _project_record_is_host(record, host_ctx)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = ", ".join(
            sorted(effective_project_name(record) for record in matches)
        )
        raise ExternalRepoOpenError(
            f"Project name '{requested}' is ambiguous: {candidates}"
        )
    return None


def _project_record_is_host(
    record: ProjectRecordWire,
    host_ctx: ProjectContext,
) -> bool:
    source = (record.workspace_dir or "").strip()
    if source:
        record_path = Path(source).expanduser().resolve(strict=False)
        host_path = (
            Path(host_ctx.primary_workspace_dir).expanduser().resolve(strict=False)
        )
        if record_path == host_path:
            return True
    return host_ctx.project_name in {
        record.project_name,
        effective_project_name(record),
        *record.aliases,
    }


def _unknown_repo_error(
    requested: str,
    *,
    host_ctx: ProjectContext,
    inventory: RepoInventory,
) -> ExternalRepoOpenError:
    valid_names = sorted(
        {
            record.name
            for record in inventory.records
            if record.project == host_ctx.project_name and record.kind != "external"
        }
        | {host_ctx.project_name}
    )
    candidates = ", ".join(valid_names) or "none"
    return ExternalRepoOpenError(
        f"Unknown repo '{requested}' for project '{host_ctx.project_name}'. "
        f"Valid repos: {candidates}. To open an external repo, use "
        "gh:owner/repo (or owner/repo)."
    )


def _materialize_external_repo(target: _ExternalRepoTarget) -> str:
    """Idempotently materialize *target* without cleaning a valid reopen."""

    dest = Path(target.dest_dir)
    if _is_valid_git_repo(dest):
        path = str(dest.resolve(strict=False))
    else:
        if os.path.lexists(dest):
            raise ExternalRepoOpenError(
                "External repo destination exists but is not a valid repository: "
                f"{dest}"
            )

        project_source_dir = target.project_source_dir
        if project_source_dir is not None:
            path = _atomic_external_clone(
                dest,
                lambda temp: _clone_external_project(project_source_dir, temp),
            )
        else:
            provider_ref = target.provider_ref
            if provider_ref is None:
                raise ExternalRepoOpenError("External repo target has no clone source.")
            path = _atomic_external_clone(
                dest,
                lambda temp: _clone_provider_external(provider_ref, temp),
            )

    from sase.workspace_provider.git_exclude import ensure_sase_git_info_excludes

    ensure_sase_git_info_excludes(path)
    return path


def _clone_external_project(source_dir: str, temp_dir: Path) -> None:
    """Clone a registered project's primary checkout into a staging path."""

    from sase.workspace_provider.utils import ensure_git_clone_at

    try:
        # A value above the primary range asks the shared helper to clone into
        # the caller-supplied path; the external identity remains host-scoped.
        ensure_git_clone_at(source_dir, 2, str(temp_dir))
    except (OSError, RuntimeError) as exc:
        raise ExternalRepoOpenError(
            f"Unable to clone external project from {source_dir}: {exc}"
        ) from exc


def _clone_provider_external(provider_ref: ExternalRepoRef, temp_dir: Path) -> None:
    """Dispatch one provider-owned clone into a core-owned staging path."""

    try:
        schemes = get_external_repo_schemes()
    except Exception as exc:
        raise ExternalRepoOpenError(
            "Unable to load external repo providers. Install or upgrade the "
            f"matching provider plugin: {exc}"
        ) from exc
    if provider_ref.scheme not in schemes:
        raise _missing_external_provider_error(provider_ref.scheme, schemes)
    try:
        result = clone_external_repo(
            provider_ref.scheme,
            provider_ref.ref,
            str(temp_dir),
        )
    except Exception as exc:
        raise ExternalRepoOpenError(str(exc)) from exc
    if result is None:
        raise _missing_external_provider_error(provider_ref.scheme, schemes)
    if result.canonical_name != provider_ref.canonical_name:
        raise ExternalRepoOpenError(
            "External repo provider returned canonical name "
            f"'{result.canonical_name}', expected '{provider_ref.canonical_name}'."
        )
    returned_dest = Path(result.dest_dir).expanduser().resolve(strict=False)
    if returned_dest != temp_dir.resolve(strict=False):
        raise ExternalRepoOpenError(
            "External repo provider cloned to an unexpected destination: "
            f"{returned_dest}"
        )


def _missing_external_provider_error(
    scheme: str,
    registered_schemes: set[str],
) -> ExternalRepoOpenError:
    registered = ", ".join(sorted(registered_schemes)) or "none"
    plugin_hint = "sase-github" if scheme == "gh" else "the matching provider plugin"
    return ExternalRepoOpenError(
        f"No workspace provider is registered for external repo scheme '{scheme}'. "
        f"Install or upgrade {plugin_hint}. Registered external schemes: {registered}."
    )


def _atomic_external_clone(
    dest: Path,
    clone_into: Callable[[Path], None],
) -> str:
    """Clone beside *dest* and atomically install a validated repository."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.parent / (f".{dest.name}.clone-tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        clone_into(temp)
        if not _is_valid_git_repo(temp):
            raise ExternalRepoOpenError(
                "External repo provider did not produce a valid Git repository."
            )
        if os.path.lexists(dest):
            if _is_valid_git_repo(dest):
                return str(dest.resolve(strict=False))
            raise ExternalRepoOpenError(
                f"External repo destination appeared but is invalid: {dest}"
            )
        os.replace(temp, dest)
        return str(dest.resolve(strict=False))
    except ExternalRepoOpenError:
        raise
    except OSError as exc:
        raise ExternalRepoOpenError(
            f"Unable to install external repo at {dest}: {exc}"
        ) from exc
    finally:
        _remove_clone_staging_path(temp)


def _is_valid_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _remove_clone_staging_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "ExternalRepoOpenError",
    "open_external_repo",
]
