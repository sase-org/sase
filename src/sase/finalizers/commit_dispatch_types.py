"""Shared types and small helpers for commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDeferralWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_baseline import FinalizerBaselineRecord
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult

PrepareDirtyState = Callable[[str, Path | None], PreparedCommitDirtyState]
ProtectedPathResolver = Callable[[Path | None, str], Sequence[str]]
UnexpectedPathResolver = Callable[[str, Sequence[str]], list[str]]
BaselineRecordResolver = Callable[[Path | None, str], FinalizerBaselineRecord | None]


@dataclass(frozen=True)
class DeferredRepoOutcome:
    """One repository whose accepted deferral skipped its stitch."""

    repo: DirtyRepo
    deferral: FinalizerDeferralWire


@dataclass(frozen=True)
class CommitDispatchResult:
    """State accumulated while dispatching accepted repository decisions."""

    invoke_result: InvokeResult
    state: PreparedCommitDirtyState
    attempt_id: int | None
    attempts: list[FinalizerAttemptWire]
    evidence: list[FinalizerOutcomeEvidenceWire]
    deferred: tuple[DeferredRepoOutcome, ...] = ()
    diagnostics: tuple[FinalizerDiagnosticWire, ...] = ()


@dataclass(frozen=True)
class PostRepairFollowUpResult:
    """Outcome from the single allowed post-repair follow-up stitch."""

    remaining: list[str]
    failure_reason: str | None = None


def merge_deferrals(
    deferred: Sequence[DeferredRepoOutcome],
) -> FinalizerDeferralWire:
    """Combine one dispatch's deferred repositories into one wire record.

    The result wire carries a single typed reason, so a mixed-reason dispatch
    keeps the first repository's reason; every deferred path across every
    repository is still recorded, and the full per-repository detail lives in
    the ``deferred_repo`` evidence entries.
    """

    reason = deferred[0].deferral.reason
    paths: list[str] = []
    seen: set[str] = set()
    for item in deferred:
        for path in item.deferral.paths:
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return FinalizerDeferralWire(reason=reason, paths=paths)


def preflight_attempt(ledger: InstanceLedger | None) -> int:
    if ledger is None:
        return 1
    return ledger.allocate_attempt()


def peek_attempt(ledger: InstanceLedger | None) -> int:
    if ledger is None:
        return 1
    return ledger.next_attempt


__all__ = [
    "BaselineRecordResolver",
    "CommitDispatchResult",
    "DeferredRepoOutcome",
    "PrepareDirtyState",
    "ProtectedPathResolver",
    "PostRepairFollowUpResult",
    "UnexpectedPathResolver",
    "merge_deferrals",
    "peek_attempt",
    "preflight_attempt",
]
