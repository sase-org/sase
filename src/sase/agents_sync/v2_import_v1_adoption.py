"""Evidence-backed matching of a v2 import against a legacy v1 artifact.

A destination machine that imported the legacy v1 agents-sidecar payload holds
lossy ``origin: import_v1`` artifacts with no explicit owner. When the same
run later arrives through a validated v2 hood, this module proves — never
guesses — that the v2 run and a local v1 artifact describe the same source
run, so the importer can refresh the v1 artifact in place instead of leaving
it behind as permanent dead state.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.agents_sync.bundles import commit_markers
from sase.agents_sync.inventory_io import source_run_id
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_import_package import ValidatedV2RunPayload
from sase.agents_sync.v2_io import content_digest
from sase.core.agent_artifact_paths import ACE_RUN_WORKFLOW_DIR
from sase.core.agent_identity_facade import AgentOwnerIdentity


class _V1AdoptionAmbiguityError(AgentsSyncFormatError):
    """A v2 run cannot be safely matched to exactly one legacy v1 artifact."""


@dataclass(frozen=True, slots=True)
class _LegacyV1Artifact:
    """One local ``origin: import_v1`` artifact eligible for v2 adoption."""

    path: Path
    source_machine: str
    v1_name: str
    source_run_id: str
    chat_path: Path | None
    commit_shas: frozenset[str]


@dataclass(slots=True)
class LegacyV1AdoptionIndex:
    """Lookup of legacy v1 artifacts keyed by recomputed source run id."""

    by_key: dict[tuple[str, str], tuple[_LegacyV1Artifact, ...]]
    consumed: set[Path] = field(default_factory=set)


def legacy_v1_adoption_index(
    project_key: str,
    rows: Iterable[tuple[Path, dict[str, Any], dict[str, Any]]],
) -> LegacyV1AdoptionIndex:
    """Index every qualifying legacy v1 row by ``(source_machine, source_run_id)``."""

    by_key: dict[tuple[str, str], list[_LegacyV1Artifact]] = defaultdict(list)
    for artifact_dir, meta, done in rows:
        if meta.get("imported_owner_kind") != "username_unknown_v1":
            continue
        if meta.get("imported_source_owner") is not None:
            continue
        machine = meta.get("imported_from_machine")
        v1_name = meta.get("name")
        if not isinstance(machine, str) or not machine:
            continue
        if not isinstance(v1_name, str) or not v1_name:
            continue
        durable = (
            meta.get("artifact_agent_id")
            or done.get("artifacts_timestamp")
            or artifact_dir.name
        )
        recomputed_id = source_run_id(project_key, ACE_RUN_WORKFLOW_DIR, str(durable))
        raw_chat_path = meta.get("chat_path")
        chat_path = (
            Path(raw_chat_path).expanduser()
            if isinstance(raw_chat_path, str) and raw_chat_path
            else None
        )
        by_key[(machine, recomputed_id)].append(
            _LegacyV1Artifact(
                artifact_dir,
                machine,
                v1_name,
                recomputed_id,
                chat_path,
                _artifact_commit_shas(artifact_dir),
            )
        )
    return LegacyV1AdoptionIndex({key: tuple(value) for key, value in by_key.items()})


def find_v1_adoption(
    index: LegacyV1AdoptionIndex,
    owner: AgentOwnerIdentity,
    payload: ValidatedV2RunPayload,
) -> _LegacyV1Artifact | None:
    """Return the one legacy v1 artifact this v2 run proves it supersedes."""

    record = payload.record
    prefix = f"{owner.username}."
    if not record.global_name.startswith(prefix):
        return None
    expected_v1_name = record.global_name[len(prefix) :]
    candidates = index.by_key.get((owner.machine_name, record.source_run_id), ())
    survivors = tuple(
        artifact
        for artifact in candidates
        if artifact.path not in index.consumed and artifact.v1_name == expected_v1_name
    )
    if not survivors:
        return None
    if len(survivors) > 1:
        raise _V1AdoptionAmbiguityError(
            f"imported run {record.global_name!r} ambiguously matches legacy v1 "
            "artifacts: " + ", ".join(str(artifact.path) for artifact in survivors)
        )
    artifact = survivors[0]
    _corroborate_or_raise(artifact, record, payload)
    index.consumed.add(artifact.path)
    return artifact


def _corroborate_or_raise(
    artifact: _LegacyV1Artifact,
    record: Any,
    payload: ValidatedV2RunPayload,
) -> None:
    chat_reference = dict(record.files).get("chat")
    if (
        chat_reference is not None
        and artifact.chat_path is not None
        and artifact.chat_path.is_file()
        and content_digest(artifact.chat_path.read_bytes()) != chat_reference.digest
    ):
        raise _V1AdoptionAmbiguityError(
            f"legacy v1 chat for {artifact.path} contradicts imported run "
            f"{record.global_name!r}"
        )
    if artifact.commit_shas:
        source_shas = {commit.sha.lower() for commit in payload.commits.commits}
        missing = artifact.commit_shas - source_shas
        if missing:
            raise _V1AdoptionAmbiguityError(
                f"legacy v1 commits for {artifact.path} contradict imported run "
                f"{record.global_name!r}: {', '.join(sorted(missing))}"
            )


def _artifact_commit_shas(artifact_dir: Path) -> frozenset[str]:
    shas: set[str] = set()
    for marker in commit_markers(artifact_dir):
        sha = marker.get("result") or marker.get("commit_result") or marker.get("sha")
        if isinstance(sha, str) and sha:
            shas.add(sha.lower())
    return frozenset(shas)


__all__ = [
    "LegacyV1AdoptionIndex",
    "find_v1_adoption",
    "legacy_v1_adoption_index",
]
