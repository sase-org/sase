"""Fail-closed proof that reconciliation commits are attributable."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import FinalizerAttemptWire
from sase.finalizers import declaration_store as _declaration_store
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_matches_repo,
    new_commit_markers,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    failed_result,
)
from sase.finalizers.ledger import InstanceLedger
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_paths import normalize_status_path
from sase.llm_provider.commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult


def reject_unproven_reconciliation_transition(
    before: DirtyState,
    after: DirtyState,
    *,
    fingerprints_before: Mapping[str, Mapping[str, tuple[str, str | None]]] | None,
    artifacts: Path | None,
    ledger_before: Sequence[Mapping[str, Any]],
    instance_id: str,
    attempt: int,
    ledger: InstanceLedger | None,
    invoke_result: InvokeResult,
) -> None:
    """Fail closed when mixed auto-commits are not attributable."""

    after_by_id = {
        _declaration_store.repository_obligation_id(repo): repo for repo in after.repos
    }
    new_markers = new_commit_markers(ledger_before, load_commit_results(artifacts))
    for repo in before.repos:
        after_repo = after_by_id.get(_declaration_store.repository_obligation_id(repo))
        if after_repo is None:
            continue
        before_paths = set(repo.changed_files)
        after_paths = set(after_repo.changed_files)
        removed = before_paths - after_paths
        added = after_paths - before_paths
        remaining = before_paths & after_paths
        if added:
            _raise_stale_repository_changed(
                repo,
                instance_id,
                attempt=attempt,
                ledger=ledger,
                invoke_result=invoke_result,
            )
        if removed and not any(
            marker_matches_repo(marker, repo) for marker in new_markers
        ):
            if ledger is not None:
                attempt = ledger.allocate_attempt()
            message_text = (
                "Commit finalizer failed: dirty work vanished without an "
                f"attributable commit in {repo.name}"
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=failed_result(
                    instance_id,
                    "dirty_work_discarded",
                    message_text,
                    attempts=[
                        FinalizerAttemptWire(
                            attempt=attempt,
                            status="failed",
                            diagnostic_code="dirty_work_discarded",
                        )
                    ],
                ),
                invoke_result=invoke_result,
            )
        if not remaining or fingerprints_before is None:
            continue
        before_fp = fingerprints_before.get(
            normalize_path(repo.path), fingerprints_before.get(repo.path)
        )
        if before_fp is None:
            continue
        after_fp = _declaration_store.dirty_path_fingerprints(repo.path)
        if any(
            _path_fingerprint(before_fp, path) != _path_fingerprint(after_fp, path)
            for path in remaining
        ):
            _raise_stale_repository_changed(
                repo,
                instance_id,
                attempt=attempt,
                ledger=ledger,
                invoke_result=invoke_result,
            )


def _path_fingerprint(
    fingerprints: Mapping[str, tuple[str, str | None]],
    path: str,
) -> tuple[str, str | None] | None:
    if path in fingerprints:
        return fingerprints[path]
    return fingerprints.get(normalize_status_path(path))


def _raise_stale_repository_changed(
    repo: DirtyRepo,
    instance_id: str,
    *,
    attempt: int,
    ledger: InstanceLedger | None,
    invoke_result: InvokeResult,
) -> None:
    if ledger is not None:
        attempt = ledger.allocate_attempt()
    message_text = (
        f"commit declaration is stale; repository {repo.name} changed after submit"
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=failed_result(
            instance_id,
            "stale_commit_declaration",
            message_text,
            attempts=[
                FinalizerAttemptWire(
                    attempt=attempt,
                    status="failed",
                    diagnostic_code="stale_commit_declaration",
                )
            ],
        ),
        invoke_result=invoke_result,
    )
