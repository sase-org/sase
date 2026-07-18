"""Top-level wait-dependency resolution status."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ._artifact_state import same_artifact_dir
from ._index import WaitDependencyIndex
from ._types import WaitDependencyStatus


def dependency_resolution_status(
    index: WaitDependencyIndex,
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    *,
    self_artifact_dir: str | Path | None = None,
) -> WaitDependencyStatus:
    resolved_dep_items = tuple(resolved_deps)
    waiter_launch_cutoff = (
        Path(self_artifact_dir).name if self_artifact_dir is not None else None
    )
    identity_names: set[str] = set()
    for dependency in wait_identity_deps:
        if not isinstance(dependency, Mapping):
            return WaitDependencyStatus("waiting")
        dependency_name = dependency.get("name")
        if isinstance(dependency_name, str) and dependency_name:
            identity_names.add(dependency_name)
        if _identity_dependency_is_memoized(dependency, resolved_dep_items):
            continue
        status = index.identity_status(
            dependency,
            exclude_artifact_dir=self_artifact_dir,
        )
        if not status.resolved:
            return WaitDependencyStatus("waiting")

    for name in wait_names:
        if not isinstance(name, str):
            return WaitDependencyStatus("waiting")
        if name in identity_names:
            continue
        if name in resolved_dep_items:
            continue
        if not index.is_resolved(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            return WaitDependencyStatus("waiting")
    return WaitDependencyStatus("resolved")


def _identity_dependency_is_memoized(
    dependency: Mapping[str, Any],
    resolved_deps: Iterable[object],
) -> bool:
    for memo in resolved_deps:
        if not isinstance(memo, Mapping):
            continue
        dependency_artifact_dir = dependency.get("artifact_dir")
        memo_artifact_dir = memo.get("artifact_dir")
        if (
            isinstance(dependency_artifact_dir, str)
            and dependency_artifact_dir
            and isinstance(memo_artifact_dir, str)
            and memo_artifact_dir
            and same_artifact_dir(dependency_artifact_dir, memo_artifact_dir)
        ):
            return True
        dependency_project = dependency.get("project_name")
        dependency_timestamp = dependency.get("timestamp")
        if (
            isinstance(dependency_project, str)
            and dependency_project
            and isinstance(dependency_timestamp, str)
            and dependency_timestamp
            and memo.get("project_name") == dependency_project
            and memo.get("timestamp") == dependency_timestamp
        ):
            return True
    return False
