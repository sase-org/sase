"""Python bridge for content-verified VCS artifact materialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from sase.config import get_artifact_capture_max_history_scan
from sase.core.artifact_file_types import ArtifactFile, default_artifact_files_root
from sase.core.rust import require_rust_binding


def materialize_artifact_file(
    row: ArtifactFile,
    *,
    repositories: Iterable[object],
) -> Path | None:
    """Return live bytes for a stored or VCS-backed artifact-file row."""

    if row.path:
        return Path(row.path).expanduser().resolve(strict=False)
    if not row.is_vcs_backed or not row.sha256:
        return None

    repository = _repository_for_name(row.vcs_repo or "", repositories)
    if repository is None:
        return None
    checkout_paths = tuple(
        str(Path(str(path)).expanduser().resolve(strict=False))
        for path in cast(Iterable[object], getattr(repository, "checkout_paths", ()))
        if str(path)
    )
    if not checkout_paths:
        checkout_path = getattr(repository, "checkout_path", None)
        checkout_paths = () if checkout_path is None else (str(checkout_path),)

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
        return None
    path = result.get("path")
    if not isinstance(path, str) or not path:
        raise RuntimeError(
            "sase_core_rs materialized a VCS artifact without returning its path"
        )
    return Path(path).expanduser().resolve(strict=False)


def _repository_for_name(
    name: str,
    repositories: Iterable[object],
) -> object | None:
    for repository in repositories:
        aliases = getattr(repository, "aliases", ())
        if getattr(repository, "name", None) == name or name in aliases:
            return repository
    return None


__all__ = ["materialize_artifact_file"]
