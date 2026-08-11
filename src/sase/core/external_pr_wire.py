"""Wire records for the external pull-request mirror classifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

EXTERNAL_PR_WIRE_SCHEMA_VERSION = 1

ACTION_ADOPT = "adopt"
ACTION_REPAIR_ORIGIN = "repair_origin"
ACTION_SKIP = "skip"

REASON_ALREADY_OWNED = "already_owned"
REASON_AMBIGUOUS_MARKER = "ambiguous_marker"
REASON_MARKER_ORPHAN = "marker_orphan"
REASON_MARKER_REPAIR = "marker_repair"
REASON_RACED_ALREADY_OWNED = "raced_already_owned"
REASON_UNMARKED = "unmarked"

PR_ORIGIN_EXTERNAL = "external"
PR_ORIGIN_SASE = "sase"
PR_ORIGIN_UNKNOWN = "unknown"

STATUS_ARCHIVED = "Archived"
STATUS_DRAFT = "Draft"
STATUS_MAILED = "Mailed"
STATUS_RESERVED = "Reserved"
STATUS_SUBMITTED = "Submitted"

DESTINATION_ACTIVE = "active"
DESTINATION_ARCHIVE = "archive"


@dataclass(frozen=True)
class CanonicalPullRequestUrl:
    host: str
    owner: str
    repo: str
    number: int
    key: str


@dataclass(frozen=True)
class RemotePullRequestWire:
    number: int
    url: str
    provider_id: str
    title: str
    body: str
    state: str
    is_draft: bool
    author: str
    head_ref: str
    base_ref: str
    created_at: str
    updated_at: str
    closed_at: str
    merged_at: str


@dataclass(frozen=True)
class LocalPatchWire:
    name: str
    pr_url: str
    pr_origin: str
    status: str
    archived: bool
    reserved: bool


@dataclass(frozen=True)
class ExternalPrImportRequestWire:
    schema_version: int
    remote: RemotePullRequestWire
    local_patches: tuple[LocalPatchWire, ...] = ()


@dataclass(frozen=True)
class ExternalPrImportPlanWire:
    action: str
    reason: str
    patch_name: str | None
    name_base: str | None
    pr_origin: str
    status: str
    destination: str
    description: str
    canonical_pr_url: str | None


def external_pr_request_to_json_dict(record: Any) -> Any:
    """Project external-PR wire dataclasses to a JSON-safe shape."""
    if isinstance(record, (list, tuple)):
        return [external_pr_request_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {str(k): external_pr_request_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def canonical_pull_request_url_from_dict(
    data: dict[str, Any] | None,
) -> CanonicalPullRequestUrl | None:
    if data is None:
        return None
    return CanonicalPullRequestUrl(
        host=str(data["host"]),
        owner=str(data["owner"]),
        repo=str(data["repo"]),
        number=int(data["number"]),
        key=str(data["key"]),
    )


def external_pr_plan_from_dict(data: dict[str, Any]) -> ExternalPrImportPlanWire:
    """Rehydrate an import plan from the Rust binding dict."""
    return ExternalPrImportPlanWire(
        action=str(data["action"]),
        reason=str(data["reason"]),
        patch_name=(
            None if data.get("patch_name") is None else str(data["patch_name"])
        ),
        name_base=(None if data.get("name_base") is None else str(data["name_base"])),
        pr_origin=str(data["pr_origin"]),
        status=str(data["status"]),
        destination=str(data["destination"]),
        description=str(data["description"]),
        canonical_pr_url=(
            None
            if data.get("canonical_pr_url") is None
            else str(data["canonical_pr_url"])
        ),
    )


__all__ = [
    "ACTION_ADOPT",
    "ACTION_REPAIR_ORIGIN",
    "ACTION_SKIP",
    "DESTINATION_ACTIVE",
    "DESTINATION_ARCHIVE",
    "EXTERNAL_PR_WIRE_SCHEMA_VERSION",
    "PR_ORIGIN_EXTERNAL",
    "PR_ORIGIN_SASE",
    "PR_ORIGIN_UNKNOWN",
    "REASON_ALREADY_OWNED",
    "REASON_AMBIGUOUS_MARKER",
    "REASON_MARKER_ORPHAN",
    "REASON_MARKER_REPAIR",
    "REASON_RACED_ALREADY_OWNED",
    "REASON_UNMARKED",
    "STATUS_ARCHIVED",
    "STATUS_DRAFT",
    "STATUS_MAILED",
    "STATUS_RESERVED",
    "STATUS_SUBMITTED",
    "CanonicalPullRequestUrl",
    "ExternalPrImportPlanWire",
    "ExternalPrImportRequestWire",
    "LocalPatchWire",
    "RemotePullRequestWire",
    "canonical_pull_request_url_from_dict",
    "external_pr_plan_from_dict",
    "external_pr_request_to_json_dict",
]
