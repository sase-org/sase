"""Strict hood-snapshot decoding and validation for v2 sidecars."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2RelationshipRecord,
    V2RelationshipTarget,
    V2RunRecord,
)
from sase.agents_sync.v2_validation import (
    MAX_CONTAINERS,
    MAX_FILES,
    MAX_RELATIONSHIPS,
    MAX_RUNS,
    V2_METADATA_FIELDS,
    decode_owner_identity,
    decode_project_identity,
    exact_object,
    json_list,
    json_object,
    nonnegative_int,
    optional_string,
    read_json,
    string_list,
    validate_digest,
    validate_component,
    validate_json_value,
    validate_output_variables,
    validate_relative_path,
    validate_run_id,
    validate_schema,
)
from sase.core.agent_archive_facade import capabilities_from_v2_run
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    globalize_agent_name,
    validate_agent_relationship_batch,
)

_STATES = {"active", "waiting", "completed", "failed", "stopped", "dismissed"}
_CONTAINER_KINDS = {"family", "clan"}
_RELATIONSHIP_KINDS = {"parent", "workflow_parent", "retry", "wait"}
_FILE_KINDS = {
    "meta",
    "state",
    "commits",
    "prompt",
    "chat",
    "embedded_workflows",
    "prompt_steps",
}


def read_hood_snapshot(path: Path) -> V2HoodSnapshot:
    return decode_hood_snapshot(read_json(path, "hood snapshot"))


def decode_hood_snapshot(value: object) -> V2HoodSnapshot:
    data = exact_object(
        value,
        "hood snapshot",
        {
            "schema_version",
            "owner",
            "project",
            "hood",
            "structural_ancestors",
            "runs",
            "containers",
            "relationships",
        },
    )
    validate_schema(data, "hood snapshot")
    owner = decode_owner_identity(data["owner"], "hood snapshot owner")
    project = decode_project_identity(data["project"])
    hood = exact_object(
        data["hood"], "hood snapshot hood", {"local_name", "global_name"}
    )
    local_hood = validate_component(hood["local_name"], label="local hood")
    global_hood = validate_component(hood["global_name"], label="global hood")
    if globalize_agent_name(local_hood, owner) != global_hood:
        raise AgentsSyncFormatError("hood global name is not canonical for its owner")
    structural_ancestors = string_list(
        data["structural_ancestors"],
        "hood snapshot structural_ancestors",
        MAX_CONTAINERS,
    )
    for ancestor in structural_ancestors:
        validate_component(ancestor, label="structural ancestor")
    if tuple(sorted(set(structural_ancestors))) != structural_ancestors:
        raise AgentsSyncFormatError(
            "hood snapshot structural_ancestors must be unique and sorted"
        )
    runs = _runs(data["runs"], owner)
    containers = _containers(data["containers"], owner)
    relationships = _relationships(data["relationships"])
    snapshot = V2HoodSnapshot(
        owner,
        project,
        local_hood,
        global_hood,
        structural_ancestors,
        runs,
        containers,
        relationships,
    )
    try:
        validate_agent_relationship_batch(snapshot.relationship_batch())
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid hood relationships: {exc}") from exc
    return snapshot


def validate_snapshot(snapshot: V2HoodSnapshot) -> None:
    """Round-trip the strict decoder and Rust relationship validator."""

    decode_hood_snapshot(snapshot.to_json_dict())


def _runs(value: object, owner: AgentOwnerIdentity) -> tuple[V2RunRecord, ...]:
    rows = json_list(value, "hood snapshot runs", MAX_RUNS)
    runs = tuple(_run(row, owner, index) for index, row in enumerate(rows))
    if tuple(sorted(runs, key=lambda item: item.source_run_id)) != runs:
        raise AgentsSyncFormatError("hood snapshot runs must be stably sorted")
    return runs


def _run(value: object, owner: AgentOwnerIdentity, index: int) -> V2RunRecord:
    label = f"hood snapshot runs[{index}]"
    raw = json_object(value, label)
    base_keys = {
        "source_run_id",
        "local_name",
        "global_name",
        "state",
        "started_at",
        "finished_at",
        "dismissed_at",
        "metadata",
        "commits",
        "files",
    }
    row = exact_object(
        raw,
        label,
        base_keys | ({"capabilities"} if "capabilities" in raw else set()),
    )
    run_id = row["source_run_id"]
    try:
        validate_run_id(run_id, label)
    except AgentsSyncFormatError:
        raise AgentsSyncFormatError(f"{label} has an invalid source_run_id") from None
    local_name = validate_component(row["local_name"], label=f"{label} local_name")
    global_name = validate_component(row["global_name"], label=f"{label} global_name")
    if globalize_agent_name(local_name, owner) != global_name:
        raise AgentsSyncFormatError(f"{label} global_name is not canonical")
    state = row["state"]
    if state not in _STATES:
        raise AgentsSyncFormatError(f"{label} has an invalid state")
    metadata = json_object(row["metadata"], f"{label} metadata")
    unknown = set(metadata) - V2_METADATA_FIELDS
    if unknown:
        raise AgentsSyncFormatError(
            f"{label} metadata has unsupported fields: {', '.join(sorted(unknown))}"
        )
    validate_output_variables(metadata, label=f"{label} metadata")
    validate_json_value(metadata, f"{label} metadata")
    commits = _commits(row["commits"], label)
    raw_files = json_object(row["files"], f"{label} files")
    if set(raw_files) - _FILE_KINDS:
        raise AgentsSyncFormatError(f"{label} has unsupported file kinds")
    files = tuple(
        (kind, _file_ref(raw, f"{label} file {kind}"))
        for kind, raw in sorted(raw_files.items())
    )
    try:
        capabilities = capabilities_from_v2_run(
            metadata,
            set(raw_files),
            asserted=row.get("capabilities") if "capabilities" in row else None,
        )
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"{label} has invalid capabilities: {exc}") from exc
    return V2RunRecord(
        run_id,
        local_name,
        global_name,
        state,
        optional_string(row["started_at"], f"{label} started_at"),
        optional_string(row["finished_at"], f"{label} finished_at"),
        optional_string(row["dismissed_at"], f"{label} dismissed_at"),
        tuple(sorted(metadata.items())),
        commits,
        files,
        capabilities,
    )


def _containers(
    value: object, owner: AgentOwnerIdentity
) -> tuple[V2ContainerRecord, ...]:
    rows = json_list(value, "hood snapshot containers", MAX_CONTAINERS)
    result: list[V2ContainerRecord] = []
    for index, value in enumerate(rows):
        label = f"hood snapshot containers[{index}]"
        base_keys = {"kind", "global_name", "owner", "member_source_run_ids"}
        raw = json_object(value, label)
        row = exact_object(
            raw,
            label,
            base_keys | ({"commits"} if "commits" in raw else set()),
        )
        if decode_owner_identity(row["owner"], f"{label} owner") != owner:
            raise AgentsSyncFormatError(f"{label} belongs to another owner")
        kind = row["kind"]
        if kind not in _CONTAINER_KINDS:
            raise AgentsSyncFormatError(f"{label} has an invalid kind")
        global_name = validate_component(row["global_name"], label="container name")
        members = string_list(
            row["member_source_run_ids"], f"{label} members", MAX_RUNS
        )
        commits = _commits(row["commits"], label) if "commits" in row else ()
        if len({commit.sha for commit in commits}) != len(commits):
            raise AgentsSyncFormatError(f"{label} commits must have unique SHAs")
        if kind == "clan" and commits:
            raise AgentsSyncFormatError(f"{label} clan commits must be empty")
        result.append(V2ContainerRecord(kind, global_name, members, commits))
    output = tuple(result)
    if tuple(sorted(output, key=lambda item: (item.kind, item.global_name))) != output:
        raise AgentsSyncFormatError("hood snapshot containers must be stably sorted")
    return output


def _relationships(value: object) -> tuple[V2RelationshipRecord, ...]:
    rows = json_list(value, "hood snapshot relationships", MAX_RELATIONSHIPS)
    output: list[V2RelationshipRecord] = []
    for index, value in enumerate(rows):
        label = f"hood snapshot relationships[{index}]"
        row = exact_object(
            value, label, {"kind", "source_run_id", "target", "required"}
        )
        kind = row["kind"]
        if kind not in _RELATIONSHIP_KINDS:
            raise AgentsSyncFormatError(f"{label} has an invalid kind")
        source = validate_run_id(row["source_run_id"], f"{label} source_run_id")
        required = row["required"]
        if type(required) is not bool:
            raise AgentsSyncFormatError(f"{label} required must be boolean")
        target_row = json_object(row["target"], f"{label} target")
        target_kind = target_row.get("kind")
        if target_kind == "source_run_id":
            target_row = exact_object(
                target_row, f"{label} target", {"kind", "source_run_id"}
            )
            target = V2RelationshipTarget(
                "source_run_id",
                source_run_id=validate_run_id(
                    target_row["source_run_id"], f"{label} target source_run_id"
                ),
            )
        elif target_kind == "global_name":
            target_row = exact_object(
                target_row, f"{label} target", {"kind", "global_name", "owner"}
            )
            target = V2RelationshipTarget(
                "global_name",
                global_name=validate_component(
                    target_row["global_name"], label=f"{label} target global_name"
                ),
                owner=decode_owner_identity(
                    target_row["owner"], f"{label} target owner"
                ),
            )
        else:
            raise AgentsSyncFormatError(f"{label} has an invalid target kind")
        output.append(V2RelationshipRecord(kind, source, target, required))
    return tuple(output)


def _file_ref(value: object, label: str) -> V2FileReference:
    row = exact_object(value, label, {"path", "digest", "size_bytes"})
    return V2FileReference(
        validate_relative_path(row["path"]),
        validate_digest(row["digest"], f"{label} digest"),
        nonnegative_int(row["size_bytes"], f"{label} size_bytes"),
    )


def _commits(value: object, label: str) -> tuple[CommitRecord, ...]:
    rows = json_list(value, f"{label} commits", MAX_FILES)
    commits: list[CommitRecord] = []
    for index, value in enumerate(rows):
        row = exact_object(
            value,
            f"{label} commits[{index}]",
            {"sha", "subject", "committed_at"},
        )
        sha = row["sha"]
        if not isinstance(sha, str) or not (7 <= len(sha) <= 64):
            raise AgentsSyncFormatError(f"{label} has an invalid commit SHA")
        if any(character not in "0123456789abcdef" for character in sha):
            raise AgentsSyncFormatError(f"{label} has an invalid commit SHA")
        subject = row["subject"]
        if not isinstance(subject, str) or "\x00" in subject:
            raise AgentsSyncFormatError(f"{label} has an invalid commit subject")
        commits.append(
            CommitRecord(
                sha,
                subject,
                nonnegative_int(row["committed_at"], "committed_at"),
            )
        )
    output = tuple(commits)
    if tuple(sorted(output, key=lambda item: (item.committed_at, item.sha))) != output:
        raise AgentsSyncFormatError(f"{label} commits must be stably sorted")
    return output


__all__ = ["read_hood_snapshot", "validate_snapshot"]
