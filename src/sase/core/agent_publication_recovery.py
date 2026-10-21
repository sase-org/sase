"""Rust-backed policy facade for agent publication recovery.

This module keeps the original import surface while the publication and
replay responsibilities live in focused sibling modules:

- :mod:`sase.core.agent_publication_recovery_publication` — retry,
  accounting, drain, completion, and deferred-prompt decisions.
- :mod:`sase.core.agent_publication_recovery_replay` — replay path,
  byte-divergence, hood-merge, and apply decisions.
- :mod:`sase.core._agent_publication_recovery_shared` — wire validation
  shared by the sibling modules.

This module keeps the historic ``require_rust_binding`` monkeypatch seam
as a settable attribute and copies the live value into the implementation
modules before each delegated call, so patching
``sase.core.agent_publication_recovery.require_rust_binding`` behaves
exactly as it did when this file held the implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any

from sase.core._agent_publication_recovery_shared import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
)
from sase.core.agent_publication_recovery_publication import (
    PUBLICATION_ERROR_INDEX_LOCK,
    PUBLICATION_ERROR_LOCK_BUSY,
    PUBLICATION_ERROR_MANIFEST_MISMATCH,
    PUBLICATION_ERROR_OTHER,
    PUBLICATION_ERROR_REBASE_CONFLICT,
    PUBLICATION_ERROR_TIMEOUT,
    PUBLICATION_ERROR_UNKNOWN,
    PUBLICATION_ERROR_UNSTAGED_CHANGES,
    PUBLICATION_FAILURE_SCOPE_HOOD,
    PUBLICATION_FAILURE_SCOPE_REPOSITORY,
    PUBLICATION_FAILURE_SCOPE_UNKNOWN,
    PUBLICATION_KIND_RUN,
    PUBLICATION_KIND_SESSION,
    PUBLICATION_LIFECYCLE_ACTIVE,
    PUBLICATION_LIFECYCLE_QUARANTINED,
    PUBLICATION_LIFECYCLE_RETIRED,
    PROMPT_STATUS_ALREADY_ARCHIVED,
    PROMPT_STATUS_FAILED,
    PROMPT_STATUS_NOT_APPLICABLE,
    PROMPT_STATUS_RESTORED,
    PROMPT_STATUS_UNAVAILABLE,
    DeferredPromptDecision,
    PublicationCompletionDecision,
    PublicationDrainSelection,
    PublicationFailureAccounting,
    PublicationFailureCharge,
    PublicationRetrySelected,
)
from sase.core.agent_publication_recovery_replay import (
    REPLAY_APPLY_ACTION_ALREADY_COMPLETE,
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_APPLY_ACTION_REFUSE,
    REPLAY_APPLY_ACTION_REPORT,
    REPLAY_BYTES_KEEP_CURRENT,
    REPLAY_BYTES_KEEP_PREVIOUS,
    REPLAY_BYTES_REFUSE,
    REPLAY_HOOD_ACTION_MERGE,
    REPLAY_HOOD_ACTION_REFUSE,
    REPLAY_PATH_ARCHIVE_OBJECT,
    REPLAY_PATH_BROWSING,
    REPLAY_PATH_OWNER_CONTENT,
    REPLAY_PATH_UNKNOWN,
    ReplayApplyDecision,
    ReplayByteDivergenceDecision,
    ReplayHoodMergeDecision,
    ReplayPathClassification,
)
from sase.core.rust import require_rust_binding

publication_impl: Any = None
replay_impl: Any = None


def _sync_publication_patchables() -> None:
    global publication_impl
    if publication_impl is None:
        publication_impl = import_module(
            "sase.core.agent_publication_recovery_publication"
        )
    publication_impl.require_rust_binding = require_rust_binding


def _sync_replay_patchables() -> None:
    global replay_impl
    if replay_impl is None:
        replay_impl = import_module("sase.core.agent_publication_recovery_replay")
    replay_impl.require_rust_binding = require_rust_binding


def classify_publication_error(error: str | None) -> str:
    """Return the stable failure class for one publication error message."""
    _sync_publication_patchables()
    return publication_impl.classify_publication_error(error)


def select_publication_retries(
    rows: Sequence[Mapping[str, Any]],
    *,
    retry_retired: bool,
    retry_quarantined: bool,
    limit: int | None = None,
    error_classes: Sequence[str] | None = None,
) -> tuple[PublicationRetrySelected, ...]:
    """Return the terminal rows one explicit retry should revive."""
    _sync_publication_patchables()
    return publication_impl.select_publication_retries(
        rows,
        retry_retired=retry_retired,
        retry_quarantined=retry_quarantined,
        limit=limit,
        error_classes=error_classes,
    )


def decide_publication_failure_accounting(
    *,
    error: str,
    scope: str | None = None,
    attempted_keys: Sequence[Mapping[str, Any] | tuple[str, str]] = (),
    rows: Sequence[Mapping[str, Any]] = (),
    format_error: bool = False,
    quarantine_threshold: int | None = None,
) -> PublicationFailureAccounting:
    """Decide whether a failure may charge the host-supplied attempted keys."""
    _sync_publication_patchables()
    return publication_impl.decide_publication_failure_accounting(
        error=error,
        scope=scope,
        attempted_keys=attempted_keys,
        rows=rows,
        format_error=format_error,
        quarantine_threshold=quarantine_threshold,
    )


def select_publication_drain(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    preferred_key: tuple[str, str] | Mapping[str, Any] | None = None,
    retry_retired: bool = False,
    retry_quarantined: bool = False,
    error_classes: Sequence[str] | None = None,
) -> PublicationDrainSelection:
    """Select at most *limit* distinct logical requests for one drain."""
    _sync_publication_patchables()
    return publication_impl.select_publication_drain(
        rows,
        limit=limit,
        preferred_key=preferred_key,
        retry_retired=retry_retired,
        retry_quarantined=retry_quarantined,
        error_classes=error_classes,
    )


def decide_publication_request_completion(
    *,
    global_agent: str,
    local_agent: str,
    primary_revision: str,
    pages: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]] = (),
    containers: Sequence[Mapping[str, Any]] = (),
) -> PublicationCompletionDecision:
    """Decide whether a request's canonical page and revision are present."""
    _sync_publication_patchables()
    return publication_impl.decide_publication_request_completion(
        global_agent=global_agent,
        local_agent=local_agent,
        primary_revision=primary_revision,
        pages=pages,
        runs=runs,
        containers=containers,
    )


