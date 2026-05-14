"""Comparison helpers for daemon lifecycle projections."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sase.agent.running import RunningAgentInfo
from sase.daemon.read_models import AgentProjectionSummary


# pyvision: sdd/epics/202605/epic7_daemon_scheduler_phases.md
def compare_lifecycle_classifications(
    expected: Iterable[RunningAgentInfo],
    observed: Iterable[AgentProjectionSummary],
) -> _LifecycleShadowDiff:
    return _compare_classifications(
        _lifecycle_from_running_agents(expected),
        _lifecycle_from_projection_summaries(observed),
    )


@dataclass(frozen=True)
class _LifecycleClassification:
    agent_id: str
    project: str
    name: str | None
    status: str
    artifacts_dir: str | None


@dataclass(frozen=True)
class _LifecycleShadowDiff:
    missing: list[_LifecycleClassification]
    extra: list[_LifecycleClassification]
    status_mismatch: list[tuple[_LifecycleClassification, _LifecycleClassification]]

    @property
    def clean(self) -> bool:
        return not self.missing and not self.extra and not self.status_mismatch


def _lifecycle_from_running_agents(
    agents: Iterable[RunningAgentInfo],
) -> list[_LifecycleClassification]:
    return [
        _LifecycleClassification(
            agent_id=_agent_id_for_info(info),
            project=info.project,
            name=info.name,
            status=_projection_status_for_cli_status(info.status),
            artifacts_dir=info.artifacts_dir,
        )
        for info in agents
    ]


def _lifecycle_from_projection_summaries(
    summaries: Iterable[AgentProjectionSummary],
) -> list[_LifecycleClassification]:
    return [
        _LifecycleClassification(
            agent_id=summary.agent_id,
            project=summary.project_name,
            name=summary.agent_name,
            status=_projection_status_for_cli_status(summary.status),
            artifacts_dir=summary.artifact_dir,
        )
        for summary in summaries
    ]


def _compare_classifications(
    expected: Iterable[_LifecycleClassification],
    observed: Iterable[_LifecycleClassification],
) -> _LifecycleShadowDiff:
    expected_by_key = {_classification_key(item): item for item in expected}
    observed_by_key = {_classification_key(item): item for item in observed}
    missing = [
        expected_by_key[key]
        for key in sorted(expected_by_key.keys() - observed_by_key.keys())
    ]
    extra = [
        observed_by_key[key]
        for key in sorted(observed_by_key.keys() - expected_by_key.keys())
    ]
    status_mismatch = []
    for key in sorted(expected_by_key.keys() & observed_by_key.keys()):
        left = expected_by_key[key]
        right = observed_by_key[key]
        if left.status != right.status:
            status_mismatch.append((left, right))
    return _LifecycleShadowDiff(
        missing=missing,
        extra=extra,
        status_mismatch=status_mismatch,
    )


def _classification_key(item: _LifecycleClassification) -> str:
    return item.artifacts_dir or item.agent_id


def _agent_id_for_info(info: RunningAgentInfo) -> str:
    if info.artifacts_dir:
        timestamp = info.artifacts_dir.rstrip("/").rsplit("/", 1)[-1]
        return f"agent:{info.project}:{timestamp}"
    return f"agent:{info.project}:{info.name or 'unknown'}"


def _projection_status_for_cli_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"done", "completed"}:
        return "completed"
    if normalized in {"failed", "failure"}:
        return "failed"
    if normalized in {"killed", "cancelled", "canceled"}:
        return "killed"
    if normalized == "waiting":
        return "waiting"
    if normalized == "starting":
        return "starting"
    if normalized == "queued":
        return "queued"
    if normalized == "planned":
        return "planned"
    if normalized == "stale":
        return "stale"
    return "running"
