"""Local-history discovery and destination allocation for v2 imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    ValidatedV2RunPayload,
)
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentSourceOwnerIdentity,
    globalize_agent_name,
    localize_imported_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.sase_agent import sase_agent_name
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

_FALLBACK_START = datetime(2000, 1, 1, tzinfo=UTC)
_FALLBACK_END = datetime(2020, 1, 1, tzinfo=UTC)
_FALLBACK_SPAN_SECONDS = int((_FALLBACK_END - _FALLBACK_START).total_seconds())


@dataclass(frozen=True, slots=True)
class ExactLocalObservationIndex:
    """One-pass lookup for exact-owner source IDs and primary commits."""

    by_source: dict[tuple[str, str], Path]
    by_commit: dict[tuple[str, str], Path]
    primary_commits: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class _LocalImportState:
    """One-pass local artifact scan reused by v1-adoption and v2 refresh."""

    imports: dict[tuple[str, str, str, str], tuple[Path, str | None]]
    legacy_v1_rows: tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...]


def scan_local_import_state(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
) -> _LocalImportState:
    """Scan local artifacts once for existing v2 imports and v1 adoption candidates."""

    imports: dict[tuple[str, str, str, str], tuple[Path, str | None]] = {}
    legacy_rows: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
    for artifact in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        meta = read_json_object(artifact / "agent_meta.json")
        if meta is None:
            continue
        owner = meta.get("imported_source_owner")
        source_id = meta.get("imported_source_run_id")
        global_name = meta.get("canonical_global_name")
        if (
            isinstance(owner, dict)
            and isinstance(source_id, str)
            and isinstance(global_name, str)
        ):
            username = owner.get("username")
            machine = owner.get("machine_name")
            if isinstance(username, str) and isinstance(machine, str):
                localized = localize_imported_agent_name(
                    global_name,
                    AgentSourceOwnerIdentity(machine, username),
                    identity,
                )
                if meta.get("name") == localized:
                    digest = meta.get("imported_snapshot_digest")
                    imports[(username, machine, source_id, global_name)] = (
                        artifact,
                        digest if isinstance(digest, str) else None,
                    )
        if meta.get("imported_owner_kind") == "username_unknown_v1":
            done = read_json_object(artifact / "done.json") or {}
            legacy_rows.append((artifact, meta, done))
    return _LocalImportState(imports, tuple(legacy_rows))


def build_exact_local_observation_index(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    packages: tuple[ValidatedV2HoodPackage, ...] = (),
    *,
    git_runner: GitRunner = run_git,
) -> ExactLocalObservationIndex:
    """Index exact-owner artifacts once for a multi-hood import pass."""

    if identity.owner is None:
        return ExactLocalObservationIndex({}, {}, frozenset())
    by_source: dict[tuple[str, str], Path] = {}
    by_commit: dict[tuple[str, str], Path] = {}
    for artifact in iter_agent_artifact_dirs(
        target.project_key,
        ACE_RUN_WORKFLOW_DIR,
        newest_first=False,
    ):
        meta = read_json_object(artifact / "agent_meta.json")
        done = read_json_object(artifact / "done.json") or {}
        if meta is None or meta.get("imported_source_owner") is not None:
            continue
        raw_name = meta.get("name") or done.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        try:
            local_name = normalize_agent_archive_name(
                normalize_owned_agent_name(raw_name, identity)
            )
            global_name = globalize_agent_name(local_name, identity.owner)
        except (ValueError, RuntimeError):
            continue
        durable = meta.get("artifact_agent_id")
        if not isinstance(durable, str) or not durable:
            durable = artifact.name
        source_run_id = _source_run_id(
            target.project_key,
            ACE_RUN_WORKFLOW_DIR,
            durable,
        )
        by_source.setdefault((global_name, source_run_id), artifact)
        for sha in _artifact_commit_shas(artifact):
            by_commit.setdefault((global_name, sha), artifact)
    return ExactLocalObservationIndex(
        by_source,
        by_commit,
        _matching_primary_commit_evidence(
            target,
            identity,
            packages,
            git_runner=git_runner,
        ),
    )


def find_exact_local_observation(
    target: ProjectTarget,
    payload: ValidatedV2RunPayload,
    identity: AgentIdentitySnapshot,
    *,
    index: ExactLocalObservationIndex | None = None,
) -> Path | None:
    if identity.owner is None:
        return None
    observations = index or build_exact_local_observation_index(target, identity)
    direct = observations.by_source.get(
        (payload.record.global_name, payload.record.source_run_id)
    )
    if direct is not None:
        return direct
    source_shas = {commit.sha for commit in payload.commits.commits}
    for sha in sorted(source_shas):
        observed = observations.by_commit.get((payload.record.global_name, sha))
        if observed is not None:
            return observed
        if (payload.record.global_name, sha) in observations.primary_commits:
            # Primary history proves the exact-owner run already happened even
            # after its local artifact was cleaned. This evidence-only path is
            # never materialized; the source-ID-derived basename exists only
            # for relationship rewriting in the otherwise no-op plan.
            return target.primary_checkout / preferred_timestamp(
                payload.record.source_run_id,
                None,
            )
    return None


def _matching_primary_commit_evidence(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    packages: tuple[ValidatedV2HoodPackage, ...],
    *,
    git_runner: GitRunner,
) -> frozenset[tuple[str, str]]:
    owner = identity.owner
    if owner is None or not packages:
        return frozenset()
    expected: dict[str, set[str]] = {}
    for package in packages:
        for payload in package.runs:
            for commit in payload.commits.commits:
                expected.setdefault(commit.sha.lower(), set()).add(
                    payload.record.global_name
                )
    unresolved = set(expected)
    matched: set[tuple[str, str]] = set()
    roots = tuple(dict.fromkeys((target.primary_checkout, *target.primary_roots)))
    for root in roots:
        if not unresolved:
            break
        if not root.is_dir():
            continue
        revisions = git_runner(
            root,
            ["rev-list", "--all"],
            op="agents_sync.v2_primary_commit_index",
        )
        if revisions.returncode != 0:
            continue
        present = unresolved & {
            line.strip().lower()
            for line in revisions.stdout.splitlines()
            if line.strip()
        }
        if not present:
            continue
        messages = git_runner(
            root,
            [
                "show",
                "--no-patch",
                "--format=%H%x00%B%x00",
                *sorted(present),
            ],
            op="agents_sync.v2_primary_commit_messages",
        )
        if messages.returncode != 0:
            continue
        chunks = messages.stdout.split("\x00")
        for index in range(0, len(chunks) - 1, 2):
            sha = chunks[index].lstrip("\r\n").strip().lower()
            if sha not in present:
                continue
            tags = parse_trailing_commit_tags(chunks[index + 1].rstrip("\r\n"))
            raw_name = tags.get("AGENT")
            footer_machine = tags.get("MACHINE")
            if not raw_name or footer_machine not in {None, owner.machine_name}:
                continue
            try:
                local_name = normalize_agent_archive_name(
                    normalize_owned_agent_name(raw_name, identity)
                )
                global_name = globalize_agent_name(local_name, owner)
            except (ValueError, RuntimeError):
                continue
            for expected_global_name in expected[sha]:
                try:
                    same_sase_agent = sase_agent_name(global_name) == sase_agent_name(
                        expected_global_name
                    )
                except (ValueError, RuntimeError):
                    same_sase_agent = False
                if global_name == expected_global_name or same_sase_agent:
                    # Evidence is indexed under the imported run identity, not
                    # under the footer's sase-agent label, so callers can resolve
                    # the exact member payload that the sase agent proves.
                    matched.add((expected_global_name, sha))
        unresolved -= present
    return frozenset(matched)


def preferred_timestamp(source_run_id: str, started_at: str | None) -> str:
    """Choose a preferred timestamp that never exceeds current UTC time."""

    now = datetime.now(UTC)
    candidate: datetime | None = None
    match = re.search(r"(?<!\d)(\d{14})(?!\d)", source_run_id)
    if match is not None:
        try:
            candidate = datetime.strptime(
                match.group(1),
                "%Y%m%d%H%M%S",
            ).replace(tzinfo=UTC)
        except ValueError:
            pass
    if candidate is None:
        parsed = _parse_datetime(started_at)
        if parsed is not None:
            candidate = parsed.astimezone(UTC)
    if candidate is None:
        # Hash into a fixed twenty-year historical window. The final clamp
        # preserves the no-future invariant even under an unexpectedly old
        # system clock.
        seconds = (
            int(hashlib.sha256(source_run_id.encode()).hexdigest()[:8], 16)
            % _FALLBACK_SPAN_SECONDS
        )
        candidate = _FALLBACK_START + timedelta(seconds=seconds)
    return min(candidate, now).strftime("%Y%m%d%H%M%S")


def reserve_timestamp(
    target: ProjectTarget,
    preferred: str,
    reserved: set[str],
) -> str:
    current = datetime.strptime(preferred, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    latest = datetime.now(UTC).replace(microsecond=0)
    if current > latest:
        raise ValueError(
            f"future imported artifact timestamp {preferred} exceeds current UTC "
            f"time {latest.strftime('%Y%m%d%H%M%S')}"
        )
    for _ in range(86_400):
        if current > latest:
            raise RuntimeError(
                "could not allocate a free imported artifact timestamp without "
                "exceeding the current UTC time"
            )
        value = current.strftime("%Y%m%d%H%M%S")
        destination = canonical_agent_artifact_path(
            target.project_key,
            ACE_RUN_WORKFLOW_DIR,
            value,
        )
        if value not in reserved and not destination.exists():
            return value
        current += timedelta(seconds=1)
    raise RuntimeError("could not allocate a free imported artifact timestamp")


def read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def read_json_object(path: Path) -> dict[str, Any] | None:
    value = read_json(path)
    return value if isinstance(value, dict) else None


def _artifact_commit_shas(artifact: Path) -> set[str]:
    result: set[str] = set()
    for name in ("commit_results.json", "commit_result.json"):
        value = read_json(artifact / name)
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            sha = row.get("result") or row.get("commit_result") or row.get("sha")
            if isinstance(sha, str):
                result.add(sha.lower())
    return result


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if len(value) == 14 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _source_run_id(project: str, workflow: str, durable: str) -> str:
    digest = hashlib.sha256(
        "\x00".join((project, workflow, durable)).encode("utf-8")
    ).hexdigest()
    return f"run-{digest[:32]}"


__all__ = [
    "ExactLocalObservationIndex",
    "build_exact_local_observation_index",
    "find_exact_local_observation",
    "preferred_timestamp",
    "read_json",
    "read_json_object",
    "reserve_timestamp",
    "scan_local_import_state",
]
