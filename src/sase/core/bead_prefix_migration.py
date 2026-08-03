"""Python facade for Rust bead prefix migration primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_bead_store_write_sandboxed


@dataclass(frozen=True)
class BeadIdTokenRewriteOutcome:
    text: str
    replacement_counts: dict[str, int]
    total_replacements: int


@dataclass(frozen=True)
class BeadPrefixMigrationRequest:
    from_prefix: str
    to_prefix: str
    agent_name_map: dict[str, str] | None = None
    expected_preimage_digest: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "from_prefix": self.from_prefix,
            "to_prefix": self.to_prefix,
            "agent_name_map": dict(self.agent_name_map or {}),
            "expected_preimage_digest": self.expected_preimage_digest,
        }


@dataclass(frozen=True)
class BeadPrefixMigrationOutcome:
    schema_version: int
    preimage_digest: str
    postimage_digest: str
    changed: bool
    bead_id_map: dict[str, str]
    event_id_map: dict[str, str]
    token_counts: dict[str, int]
    total_token_replacements: int
    stream_count: int
    event_count: int
    issue_count: int
    alias_additions: dict[str, str]
    lock_wait_ms: int = 0


def validate_issue_prefix(prefix: str) -> None:
    binding = require_rust_binding("bead_validate_issue_prefix")
    binding(prefix)


def rewrite_id_tokens(
    text: str,
    replacements: dict[str, str],
) -> BeadIdTokenRewriteOutcome:
    binding = require_rust_binding("bead_rewrite_id_tokens")
    return _token_outcome_from_wire(dict(binding(text, replacements)))


def preview_prefix_migration(
    beads_dir: Path | str,
    request: BeadPrefixMigrationRequest,
) -> BeadPrefixMigrationOutcome:
    binding = require_rust_binding("bead_prefix_migration_preview")
    return _migration_outcome_from_wire(
        dict(binding(str(beads_dir), request.to_wire()))
    )


def apply_prefix_migration(
    beads_dir: Path | str,
    request: BeadPrefixMigrationRequest,
) -> BeadPrefixMigrationOutcome:
    assert_bead_store_write_sandboxed(beads_dir, operation="prefix_migration")
    binding = require_rust_binding("bead_prefix_migration_apply")
    return _migration_outcome_from_wire(
        dict(binding(str(beads_dir), request.to_wire()))
    )


def _token_outcome_from_wire(
    payload: dict[str, Any],
) -> BeadIdTokenRewriteOutcome:
    return BeadIdTokenRewriteOutcome(
        text=str(payload.get("text", "")),
        replacement_counts=_int_map(payload.get("replacement_counts", {})),
        total_replacements=int(payload.get("total_replacements", 0)),
    )


def _migration_outcome_from_wire(
    payload: dict[str, Any],
) -> BeadPrefixMigrationOutcome:
    return BeadPrefixMigrationOutcome(
        schema_version=int(payload["schema_version"]),
        preimage_digest=str(payload["preimage_digest"]),
        postimage_digest=str(payload["postimage_digest"]),
        changed=bool(payload["changed"]),
        bead_id_map=_string_map(payload.get("bead_id_map", {})),
        event_id_map=_string_map(payload.get("event_id_map", {})),
        token_counts=_int_map(payload.get("token_counts", {})),
        total_token_replacements=int(payload.get("total_token_replacements", 0)),
        stream_count=int(payload.get("stream_count", 0)),
        event_count=int(payload.get("event_count", 0)),
        issue_count=int(payload.get("issue_count", 0)),
        alias_additions=_string_map(payload.get("alias_additions", {})),
        lock_wait_ms=int(payload.get("lock_wait_ms", 0)),
    )


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _int_map(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): int(item) for key, item in value.items()}


__all__ = [
    "BeadIdTokenRewriteOutcome",
    "BeadPrefixMigrationOutcome",
    "BeadPrefixMigrationRequest",
    "apply_prefix_migration",
    "preview_prefix_migration",
    "rewrite_id_tokens",
    "validate_issue_prefix",
]
