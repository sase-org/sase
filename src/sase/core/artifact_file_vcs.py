"""Python bridge for content-verified VCS artifact materialization."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from sase.config import get_artifact_capture_max_history_scan
from sase.core.artifact_file_types import ArtifactFile, default_artifact_files_root
from sase.core.rust import require_rust_binding

log = logging.getLogger(__name__)


class ArtifactFileRepositoryResolver:
    """Resolve VCS rows to checkouts, preferring the row's owning project.

    The resolver memoizes owner-project repository lookups per
    ``(project, workspace_num)`` for its own lifetime. Create one resolver
    per call or per batch, never a process-global instance, so long-lived
    TUI processes pick up new clones.

    ``fallback`` supplies today's caller (cwd-derived) repositories. It may
    be an iterable or a zero-arg callable returning one. A callable is
    evaluated lazily and at most once, so batches that resolve every row by
    owner never pay for ``launch_artifact_ref_context``.
    """

    def __init__(
        self,
        fallback: Iterable[object] | Callable[[], Iterable[object]] | None = (),
    ) -> None:
        self._fallback = fallback if fallback is not None else ()
        self._fallback_evaluated = False
        self._fallback_cache: tuple[object, ...] = ()
        self._owner_cache: dict[tuple[str, int], tuple[object, ...] | None] = {}

    def repository_for_row(self, row: ArtifactFile) -> object | None:
        """Return the checkout record for *row*, owner project first."""

        owner_repositories = self._owner_repositories_for_row(row)
        if owner_repositories is not None:
            repository = _repository_for_name(row.vcs_repo or "", owner_repositories)
            if repository is not None:
                return repository
        return _repository_for_name(row.vcs_repo or "", self._fallback_repositories())

    def _owner_repositories_for_row(
        self, row: ArtifactFile
    ) -> tuple[object, ...] | None:
        project = getattr(row, "project", None)
        if not project or not isinstance(project, str):
            return None
        workspace_num = _workspace_num_for_row(row)
        key = (project, workspace_num)
        if key not in self._owner_cache:
            try:
                from sase.artifact_ref_context import artifact_ref_repositories

                repositories = artifact_ref_repositories(
                    project=project,
                    workspace_num=workspace_num,
                )
            except Exception:
                log.debug(
                    "Owner-project repository lookup failed for %r",
                    project,
                    exc_info=True,
                )
                repositories = None
            self._owner_cache[key] = repositories
        return self._owner_cache[key]

    def _fallback_repositories(self) -> tuple[object, ...]:
        if not self._fallback_evaluated:
            fallback = self._fallback
            resolved = fallback() if callable(fallback) else fallback
            self._fallback_cache = () if resolved is None else tuple(resolved)
            self._fallback_evaluated = True
        return self._fallback_cache


def materialize_artifact_file(
    row: ArtifactFile,
    *,
    repositories: Iterable[object] = (),
    resolver: ArtifactFileRepositoryResolver | None = None,
) -> Path | None:
    """Return live bytes for a stored or VCS-backed artifact-file row.

    Resolution is owner-first: when ``row.project`` names a known project,
    ``row.vcs_repo`` is matched against that project's repositories before
    the caller-supplied ``repositories`` fallback. When ``resolver`` is
    given, ``repositories`` is ignored. When ``resolver`` is ``None``, a
    one-shot resolver is built whose fallback is ``repositories``, so
    existing callers automatically gain owner-first behavior.
    """

    if row.path:
        return Path(row.path).expanduser().resolve(strict=False)
    if not row.is_vcs_backed or not row.sha256:
        return None

    active = (
        resolver
        if resolver is not None
        else ArtifactFileRepositoryResolver(fallback=repositories)
    )
    repository = active.repository_for_row(row)
    if repository is None:
        checkout_paths: list[str] = []
    else:
        checkout_paths = _checkout_paths_for_repository(repository)

    assert row.vcs_sha is not None
    assert row.vcs_relpath is not None
    binding = require_rust_binding("artifact_file_materialize_vcs")
    raw = binding(
        {
            "cache_root": str(default_artifact_files_root() / "vcs-cache"),
            "checkout_paths": list(dict.fromkeys(checkout_paths)),
            "vcs_sha": row.vcs_sha,
            "vcs_relpath": row.vcs_relpath,
            "sha256": row.sha256,
            "suffix": Path(row.vcs_relpath).suffix,
            "max_history_scan": get_artifact_capture_max_history_scan(),
        }
    )
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible VCS artifact materialization result"
        )
    result = cast(Mapping[str, Any], raw)
    if result.get("status") not in {"cached", "materialized"}:
        log.debug(
            "VCS artifact materialization missing for row %r (project %r): "
            "checkouts_tried=%r",
            getattr(row, "id", None),
            getattr(row, "project", None),
            result.get("checkouts_tried"),
        )
        return None
    path = result.get("path")
    if not isinstance(path, str) or not path:
        raise RuntimeError(
            "sase_core_rs materialized a VCS artifact without returning its path"
        )
    return Path(path).expanduser().resolve(strict=False)


def _workspace_num_for_row(row: ArtifactFile) -> int:
    """Return the checkout-ordering workspace number for *row*.

    Reads the checkout marker at ``row.workspace_dir`` and uses its
    ``workspace_num`` when the marker's project matches the row's owning
    project. Otherwise returns ``0`` (the primary). This only orders
    candidates; every existing clone is still tried.
    """

    workspace_dir = getattr(row, "workspace_dir", None)
    if not workspace_dir or not isinstance(workspace_dir, str):
        return 0
    if not workspace_dir.strip():
        return 0
    try:
        from sase.workspace_provider.marker import (
            find_marker_from_cwd,
            read_marker,
        )

        found = find_marker_from_cwd(workspace_dir)
        marker = found[1] if found is not None else read_marker(workspace_dir)
    except Exception:
        return 0
    if marker is None:
        return 0
    project = getattr(row, "project", None)
    if project and project in (marker.project_name, marker.project_key):
        try:
            return int(marker.workspace_num)
        except (TypeError, ValueError):
            return 0
    return 0


def _checkout_paths_for_repository(repository: object) -> list[str]:
    paths = tuple(
        str(Path(str(path)).expanduser().resolve(strict=False))
        for path in cast(Iterable[object], getattr(repository, "checkout_paths", ()))
        if str(path)
    )
    if paths:
        return list(paths)
    checkout_path = getattr(repository, "checkout_path", None)
    if checkout_path is None:
        return []
    return [str(checkout_path)]


def _repository_for_name(
    name: str,
    repositories: Iterable[object],
) -> object | None:
    for repository in repositories:
        aliases = getattr(repository, "aliases", ())
        if getattr(repository, "name", None) == name or name in aliases:
            return repository
    return None


__all__ = ["ArtifactFileRepositoryResolver", "materialize_artifact_file"]
