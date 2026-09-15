"""Patchable side-effect hooks for plan-file bead launches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sase.bead.project import BeadProject
from sase.sdd.store import SddStore


class _CommitPlanFile(Protocol):
    def __call__(
        self,
        store: SddStore,
        *,
        workspace_dir: Path,
        plan_path: Path,
        message: str,
    ) -> bool: ...


class _WriteAndCommitPlanFile(Protocol):
    def __call__(
        self,
        store: SddStore,
        *,
        workspace_dir: Path,
        plan_path: Path,
        content: str,
        message: str,
    ) -> bool: ...


class _CheckpointAndPublishGraph(Protocol):
    def __call__(
        self,
        *,
        store: SddStore,
        project: BeadProject,
        epic_id: str,
        no_push: bool,
        render: bool,
    ) -> Any: ...


class _PublishEpicGraphBeforeLaunch(Protocol):
    def __call__(self, store: SddStore, *, no_push: bool) -> Any: ...


class _PublishEpicRollback(Protocol):
    def __call__(self, store: SddStore) -> bool: ...


class _PushStoreAfterLaunch(Protocol):
    def __call__(
        self,
        store: SddStore,
        *,
        no_push: bool,
        archived_plan_path: Path | None = None,
    ) -> None: ...


class _RequirePlanStoreHealth(Protocol):
    def __call__(self, store: SddStore) -> None: ...


@dataclass(frozen=True)
class PlanFileWorkLaunchHooks:
    """Patchable side-effect hooks supplied by the public adapter module."""

    commit_plan_file: _CommitPlanFile
    write_and_commit_plan_file: _WriteAndCommitPlanFile
    checkpoint_and_publish_graph: _CheckpointAndPublishGraph
    publish_epic_graph_before_launch: _PublishEpicGraphBeforeLaunch
    publish_epic_rollback: _PublishEpicRollback
    push_store_after_launch: _PushStoreAfterLaunch
    require_plan_store_health: _RequirePlanStoreHealth


__all__ = ["PlanFileWorkLaunchHooks"]
