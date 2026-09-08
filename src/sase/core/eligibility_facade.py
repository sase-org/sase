"""Typed Python boundary for automatic artifact-link publish eligibility.

All eligibility policy lives in :mod:`sase_core_rs`; this module only
converts between plain Python data and Rust binding dictionaries. See
:mod:`sase.sdd.artifact_link_release_evidence` for the durable evidence
store built on top of this facade.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, NamedTuple

from sase.core.rust import require_rust_binding


class ArtifactLinkChangedPath(NamedTuple):
    """One host-collected changed path and whether it is a real change."""

    path: str
    is_real: bool


class ArtifactLinkRepoEvidence(NamedTuple):
    """One repository's host-collected change evidence for a run."""

    repo_id: str
    kind: str
    changed_paths: tuple[ArtifactLinkChangedPath, ...] = ()


class ArtifactLinkEligibilityDecision(NamedTuple):
    """Whether a run's evidence qualifies it to publish pending links."""

    run_id: str
    agent_id: str
    eligible: bool
    qualifying_repo_ids: tuple[str, ...]


class ArtifactLinkReleaseEvidence(NamedTuple):
    """Durable evidence that a run's qualifying change was verified."""

    run_id: str
    agent_id: str
    qualifying_repo_ids: tuple[str, ...]
    recorded_at: str


@lru_cache(maxsize=1)
def _artifact_link_eligibility_wire_schema_version() -> int:
    binding = require_rust_binding("artifact_link_eligibility_wire_schema_version")
    return int(binding())


def decide_artifact_link_eligibility(
    *,
    run_id: str,
    agent_id: str,
    repos: Sequence[ArtifactLinkRepoEvidence],
) -> ArtifactLinkEligibilityDecision:
    """Decide whether *run_id*/*agent_id* may publish its pending links."""

    binding = require_rust_binding("decide_artifact_link_eligibility")
    request = {
        "schema_version": _artifact_link_eligibility_wire_schema_version(),
        "run_id": run_id,
        "agent_id": agent_id,
        "repos": [_repo_to_wire(repo) for repo in repos],
    }
    return _decision_from_wire(binding(request))


def artifact_link_release_evidence(
    decision: ArtifactLinkEligibilityDecision,
    *,
    recorded_at: str,
) -> ArtifactLinkReleaseEvidence:
    """Build durable release evidence for an eligible *decision*."""

    binding = require_rust_binding("artifact_link_release_evidence")
    payload = binding(_decision_to_wire(decision), recorded_at)
    return _release_evidence_from_wire(payload)


def validate_artifact_link_release_evidence(
    evidence: ArtifactLinkReleaseEvidence,
    *,
    expected_run_id: str,
    expected_agent_id: str,
) -> None:
    """Raise unless *evidence* is still bound to the expected run/agent."""

    binding = require_rust_binding("validate_artifact_link_release_evidence")
    binding(
        _release_evidence_to_wire(evidence),
        expected_run_id,
        expected_agent_id,
    )


def _repo_to_wire(repo: ArtifactLinkRepoEvidence) -> dict[str, Any]:
    return {
        "repo_id": repo.repo_id,
        "kind": repo.kind,
        "changed_paths": [
            {
                "path": changed.path,
                "role": "real" if changed.is_real else "bookkeeping",
            }
            for changed in repo.changed_paths
        ],
    }


def _decision_to_wire(decision: ArtifactLinkEligibilityDecision) -> dict[str, Any]:
    return {
        "schema_version": _artifact_link_eligibility_wire_schema_version(),
        "run_id": decision.run_id,
        "agent_id": decision.agent_id,
        "eligible": decision.eligible,
        "qualifying_repo_ids": list(decision.qualifying_repo_ids),
    }


def _decision_from_wire(
    payload: Mapping[str, Any],
) -> ArtifactLinkEligibilityDecision:
    return ArtifactLinkEligibilityDecision(
        run_id=str(payload["run_id"]),
        agent_id=str(payload["agent_id"]),
        eligible=bool(payload["eligible"]),
        qualifying_repo_ids=tuple(str(item) for item in payload["qualifying_repo_ids"]),
    )


def _release_evidence_to_wire(
    evidence: ArtifactLinkReleaseEvidence,
) -> dict[str, Any]:
    return {
        "schema_version": _artifact_link_eligibility_wire_schema_version(),
        "run_id": evidence.run_id,
        "agent_id": evidence.agent_id,
        "qualifying_repo_ids": list(evidence.qualifying_repo_ids),
        "recorded_at": evidence.recorded_at,
    }


def _release_evidence_from_wire(
    payload: Mapping[str, Any],
) -> ArtifactLinkReleaseEvidence:
    return ArtifactLinkReleaseEvidence(
        run_id=str(payload["run_id"]),
        agent_id=str(payload["agent_id"]),
        qualifying_repo_ids=tuple(str(item) for item in payload["qualifying_repo_ids"]),
        recorded_at=str(payload["recorded_at"]),
    )


__all__ = [
    "ArtifactLinkChangedPath",
    "ArtifactLinkEligibilityDecision",
    "ArtifactLinkReleaseEvidence",
    "ArtifactLinkRepoEvidence",
    "artifact_link_release_evidence",
    "decide_artifact_link_eligibility",
    "validate_artifact_link_release_evidence",
]
