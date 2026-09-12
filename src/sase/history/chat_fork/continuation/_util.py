"""Shared types and hashing helpers for continuation fork replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from sase.core.continuation_wire import ContinuationExecutionIdentityWire

_BlockKind = Literal[
    "agent_delta",
    "monitor_result",
    "legacy_boundary",
    "checkpoint",
]

# Match the Rust continuation text bound so opaque protected blobs stay
# representable as a single validated field or else refuse automatic launch.
MAX_PROTECTED_LEGACY_BYTES = 256 * 1024
MAX_HYDRATION_NODES = 10_000
STRICT_EVIDENCE_POLICIES = frozenset({"none", "file"})
AUTOMATIC_REFUSAL_OMISSIONS = frozenset(
    {
        "missing_parent",
        "missing_root",
        "missing_source",
        "digest_mismatch",
        "legacy_evidence_policy_conflict",
        "protected_content_over_budget",
        "failed_starter_without_checkpoint",
    }
)


class ContinuationSourceError(ValueError):
    """A local or portable continuation ref could not be resolved safely."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class ContinuationReplayRefusal(ValueError):
    """Automatic continuation launch cannot proceed with this replay."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class BlockContent:
    kind: _BlockKind
    label: str
    payload: Mapping[str, Any]


def owner(
    *,
    project: str,
    run_id: str,
    agent_name: str,
    workspace_id: object,
) -> ContinuationExecutionIdentityWire:
    identity: ContinuationExecutionIdentityWire = {
        "project": safe_identifier(project),
        "run_id": safe_identifier(run_id),
        "agent_name": safe_identifier(agent_name),
    }
    if workspace_id is not None:
        identity["workspace_id"] = safe_identifier(workspace_id)
    return identity


def optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or any(ch.isspace() for ch in value):
        return f"ref:{_sha_text(value)[:16]}"
    return value


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def number_or_none(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def block_payload_size(content: BlockContent) -> int:
    return len(_json_bytes(content.payload))


def sha_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return str(value)


def safe_identifier(value: object, *, max_len: int = 80) -> str:
    text = str(value).strip() or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in text)
    safe = safe.strip("_.:-") or "unknown"
    if len(safe.encode("utf-8")) <= max_len:
        return safe
    digest = _sha_text(safe)[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{safe[:keep]}:{digest}"


def unique_strings(values: Sequence[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def iter_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
