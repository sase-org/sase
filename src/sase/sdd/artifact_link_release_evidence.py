"""Durable run-scoped release evidence for automatic artifact-link publication.

Recorded once the host verifies a qualifying (non-bookkeeping) commit for one
run, so a later outbox drain -- possibly from a different process, after the
originating workspace is gone -- can confirm that run earned the right to
publish its pending automatic links, without re-deriving eligibility. See
``sase.sdd.artifact_link_outbox`` for the queue this evidence gates.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
import time

from sase.core.eligibility_facade import (
    ArtifactLinkEligibilityDecision,
    ArtifactLinkReleaseEvidence,
)
from sase.core.eligibility_facade import (
    artifact_link_release_evidence as _build_release_evidence,
)
from sase.core.eligibility_facade import (
    validate_artifact_link_release_evidence as _validate_release_evidence,
)
from sase.core.paths import sase_projects_dir, validate_sase_project_name
from sase.memory.locks import locked_file

ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME = "artifact-link-release-evidence.jsonl"


def _release_evidence_path(project_key: str) -> Path:
    """Return ``~/.sase/projects/<key>/artifact-link-release-evidence.jsonl``."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME


def record_artifact_link_release_evidence(
    *,
    project_key: str,
    run_id: str,
    agent_id: str,
    qualifying_repo_ids: Sequence[str],
    now: float | None = None,
) -> ArtifactLinkReleaseEvidence:
    """Durably record that *agent_id*'s *run_id* made a qualifying change."""

    decision = ArtifactLinkEligibilityDecision(
        run_id=run_id,
        agent_id=agent_id,
        eligible=True,
        qualifying_repo_ids=tuple(qualifying_repo_ids),
    )
    recorded_at = datetime.fromtimestamp(
        time.time() if now is None else now, tz=UTC
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence = _build_release_evidence(decision, recorded_at=recorded_at)

    path = _release_evidence_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(
                {
                    "run_id": evidence.run_id,
                    "agent_id": evidence.agent_id,
                    "qualifying_repo_ids": list(evidence.qualifying_repo_ids),
                    "recorded_at": evidence.recorded_at,
                },
                output_file,
                sort_keys=True,
            )
            output_file.write("\n")
            output_file.flush()
    return evidence


def artifact_link_run_has_release_evidence(
    *,
    project_key: str,
    run_id: str,
    agent_id: str,
) -> bool:
    """Return whether *agent_id*'s *run_id* has verified release evidence.

    A blank ``run_id`` or ``agent_id`` never qualifies: legacy queue rows
    recorded before this contract existed carry no run evidence and stay
    local rather than being assumed eligible.
    """

    if not run_id or not agent_id:
        return False
    path = _release_evidence_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.is_file():
            return False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("run_id") or "") != run_id:
            continue
        if str(data.get("agent_id") or "") != agent_id:
            continue
        evidence = ArtifactLinkReleaseEvidence(
            run_id=str(data.get("run_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            qualifying_repo_ids=tuple(
                str(item) for item in data.get("qualifying_repo_ids") or ()
            ),
            recorded_at=str(data.get("recorded_at") or ""),
        )
        try:
            _validate_release_evidence(
                evidence,
                expected_run_id=run_id,
                expected_agent_id=agent_id,
            )
        except (TypeError, ValueError, RuntimeError):
            continue
        return True
    return False


__all__ = [
    "ARTIFACT_LINK_RELEASE_EVIDENCE_FILENAME",
    "artifact_link_run_has_release_evidence",
    "record_artifact_link_release_evidence",
]
