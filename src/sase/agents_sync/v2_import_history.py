"""Local-history discovery and destination allocation for v2 imports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_import_package import ValidatedV2RunPayload
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


def existing_project_imports(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str, str, str], tuple[Path, str | None]]:
    results: dict[tuple[str, str, str, str], tuple[Path, str | None]] = {}
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
            not isinstance(owner, dict)
            or not isinstance(source_id, str)
            or not isinstance(global_name, str)
        ):
            continue
        username = owner.get("username")
        machine = owner.get("machine_name")
        if not isinstance(username, str) or not isinstance(machine, str):
            continue
        localized = localize_imported_agent_name(
            global_name,
            AgentSourceOwnerIdentity(machine, username),
            identity,
        )
        if meta.get("name") != localized:
            continue
        digest = meta.get("imported_snapshot_digest")
        results[(username, machine, source_id, global_name)] = (
            artifact,
            digest if isinstance(digest, str) else None,
        )
    return results


def find_exact_local_observation(
    target: ProjectTarget,
    payload: ValidatedV2RunPayload,
    identity: AgentIdentitySnapshot,
) -> Path | None:
    if identity.owner is None:
        return None
    source_shas = {commit.sha for commit in payload.commits.commits}
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
            if (
                globalize_agent_name(local_name, identity.owner)
                != payload.record.global_name
            ):
                continue
        except (ValueError, RuntimeError):
            continue
        durable = meta.get("artifact_agent_id")
        if not isinstance(durable, str) or not durable:
            durable = artifact.name
        derived_id = _source_run_id(target.project_key, ACE_RUN_WORKFLOW_DIR, durable)
        if derived_id == payload.record.source_run_id:
            return artifact
        if source_shas and source_shas & _artifact_commit_shas(artifact):
            return artifact
    return None


def preferred_timestamp(source_run_id: str, started_at: str | None) -> str:
    match = re.search(r"(?<!\d)(\d{14})(?!\d)", source_run_id)
    if match is not None:
        try:
            datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            return match.group(1)
        except ValueError:
            pass
    parsed = _parse_datetime(started_at)
    if parsed is not None:
        return parsed.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    # Stable fallback in a historical range; probing resolves collisions.
    seconds = int(hashlib.sha256(source_run_id.encode()).hexdigest()[:8], 16)
    return (datetime(2000, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)).strftime(
        "%Y%m%d%H%M%S"
    )


def reserve_timestamp(
    target: ProjectTarget,
    preferred: str,
    reserved: set[str],
) -> str:
    current = datetime.strptime(preferred, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    for _ in range(86_400):
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
    "existing_project_imports",
    "find_exact_local_observation",
    "preferred_timestamp",
    "read_json",
    "read_json_object",
    "reserve_timestamp",
]
