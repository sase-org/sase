"""Top-level wait-dependency resolution status."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ._index import WaitDependencyIndex
from ._types import WaitDependencyStatus


def dependency_resolution_status(
    index: WaitDependencyIndex,
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object] = (),
    *,
    self_artifact_dir: str | Path | None = None,
) -> WaitDependencyStatus:
    failed: list[dict[str, str]] = []
    identity_names: set[str] = set()
    for dependency in wait_identity_deps:
        if not isinstance(dependency, Mapping):
            return WaitDependencyStatus("waiting")
        dependency_name = dependency.get("name")
        if isinstance(dependency_name, str) and dependency_name:
            identity_names.add(dependency_name)
        status = index.identity_status(
            dependency,
            exclude_artifact_dir=self_artifact_dir,
        )
        if status.failed:
            failed.extend(status.failed_dependencies)
        elif not status.resolved:
            return WaitDependencyStatus("waiting")
    if failed:
        return WaitDependencyStatus("failed", tuple(failed))

    for name in wait_names:
        if not isinstance(name, str):
            return WaitDependencyStatus("waiting")
        if name in identity_names:
            continue
        if not index.is_resolved(name, exclude_artifact_dir=self_artifact_dir):
            return WaitDependencyStatus("waiting")
    return WaitDependencyStatus("resolved")