def classify_deferred_prompt_obligation(
    *,
    restore_wrote: bool,
    restore_error: str | None,
    local_source_present: bool,
    archive_present: bool,
    prompt_file_in_snapshot: bool | None,
) -> DeferredPromptDecision:
    """Classify one deferred prompt as restored, archived, n/a, unavailable, or failed."""
    _sync_publication_patchables()
    return publication_impl.classify_deferred_prompt_obligation(
        restore_wrote=restore_wrote,
        restore_error=restore_error,
        local_source_present=local_source_present,
        archive_present=archive_present,
        prompt_file_in_snapshot=prompt_file_in_snapshot,
    )


def classify_replay_paths(
    paths: Sequence[str],
) -> ReplayPathClassification:
    """Classify sidecar paths through ``sase_core_rs``."""
    _sync_replay_patchables()
    return replay_impl.classify_replay_paths(paths)


def decide_replay_byte_divergence(
    current: bytes,
    previous: bytes,
    base: bytes | None = None,
) -> ReplayByteDivergenceDecision:
    """Decide whether same-run bytes can be retained without losing changes."""
    _sync_replay_patchables()
    return replay_impl.decide_replay_byte_divergence(current, previous, base)


def decide_replay_hood_merge(
    *,
    local_owner_username: str,
    local_owner_machine: str,
    local_hood: str,
    upstream_owner_username: str,
    upstream_owner_machine: str,
    upstream_hood: str,
) -> ReplayHoodMergeDecision:
    """Decide whether a same-owner hood may merge through snapshot preservation."""
    _sync_replay_patchables()
    return replay_impl.decide_replay_hood_merge(
        local_owner_username=local_owner_username,
        local_owner_machine=local_owner_machine,
        local_hood=local_hood,
        upstream_owner_username=upstream_owner_username,
        upstream_owner_machine=upstream_owner_machine,
        upstream_hood=upstream_hood,
    )


