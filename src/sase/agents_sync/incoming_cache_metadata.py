"""Metadata identities and validation for immutable incoming cache objects."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
import re

from sase.agents_sync.io import (
    AgentsSyncFormatError,
    canonical_json_bytes,
    validate_machine,
)
from sase.agents_sync.models import (
    CACHE_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    AgentHoodImportReceipt,
    CapturedIncomingHood,
    SourceOwnerKind,
)
from sase.agents_sync.v2_io import validate_component
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    agent_local_hood,
    validate_agent_owner,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CAPTURED_KEYS = {
    "schema_version",
    "project_key",
    "project",
    "fetched_ref",
    "fetched_sha",
    "cache_id",
    "format_version",
    "source_owner_kind",
    "source_username",
    "source_machine",
    "top_hood",
    "hood_digest",
    "run_count",
    "family_count",
    "cache_created_at",
}
_RECEIPT_KEYS = {
    "schema_version",
    "project_key",
    "project",
    "source_owner_kind",
    "source_username",
    "source_machine",
    "top_hood",
    "hood_digest",
    "cache_id",
    "fetched_ref",
    "fetched_sha",
    "cache_created_at",
    "applied_at",
}


def cache_id_for(
    *,
    project_key: str,
    project: str,
    format_version: int,
    source_owner_kind: SourceOwnerKind,
    source_username: str | None,
    source_machine: str,
    top_hood: str,
    hood_digest: str,
) -> str:
    """Return the stable content address for one semantic source hood."""

    identity = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "project_key": project_key,
        "project": project,
        "format_version": format_version,
        "source_owner_kind": source_owner_kind,
        "source_username": source_username,
        "source_machine": source_machine,
        "top_hood": top_hood,
        "hood_digest": hood_digest,
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def captured_incoming_hood_from_json(value: object) -> CapturedIncomingHood:
    row = exact_object(value, "captured incoming hood", _CAPTURED_KEYS)
    if row["schema_version"] != CACHE_SCHEMA_VERSION:
        raise AgentsSyncFormatError("unsupported captured incoming hood schema")
    kind, username = _source_owner(row)
    format_version = _nonnegative_int(row["format_version"], "format_version")
    if format_version not in {1, 2}:
        raise AgentsSyncFormatError("format_version must be 1 or 2")
    item = CapturedIncomingHood(
        project_key=metadata_component(row["project_key"], "project key"),
        project=project_name(row["project"]),
        fetched_ref=_fetched_ref(row["fetched_ref"]),
        fetched_sha=_sha(row["fetched_sha"], "fetched SHA"),
        cache_id=validate_digest(row["cache_id"], "cache ID"),
        format_version=format_version,
        source_owner_kind=kind,
        source_username=username,
        source_machine=metadata_component(row["source_machine"], "source machine"),
        top_hood=metadata_component(row["top_hood"], "top hood"),
        hood_digest=validate_digest(row["hood_digest"], "hood digest"),
        run_count=_nonnegative_int(row["run_count"], "run_count"),
        family_count=_nonnegative_int(row["family_count"], "family_count"),
        cache_created_at=_finite_time(row["cache_created_at"], "cache creation time"),
    )
    _validate_source_hood(
        item.source_owner_kind,
        item.source_username,
        item.source_machine,
        item.top_hood,
    )
    if item.cache_id != _item_cache_id(item):
        raise AgentsSyncFormatError("captured incoming hood cache ID is inconsistent")
    return item


def import_receipt_from_json(value: object) -> AgentHoodImportReceipt:
    row = exact_object(value, "agent hood import receipt", _RECEIPT_KEYS)
    if row["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise AgentsSyncFormatError("unsupported agent hood receipt schema")
    kind, username = _source_owner(row)
    receipt = AgentHoodImportReceipt(
        project_key=metadata_component(row["project_key"], "project key"),
        project=project_name(row["project"]),
        source_owner_kind=kind,
        source_username=username,
        source_machine=metadata_component(row["source_machine"], "source machine"),
        top_hood=metadata_component(row["top_hood"], "top hood"),
        hood_digest=validate_digest(row["hood_digest"], "hood digest"),
        cache_id=validate_digest(row["cache_id"], "cache ID"),
        fetched_ref=_fetched_ref(row["fetched_ref"]),
        fetched_sha=_sha(row["fetched_sha"], "fetched SHA"),
        cache_created_at=_finite_time(row["cache_created_at"], "cache creation time"),
        applied_at=_finite_time(row["applied_at"], "receipt application time"),
    )
    _validate_source_hood(
        receipt.source_owner_kind,
        receipt.source_username,
        receipt.source_machine,
        receipt.top_hood,
    )
    expected = cache_id_for(
        project_key=receipt.project_key,
        project=receipt.project,
        format_version=(1 if receipt.source_owner_kind == "username_unknown_v1" else 2),
        source_owner_kind=receipt.source_owner_kind,
        source_username=receipt.source_username,
        source_machine=receipt.source_machine,
        top_hood=receipt.top_hood,
        hood_digest=receipt.hood_digest,
    )
    if receipt.cache_id != expected:
        raise AgentsSyncFormatError("agent hood receipt cache ID is inconsistent")
    return receipt


def with_cache_id(item: CapturedIncomingHood) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key=item.project_key,
        project=item.project,
        fetched_ref=item.fetched_ref,
        fetched_sha=item.fetched_sha,
        cache_id=_item_cache_id(item),
        format_version=item.format_version,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
        run_count=item.run_count,
        family_count=item.family_count,
        cache_created_at=item.cache_created_at,
    )


def _item_cache_id(item: CapturedIncomingHood) -> str:
    return cache_id_for(
        project_key=item.project_key,
        project=item.project,
        format_version=item.format_version,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
    )


def same_cached_content(
    left: CapturedIncomingHood,
    right: CapturedIncomingHood,
) -> bool:
    return (
        left.project_key,
        left.project,
        left.cache_id,
        left.format_version,
        left.source_owner_kind,
        left.source_username,
        left.source_machine,
        left.top_hood,
        left.hood_digest,
        left.run_count,
        left.family_count,
    ) == (
        right.project_key,
        right.project,
        right.cache_id,
        right.format_version,
        right.source_owner_kind,
        right.source_username,
        right.source_machine,
        right.top_hood,
        right.hood_digest,
        right.run_count,
        right.family_count,
    )


def receipt_matches(
    receipt: AgentHoodImportReceipt | None,
    item: CapturedIncomingHood,
) -> bool:
    return receipt is not None and receipt.hood_digest == item.hood_digest


def _source_owner(
    row: Mapping[str, object],
) -> tuple[SourceOwnerKind, str | None]:
    kind = row["source_owner_kind"]
    username = row["source_username"]
    if kind == "exact":
        return "exact", metadata_component(username, "source username")
    if kind == "username_unknown_v1" and username is None:
        return "username_unknown_v1", None
    raise AgentsSyncFormatError("source owner kind and username are inconsistent")


def _validate_source_hood(
    kind: SourceOwnerKind,
    username: str | None,
    machine: str,
    hood: str,
) -> None:
    try:
        if kind == "exact":
            assert username is not None
            validate_agent_owner(AgentOwnerIdentity(username, machine))
        else:
            validate_machine(machine)
        if agent_local_hood(hood) != hood:
            raise AgentsSyncFormatError("top hood is not a semantic hood root")
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid source hood identity: {exc}") from exc


def exact_object(
    value: object,
    label: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    if set(value) != keys:
        raise AgentsSyncFormatError(f"{label} has an invalid shape")
    return value


def metadata_component(value: object, label: str) -> str:
    return validate_component(value, label=label)


def project_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise AgentsSyncFormatError("project name is invalid")
    return value


def _fetched_ref(value: object) -> str:
    if value == "HEAD":
        return "HEAD"
    if (
        not isinstance(value, str)
        or not value.startswith("refs/remotes/")
        or len(value.encode("utf-8")) > 1024
        or any(ord(char) <= 32 or char in "~^:?*[\\" for char in value)
        or ".." in value
        or value.endswith((".", "/"))
    ):
        raise AgentsSyncFormatError(f"fetched ref is invalid: {value!r}")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def validate_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise AgentsSyncFormatError(f"{label} must be a non-negative integer")
    return value


def _finite_time(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise AgentsSyncFormatError(f"{label} must be a finite non-negative number")
    return float(value)
