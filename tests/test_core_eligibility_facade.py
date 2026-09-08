from __future__ import annotations

import pytest

from sase.core.eligibility_facade import (
    ArtifactLinkChangedPath,
    ArtifactLinkRepoEvidence,
    artifact_link_eligibility_wire_schema_version,
    artifact_link_release_evidence,
    decide_artifact_link_eligibility,
    validate_artifact_link_release_evidence,
)

pytestmark = pytest.mark.contract


def test_facade_resolves_schema_version() -> None:
    assert artifact_link_eligibility_wire_schema_version() >= 1


def test_bookkeeping_only_evidence_is_ineligible() -> None:
    decision = decide_artifact_link_eligibility(
        run_id="run-1",
        agent_id="agent-1",
        repos=(
            ArtifactLinkRepoEvidence(
                repo_id="sdd:plan",
                kind="sdd",
                changed_paths=(
                    ArtifactLinkChangedPath(
                        path="links/plan/foo.md.json", is_real=False
                    ),
                ),
            ),
        ),
    )
    assert decision.eligible is False
    assert decision.qualifying_repo_ids == ()


def test_real_change_makes_its_repo_eligible() -> None:
    decision = decide_artifact_link_eligibility(
        run_id="run-1",
        agent_id="agent-1",
        repos=(
            ArtifactLinkRepoEvidence(
                repo_id="sdd:plan",
                kind="sdd",
                changed_paths=(
                    ArtifactLinkChangedPath(
                        path="links/plan/foo.md.json", is_real=False
                    ),
                ),
            ),
            ArtifactLinkRepoEvidence(
                repo_id="main",
                kind="main",
                changed_paths=(
                    ArtifactLinkChangedPath(path="src/lib.py", is_real=True),
                ),
            ),
        ),
    )
    assert decision.eligible is True
    assert decision.qualifying_repo_ids == ("main",)


def test_release_evidence_round_trips_and_validates_the_same_run() -> None:
    decision = decide_artifact_link_eligibility(
        run_id="run-1",
        agent_id="agent-1",
        repos=(
            ArtifactLinkRepoEvidence(
                repo_id="main",
                kind="main",
                changed_paths=(
                    ArtifactLinkChangedPath(path="src/lib.py", is_real=True),
                ),
            ),
        ),
    )
    evidence = artifact_link_release_evidence(
        decision, recorded_at="2026-09-08T00:00:00Z"
    )
    assert evidence.run_id == "run-1"
    assert evidence.agent_id == "agent-1"
    assert evidence.qualifying_repo_ids == ("main",)

    validate_artifact_link_release_evidence(
        evidence, expected_run_id="run-1", expected_agent_id="agent-1"
    )


def test_release_evidence_refuses_an_ineligible_decision() -> None:
    decision = decide_artifact_link_eligibility(
        run_id="run-1", agent_id="agent-1", repos=()
    )
    with pytest.raises(ValueError):
        artifact_link_release_evidence(decision, recorded_at="2026-09-08T00:00:00Z")


def test_release_evidence_rejects_a_different_run_or_agent() -> None:
    decision = decide_artifact_link_eligibility(
        run_id="run-1",
        agent_id="agent-1",
        repos=(
            ArtifactLinkRepoEvidence(
                repo_id="main",
                kind="main",
                changed_paths=(
                    ArtifactLinkChangedPath(path="src/lib.py", is_real=True),
                ),
            ),
        ),
    )
    evidence = artifact_link_release_evidence(
        decision, recorded_at="2026-09-08T00:00:00Z"
    )

    with pytest.raises(ValueError):
        validate_artifact_link_release_evidence(
            evidence, expected_run_id="run-2", expected_agent_id="agent-1"
        )
    with pytest.raises(ValueError):
        validate_artifact_link_release_evidence(
            evidence, expected_run_id="run-1", expected_agent_id="agent-2"
        )
