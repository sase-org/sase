"""Submit-time adjudication for typed commit finalizer deferrals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FINALIZER_DEFERRAL_REASONS,
    FinalizerContextWire,
    FinalizerPlanWire,
)
from sase.finalizers.commit_validation import protected_baseline_paths
from sase.finalizers.declaration_manifest import (
    CommitDeferralDecision,
    commit_deferral_decisions_for_payload,
)
from sase.finalizers.declaration_recovery_evidence import (
    direct_written_paths,
    written_paths_from_tool_calls,
)
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    HostRepositoryRecord,
)
from sase.llm_provider.commit_finalizer_baseline import (
    DirtyBaseline,
    load_dirty_baseline,
)
from sase.llm_provider.commit_finalizer_git import (
    git_changed_files,
    normalize_path,
    split_pre_existing_changed_files,
)
from sase.telemetry.metrics import FINALIZER_DEFERRALS


@dataclass(frozen=True)
class _AcceptedCommitDeferral:
    """One deferral the host could not refute at submit time."""

    instance_id: str
    repo_id: str
    repo_display_name: str
    reason: str
    paths: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo_id": self.repo_id,
            "repo_display_name": self.repo_display_name,
            "reason": self.reason,
            "paths": list(self.paths),
        }


def adjudicate_commit_deferrals(
    plan: FinalizerPlanWire,
    context: FinalizerContextWire,
    envelope: Mapping[str, Any],
    *,
    root: Path,
    host_records: tuple[HostRepositoryRecord, ...],
) -> tuple[_AcceptedCommitDeferral, ...]:
    """Validate typed deferrals against host evidence without mutating state."""

    commit_instances = {
        entry.instance_id
        for entry in plan.entries
        if entry.provider_ref == "builtin@commit"
    }
    if not commit_instances:
        return ()

    host_by_id = {record.obligation_id: record for record in host_records}
    display_by_id = {
        obligation.obligation_id: obligation.display_name or obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    }
    baseline = load_dirty_baseline(root)
    written_paths = written_paths_from_tool_calls(root)

    accepted: list[_AcceptedCommitDeferral] = []
    for instance_id, payload in _commit_payloads(envelope, commit_instances):
        for decision in commit_deferral_decisions_for_payload(context, payload):
            record = host_by_id.get(decision.repo_id)
            if record is None:
                raise FinalizerDeclarationError(
                    "commit deferral cannot be adjudicated; missing host identity "
                    f"for repository obligation {decision.repo_id}",
                    code="commit_deferral_rejected",
                )
            accepted.append(
                _adjudicate_decision_with_telemetry(
                    instance_id,
                    decision,
                    record,
                    repo_display_name=display_by_id.get(
                        decision.repo_id, decision.repo_id
                    ),
                    root=root,
                    baseline=baseline,
                    written_paths=written_paths,
                )
            )
    return tuple(accepted)


def _adjudicate_decision_with_telemetry(
    instance_id: str,
    decision: CommitDeferralDecision,
    record: HostRepositoryRecord,
    *,
    repo_display_name: str,
    root: Path,
    baseline: DirtyBaseline | None,
    written_paths: tuple[str, ...],
) -> _AcceptedCommitDeferral:
    reason_label = (
        decision.deferral.reason
        if decision.deferral.reason in FINALIZER_DEFERRAL_REASONS
        else "invalid"
    )
    FINALIZER_DEFERRALS.labels(reason=reason_label, outcome="submitted").inc()
    try:
        result = _adjudicate_decision(
            instance_id,
            decision,
            record,
            repo_display_name=repo_display_name,
            root=root,
            baseline=baseline,
            written_paths=written_paths,
        )
    except FinalizerDeclarationError:
        FINALIZER_DEFERRALS.labels(reason=reason_label, outcome="rejected").inc()
        raise
    FINALIZER_DEFERRALS.labels(reason=reason_label, outcome="upheld").inc()
    return result


def _commit_payloads(
    envelope: Mapping[str, Any],
    commit_instances: set[str],
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, list):
        return ()
    resolved: list[tuple[str, Mapping[str, Any]]] = []
    for item in payloads:
        if not isinstance(item, Mapping):
            continue
        instance_id = item.get("instance_id")
        payload = item.get("payload")
        if isinstance(instance_id, str) and instance_id in commit_instances:
            if isinstance(payload, Mapping):
                resolved.append((instance_id, payload))
    return tuple(resolved)


def _adjudicate_decision(
    instance_id: str,
    decision: CommitDeferralDecision,
    record: HostRepositoryRecord,
    *,
    repo_display_name: str,
    root: Path,
    baseline: DirtyBaseline | None,
    written_paths: tuple[str, ...],
) -> _AcceptedCommitDeferral:
    reason = decision.deferral.reason
    paths = tuple(decision.deferral.paths)
    if reason == "unsafe_content":
        return _accepted(instance_id, decision, repo_display_name)
    if reason == "protected_paths":
        return _adjudicate_protected_paths(
            instance_id,
            decision,
            record,
            repo_display_name=repo_display_name,
            root=root,
        )
    if reason in {"foreign_work", "belongs_to_another_turn"}:
        direct_writes = direct_written_paths(
            repo_path=record.path,
            written_paths=written_paths,
            named_paths=paths,
        )
        baseline_owned = _baseline_owned_paths(
            baseline=baseline,
            repo_path=record.path,
            paths=paths,
        )
        counter_paths = tuple(sorted(set(direct_writes) | set(baseline_owned)))
        if counter_paths:
            _reject_run_owned_paths(
                decision,
                repo_display_name=repo_display_name,
                direct_writes=direct_writes,
                baseline_owned=baseline_owned,
                counter_paths=counter_paths,
            )
        return _accepted(instance_id, decision, repo_display_name)
    raise FinalizerDeclarationError(
        f"commit deferral for {decision.repo_id} has unsupported reason {reason!r}",
        code="commit_deferral_reason_invalid",
    )


def _adjudicate_protected_paths(
    instance_id: str,
    decision: CommitDeferralDecision,
    record: HostRepositoryRecord,
    *,
    repo_display_name: str,
    root: Path,
) -> _AcceptedCommitDeferral:
    protected = set(
        protected_baseline_paths(
            root,
            record.path,
            get_changed_files=git_changed_files,
        )
    )
    paths = set(decision.deferral.paths)
    rejected = tuple(sorted(paths - protected))
    if rejected:
        protected_text = ", ".join(sorted(protected)) if protected else "none"
        raise FinalizerDeclarationError(
            f"commit deferral for {repo_display_name} (protected_paths) was "
            "rejected: host evidence does not identify "
            f"{_path_list(rejected)} as protected; protected paths currently "
            f"known for this repository: {protected_text}. Submit a conventional "
            "commit message for this repository instead.",
            code="commit_deferral_rejected",
        )
    return _accepted(instance_id, decision, repo_display_name)


def _baseline_owned_paths(
    *,
    baseline: DirtyBaseline | None,
    repo_path: str,
    paths: tuple[str, ...],
) -> tuple[str, ...]:
    if baseline is None:
        return ()
    fingerprints = baseline.get(normalize_path(repo_path))
    if fingerprints is None:
        return tuple(sorted(paths))
    run_owned, _pre_existing = split_pre_existing_changed_files(
        repo_path,
        list(paths),
        fingerprints,
    )
    return tuple(sorted(run_owned))


def _reject_run_owned_paths(
    decision: CommitDeferralDecision,
    *,
    repo_display_name: str,
    direct_writes: tuple[str, ...],
    baseline_owned: tuple[str, ...],
    counter_paths: tuple[str, ...],
) -> None:
    details: list[str] = []
    if baseline_owned:
        details.append(
            "the run-start baseline shows "
            f"{_path_list(baseline_owned)} were new or changed after this run began"
        )
    if direct_writes:
        details.append(
            f"this run's write/edit tool calls named {_path_list(direct_writes)}"
        )
    raise FinalizerDeclarationError(
        f"commit deferral for {repo_display_name} ({decision.deferral.reason}) was "
        f"rejected: host evidence attributes {_path_list(counter_paths)} to this "
        f"run; {'; '.join(details)}. Submit a conventional commit message for "
        "this repository instead.",
        code="commit_deferral_rejected",
    )


def _accepted(
    instance_id: str,
    decision: CommitDeferralDecision,
    repo_display_name: str,
) -> _AcceptedCommitDeferral:
    return _AcceptedCommitDeferral(
        instance_id=instance_id,
        repo_id=decision.repo_id,
        repo_display_name=repo_display_name,
        reason=decision.deferral.reason,
        paths=tuple(decision.deferral.paths),
    )


def _path_list(paths: tuple[str, ...]) -> str:
    return ", ".join(paths)


__all__ = [
    "adjudicate_commit_deferrals",
]
