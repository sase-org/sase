"""Typed results returned by prompt-completion inventory workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.widgets.prompt_commit_inventory import PromptCommitSnapshot
from sase.ace.tui.widgets.prompt_path_inventory import PromptPathSnapshot
from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult


@dataclass(frozen=True)
class VcsRepoCompletionWorkerResult:
    """Result returned by a repository completion fetch worker."""

    workflow: str
    namespace: str
    result: VcsRepoFetchResult

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow, self.namespace)


@dataclass(frozen=True)
class PromptPathInventoryWorkerResult:
    """Result returned by a prompt path inventory worker."""

    snapshot: PromptPathSnapshot
    changed: bool


@dataclass(frozen=True)
class PromptCommitInventoryWorkerResult:
    """Result returned by a prompt commit inventory worker."""

    snapshot: PromptCommitSnapshot
    changed: bool


@dataclass(frozen=True)
class WaitBeadInventoryWorkerResult:
    """Result returned by a prompt wait-bead inventory worker."""

    project_key: str
    rows: tuple[dict[str, str], ...]
    available: bool


@dataclass(frozen=True)
class FinalizerInventoryWorkerResult:
    """Result returned by a prompt finalizer-catalog worker."""

    rows: tuple[dict[str, object], ...]
    available: bool


@dataclass(frozen=True)
class MachineInventoryWorkerResult:
    """Result returned by a prompt dispatch-machine inventory worker."""

    rows: tuple[dict[str, str], ...]
    available: bool


@dataclass(frozen=True)
class ModelCompletionCatalogWorkerResult:
    """Result returned by a model completion catalog worker."""

    rows: tuple[Any, ...]
    available: bool
