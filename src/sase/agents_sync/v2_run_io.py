"""Strict decoding for v2 per-run metadata, state, and commit payloads."""

from __future__ import annotations

import json
from typing import Any, cast

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_io import (
    V2_METADATA_FIELDS,
    validate_component,
    validate_output_variables,
)
from sase.agents_sync.v2_models import (
    RunState,
    V2ProjectIdentity,
    V2RunCommitsPayload,
    V2RunMetadataPayload,
    V2RunStatePayload,
    V2_SCHEMA_VERSION,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    globalize_agent_name,
    validate_agent_owner,
)

_STATES = {"active", "waiting", "completed", "failed", "stopped", "dismissed"}


def run_metadata_from_json(value: object) -> V2RunMetadataPayload:
    row = _exact(
        value,
        "meta.json",
        {
            "schema_version",
            "owner",
            "project",
            "source_run_id",
            "local_name",
            "global_name",
            "metadata",
        },
    )
    _schema(row, "meta.json")
    owner = _owner(row["owner"])
    project = _project(row["project"])
    run_id = _run_id(row["source_run_id"], "meta.json source_run_id")
    local_name = validate_component(row["local_name"], label="local agent name")
    global_name = validate_component(row["global_name"], label="global agent name")
    if globalize_agent_name(local_name, owner) != global_name:
        raise AgentsSyncFormatError("meta.json global name is not canonical")
    metadata = _object(row["metadata"], "meta.json metadata")
    unknown = set(metadata) - V2_METADATA_FIELDS
    if unknown:
        raise AgentsSyncFormatError(
            "meta.json metadata has unsupported fields: " + ", ".join(sorted(unknown))
        )
    validate_output_variables(metadata, label="meta.json metadata")
    _json_value(metadata, "meta.json metadata")
    return V2RunMetadataPayload(
        owner,
        project,
        run_id,
        local_name,
        global_name,
        tuple(sorted(metadata.items())),
    )


def run_state_from_json(value: object) -> V2RunStatePayload:
    row = _exact(
        value,
        "state.json",
        {
            "schema_version",
            "source_run_id",
            "state",
            "started_at",
            "finished_at",
            "dismissed_at",
        },
    )
    _schema(row, "state.json")
    state = row["state"]
    if state not in _STATES:
        raise AgentsSyncFormatError("state.json state is invalid")
    return V2RunStatePayload(
        _run_id(row["source_run_id"], "state.json source_run_id"),
        cast(RunState, state),
        _optional_string(row["started_at"], "state.json started_at"),
        _optional_string(row["finished_at"], "state.json finished_at"),
        _optional_string(row["dismissed_at"], "state.json dismissed_at"),
    )


def run_commits_from_json(value: object) -> V2RunCommitsPayload:
    row = _exact(
        value,
        "commits.json",
        {"schema_version", "source_run_id", "commits"},
    )
    _schema(row, "commits.json")
    raw_commits = row["commits"]
    if not isinstance(raw_commits, list) or len(raw_commits) > 4_096:
        raise AgentsSyncFormatError("commits.json commits must be a bounded list")
    commits: list[CommitRecord] = []
    for index, raw in enumerate(raw_commits):
        commit = _exact(
            raw,
            f"commits.json commits[{index}]",
            {"sha", "subject", "committed_at"},
        )
        sha = commit["sha"]
        if (
            not isinstance(sha, str)
            or not 7 <= len(sha) <= 64
            or any(character not in "0123456789abcdef" for character in sha)
        ):
            raise AgentsSyncFormatError(f"invalid commit SHA at index {index}")
        subject = commit["subject"]
        if not isinstance(subject, str) or "\x00" in subject:
            raise AgentsSyncFormatError(f"invalid commit subject at index {index}")
        committed_at = commit["committed_at"]
        if type(committed_at) is not int or committed_at < 0:
            raise AgentsSyncFormatError(f"invalid commit time at index {index}")
        commits.append(CommitRecord(sha, subject, committed_at))
    if commits != sorted(commits, key=lambda item: (item.committed_at, item.sha)):
        raise AgentsSyncFormatError("commits.json commits must be stably sorted")
    return V2RunCommitsPayload(
        _run_id(row["source_run_id"], "commits.json source_run_id"),
        tuple(commits),
    )


def _owner(value: object) -> AgentOwnerIdentity:
    row = _exact(value, "owner", {"username", "machine_name"})
    owner = AgentOwnerIdentity(
        validate_component(row["username"], label="username"),
        validate_component(row["machine_name"], label="machine"),
    )
    try:
        validate_agent_owner(owner)
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid owner: {exc}") from exc
    return owner


def _project(value: object) -> V2ProjectIdentity:
    row = _exact(value, "project", {"key", "name"})
    key = validate_component(row["key"], label="project key")
    name = row["name"]
    if not isinstance(name, str) or not name or "\x00" in name:
        raise AgentsSyncFormatError("project name must be a non-empty string")
    return V2ProjectIdentity(key, name)


def _schema(value: dict[str, Any], label: str) -> None:
    if value["schema_version"] != V2_SCHEMA_VERSION:
        raise AgentsSyncFormatError(
            f"unsupported {label} schema_version {value['schema_version']!r}; "
            f"expected {V2_SCHEMA_VERSION}"
        )


def _exact(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    row = _object(value, label)
    if set(row) != keys:
        raise AgentsSyncFormatError(f"{label} has an invalid shape")
    return row


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    return value


def _run_id(value: object, label: str) -> str:
    run_id = validate_component(value, label=label)
    if len(run_id.encode()) > 128:
        raise AgentsSyncFormatError(f"{label} is too long")
    return run_id


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AgentsSyncFormatError(f"{label} must be null or a non-empty string")
    return value


def _json_value(value: object, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AgentsSyncFormatError(f"{label} contains a non-JSON value") from exc


__all__ = [
    "run_commits_from_json",
    "run_metadata_from_json",
    "run_state_from_json",
]