def decide_replay_apply(
    *,
    apply: bool,
    observed_head: str,
    expected_head: str,
    backup_complete: bool,
    backup_verified: bool,
    unreconcilable: bool,
    already_complete: bool,
    mutation_started: bool,
) -> ReplayApplyDecision:
    """Admit, refuse, or report a stale-replay apply against backup and HEAD facts."""
    _sync_replay_patchables()
    return replay_impl.decide_replay_apply(
        apply=apply,
        observed_head=observed_head,
        expected_head=expected_head,
        backup_complete=backup_complete,
        backup_verified=backup_verified,
        unreconcilable=unreconcilable,
        already_complete=already_complete,
        mutation_started=mutation_started,
    )


__all__ = [
    "DeferredPromptDecision",
    "PROMPT_STATUS_ALREADY_ARCHIVED",
    "PROMPT_STATUS_FAILED",
    "PROMPT_STATUS_NOT_APPLICABLE",
    "PROMPT_STATUS_RESTORED",
    "PROMPT_STATUS_UNAVAILABLE",
    "PUBLICATION_ERROR_INDEX_LOCK",
    "PUBLICATION_ERROR_LOCK_BUSY",
    "PUBLICATION_ERROR_MANIFEST_MISMATCH",
    "PUBLICATION_ERROR_OTHER",
    "PUBLICATION_ERROR_REBASE_CONFLICT",
    "PUBLICATION_ERROR_TIMEOUT",
    "PUBLICATION_ERROR_UNKNOWN",
    "PUBLICATION_ERROR_UNSTAGED_CHANGES",
    "PUBLICATION_FAILURE_SCOPE_HOOD",
    "PUBLICATION_FAILURE_SCOPE_REPOSITORY",
    "PUBLICATION_FAILURE_SCOPE_UNKNOWN",
    "PUBLICATION_KIND_RUN",
    "PUBLICATION_KIND_SESSION",
    "PUBLICATION_LIFECYCLE_ACTIVE",
    "PUBLICATION_LIFECYCLE_QUARANTINED",
    "PUBLICATION_LIFECYCLE_RETIRED",
    "PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION",
    "PublicationCompletionDecision",
    "PublicationDrainSelection",
    "PublicationFailureAccounting",
    "PublicationFailureCharge",
    "PublicationRetrySelected",
    "REPLAY_APPLY_ACTION_ALREADY_COMPLETE",
    "REPLAY_APPLY_ACTION_APPLY",
    "REPLAY_APPLY_ACTION_REFUSE",
    "REPLAY_APPLY_ACTION_REPORT",
    "REPLAY_BYTES_KEEP_CURRENT",
    "REPLAY_BYTES_KEEP_PREVIOUS",
    "REPLAY_BYTES_REFUSE",
    "REPLAY_HOOD_ACTION_MERGE",
    "REPLAY_HOOD_ACTION_REFUSE",
    "REPLAY_PATH_ARCHIVE_OBJECT",
    "REPLAY_PATH_BROWSING",
    "REPLAY_PATH_OWNER_CONTENT",
    "REPLAY_PATH_UNKNOWN",
    "ReplayApplyDecision",
    "ReplayByteDivergenceDecision",
    "ReplayHoodMergeDecision",
    "ReplayPathClassification",
    "classify_deferred_prompt_obligation",
    "classify_publication_error",
    "classify_replay_paths",
    "decide_publication_failure_accounting",
    "decide_publication_request_completion",
    "decide_replay_apply",
    "decide_replay_byte_divergence",
    "decide_replay_hood_merge",
    "select_publication_drain",
    "select_publication_retries",
]
