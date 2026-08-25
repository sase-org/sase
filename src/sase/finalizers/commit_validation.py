"""State and result validation for the built-in commit finalizer.

Commit protection reads ``finalizer_baseline.json`` through the same canonical
record loader as model-visible provenance. That keeps the protected-path view
and the declaration evidence view from making contradictory ownership claims
for the same normalized repository path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import logging
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_repair import (
    load_commit_results as _load_commit_results,
    new_commit_markers as _new_commit_markers,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    failed_result as _failed_result,
)
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FinalizerBaselineRecord,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import (
    discarded_dirty_work_evidence,
    discarded_dirty_work_message,
    normalize_path,
    split_pre_existing_changed_files,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult

_logger = logging.getLogger(__name__)


def raise_if_unpublished_machine_state(
    state: PreparedCommitDirtyState,
    *,
    instance_id: str,
    invoke_result: InvokeResult,
    attempts: Sequence[FinalizerAttemptWire] = (),
    evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
) -> None:
    if state.bead_publication_error is not None:
        result = _failed_result(
            instance_id,
            "bead_state_unpublished",
            state.bead_publication_error,
            attempts=attempts,
            evidence=evidence,
        )
        raise BuiltinCommitFinalizerError(
            state.bead_publication_error,
            result=result,
            invoke_result=invoke_result,
        )
    if state.artifact_link_publication_error is None:
        return
    result = _failed_result(
        instance_id,
        "artifact_links_unpublished",
        state.artifact_link_publication_error,
        attempts=attempts,
        evidence=evidence,
    )
    raise BuiltinCommitFinalizerError(
        state.artifact_link_publication_error,
        result=result,
        invoke_result=invoke_result,
    )


def protected_baseline_paths(
    artifacts: Path | None,
    repo_path: str,
    *,
    get_changed_files: Callable[[str], list[str]],
) -> tuple[str, ...]:
    if artifacts is None:
        return ()
    baseline = _load_baseline_fingerprints(artifacts, repo_path)
    if not baseline:
        return ()
    changed = get_changed_files(repo_path)
    _still, pre_existing = split_pre_existing_changed_files(
        repo_path,
        changed,
        baseline,
    )
    return tuple(sorted(pre_existing))


def _load_baseline_fingerprints(
    artifacts: Path,
    repo_path: str,
) -> dict[str, tuple[str, str | None]]:
    normalized_repo = normalize_path(repo_path)
    records = load_finalizer_baseline_records(artifacts)
    if records is None:
        return _read_legacy_baseline(artifacts, normalized_repo)
    record = _record_for_path(records, normalized_repo)
    return dict(record.fingerprints) if record is not None else {}


def protected_baseline_record(
    artifacts: Path | None,
    repo_path: str,
) -> FinalizerBaselineRecord | None:
    """Return the canonical baseline record protecting *repo_path*, if any.

    Used to explain, not just enforce, protection: a refused dispatch names
    the record's ``scope``, ``repo_id``, and ``captured_at`` so an operator
    does not have to reconstruct the exclude from source.
    """
    if artifacts is None:
        return None
    records = load_finalizer_baseline_records(artifacts)
    if records is None:
        return None
    return _record_for_path(records, normalize_path(repo_path))


def _record_for_path(
    records: Sequence[FinalizerBaselineRecord],
    normalized_repo: str,
) -> FinalizerBaselineRecord | None:
    for record in records:
        if record.path == normalized_repo:
            return record
    return None


def protection_exhausted_message(
    repo: DirtyRepo,
    protected: Sequence[str],
    record: FinalizerBaselineRecord | None,
) -> str:
    """Explain why every changed path in *repo* is already protected."""
    lines = [
        f"sase stitch create was not run for {repo.name}: protection already "
        "excludes every changed path in this repository, so the commit is "
        "guaranteed to fail with nothing staged.",
        f"protected paths: {', '.join(sorted(protected))}",
    ]
    if record is not None:
        lines.append(
            "protected by baseline record "
            f"repo_id={record.repo_id!r} scope={record.scope!r} "
            f"captured_at={record.captured_at or 'unknown'}"
        )
    else:
        lines.append("no baseline record could be located to explain the protection")
    lines.append(
        "Submit a deferral with reason 'protected_paths' for this repository "
        "instead of a commit action."
    )
    return "\n".join(lines)


def _read_legacy_baseline(
    artifacts: Path,
    normalized_repo: str,
) -> dict[str, tuple[str, str | None]]:
    try:
        payload = json.loads(
            (artifacts / BASELINE_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    raw = payload.get(normalized_repo)
    return _normalize_fingerprints(raw) if isinstance(raw, Mapping) else {}


def _normalize_fingerprints(
    raw: Mapping[str, Any],
) -> dict[str, tuple[str, str | None]]:
    normalized: dict[str, tuple[str, str | None]] = {}
    for path, value in raw.items():
        if (
            isinstance(path, str)
            and isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
            and (value[1] is None or isinstance(value[1], str))
        ):
            normalized[path] = (value[0], value[1])
    return normalized


def unexpected_remaining_paths(
    repo_path: str,
    protected: Sequence[str],
    *,
    get_changed_files: Callable[[str], list[str]],
) -> list[str]:
    protected_set = set(protected)
    return [path for path in get_changed_files(repo_path) if path not in protected_set]


def _marker_commit_sha(marker: Mapping[str, Any]) -> str | None:
    for key in ("commit_sha", "result"):
        value = marker.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("http"):
            return value
    return None


def reconcile_commit_file_hooks(
    repo: DirtyRepo,
    marker: Mapping[str, Any],
    *,
    workspace_dir: str,
) -> None:
    """Ensure the deterministic commit batch exists after a verified marker."""
    try:
        from sase.agent.identity import resolve_local_agent_name
        from sase.file_hooks.producer import reconcile_commit_file_hooks

        sidecar_role = repo.name if repo.kind == "sdd" else None
        reconcile_commit_file_hooks(
            repo_root=repo.path,
            commit_sha=_marker_commit_sha(marker),
            workspace_dir=workspace_dir,
            sidecar_role=sidecar_role,
            agent_name=resolve_local_agent_name(),
        )
    except Exception:
        _logger.warning(
            "File-hook finalizer reconciliation failed; continuing",
            exc_info=True,
        )


def reject_discarded_dirty_work(
    before: DirtyState,
    after: DirtyState,
    *,
    artifacts: Path | None,
    project_dir: str,
    instance_id: str,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    invoke_result: InvokeResult,
    ledger_before: Sequence[Mapping[str, Any]],
) -> None:
    discarded = discarded_dirty_work_evidence(
        before,
        after,
        artifacts_dir=str(artifacts) if artifacts is not None else None,
    )
    proven = {
        normalize_path(str(marker.get("cwd", "")))
        for marker in _new_commit_markers(
            ledger_before, _load_commit_results(artifacts)
        )
        if marker.get("cwd")
    }
    remaining = tuple(
        item for item in discarded if normalize_path(item.repo_path) not in proven
    )
    if not remaining:
        return
    message_text = discarded_dirty_work_message(remaining)
    result = _failed_result(
        instance_id,
        "dirty_work_discarded",
        message_text,
        attempts=attempts,
        evidence=evidence,
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=result,
        invoke_result=invoke_result,
    )
