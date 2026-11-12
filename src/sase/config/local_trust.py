"""Thin Python adapter for the Rust local-command trust contract.

Phase ``trust-policy`` exposes the pure-Rust command-bearing projection,
canonical digest, filtering, and trust-decision contracts without changing
runtime command loading. Enforcement phases consume this adapter; nothing
here filters merged config or file hooks on its own.

The digest covers the canonical command-bearing projection only, not the
transitive contents of scripts, binaries, or standalone macro files it
invokes. See the child-epic plan ``202611/local_config_digest_trust.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.rust import require_rust_binding

LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION = 1
LOCAL_COMMAND_TRUST_POLICY_VERSION = 1
LOCAL_COMMAND_DIGEST_DOMAIN = "sase.local-commands/v1:"


class LocalCommandTrustError(ValueError):
    """Raised when the trust wire payload is malformed or version-skewed."""


def _check_wire_version(payload: dict[str, Any]) -> None:
    version = payload.get("schema_version")
    if version != LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION:
        raise LocalCommandTrustError(
            "unsupported local-command trust wire version: "
            f"{version!r} (expected "
            f"{LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION})"
        )


@dataclass(frozen=True)
class LocalCommandProjection:
    """Normalized command-bearing projection of one local layer."""

    projection: dict[str, Any]
    blocked_paths: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]
    digest: str
    canonical_json: str
    policy_version: int = LOCAL_COMMAND_TRUST_POLICY_VERSION

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> LocalCommandProjection:
        """Rehydrate a Rust projection payload, checking its wire version."""
        if not isinstance(payload, dict):
            raise LocalCommandTrustError("local-command projection is not an object")
        _check_wire_version(payload)
        projection = payload.get("projection")
        blocked = payload.get("blocked_paths")
        diagnostics = payload.get("diagnostics")
        digest = payload.get("digest")
        canonical = payload.get("canonical_json")
        policy = payload.get("policy_version", LOCAL_COMMAND_TRUST_POLICY_VERSION)
        if not isinstance(projection, dict):
            raise LocalCommandTrustError("projection.projection is not an object")
        if not isinstance(blocked, list) or not all(
            isinstance(path, str) for path in blocked
        ):
            raise LocalCommandTrustError("projection.blocked_paths is not a list")
        if not isinstance(diagnostics, list):
            raise LocalCommandTrustError("projection.diagnostics is not a list")
        if not isinstance(digest, str) or len(digest) != 64:
            raise LocalCommandTrustError("projection.digest is not a sha256 hex")
        if not isinstance(canonical, str):
            raise LocalCommandTrustError("projection.canonical_json is not a string")
        if policy != LOCAL_COMMAND_TRUST_POLICY_VERSION:
            raise LocalCommandTrustError(
                f"unsupported trust policy version: {policy!r}"
            )
        return cls(
            projection=projection,
            blocked_paths=tuple(blocked),
            diagnostics=tuple(diagnostics),
            digest=digest,
            canonical_json=canonical,
            policy_version=policy,
        )


@dataclass(frozen=True)
class LocalTrustFilterResult:
    """Effective local contribution for one trust verdict."""

    effective_layer: dict[str, Any]
    removed_paths: tuple[str, ...]
    status: str
    reason: str

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> LocalTrustFilterResult:
        """Rehydrate a Rust filter payload, checking its wire version."""
        if not isinstance(payload, dict):
            raise LocalCommandTrustError("trust filter result is not an object")
        _check_wire_version(payload)
        effective = payload.get("effective_layer")
        removed = payload.get("removed_paths")
        status = payload.get("status")
        reason = payload.get("reason")
        if not isinstance(effective, dict):
            raise LocalCommandTrustError("filter.effective_layer is not an object")
        if not isinstance(removed, list) or not all(
            isinstance(path, str) for path in removed
        ):
            raise LocalCommandTrustError("filter.removed_paths is not a list")
        if not isinstance(status, str) or not isinstance(reason, str):
            raise LocalCommandTrustError("filter status/reason must be strings")
        return cls(
            effective_layer=effective,
            removed_paths=tuple(removed),
            status=status,
            reason=reason,
        )


@dataclass(frozen=True)
class LocalTrustDecision:
    """Structured trust status for a current/acknowledged digest pair."""

    status: str
    reason: str

    @property
    def trusted(self) -> bool:
        """Return whether the decision permits local command execution."""
        return self.status == "trusted"


@dataclass(frozen=True)
class LocalCommandDigest:
    """Canonical digest of one command-bearing projection."""

    digest: str
    canonical_json: str = field(repr=False)

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> LocalCommandDigest:
        """Rehydrate a Rust digest payload, checking its wire version."""
        if not isinstance(payload, dict):
            raise LocalCommandTrustError("local-command digest is not an object")
        _check_wire_version(payload)
        digest = payload.get("digest")
        canonical = payload.get("canonical_json")
        if not isinstance(digest, str) or len(digest) != 64:
            raise LocalCommandTrustError("digest.digest is not a sha256 hex")
        if not isinstance(canonical, str):
            raise LocalCommandTrustError("digest.canonical_json is not a string")
        return cls(digest=digest, canonical_json=canonical)


def local_command_trust_wire_schema_version() -> int:
    """Return the Rust local-command trust wire schema version."""
    binding = require_rust_binding("local_command_trust_wire_schema_version")
    version = binding()
    if version != LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION:
        raise LocalCommandTrustError(
            f"core trust wire version {version!r} does not match Python "
            f"{LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION}"
        )
    return int(version)


def project_local_commands(
    layer: dict[str, Any],
    *,
    lower_macros: dict[str, Any] | None = None,
    lower_workflows: dict[str, Any] | None = None,
    source: str = "local_config",
) -> LocalCommandProjection:
    """Project the command-bearing subset of one decoded local layer.

    Legacy macro spellings are normalized before classification. A sparse
    local override of a lower-layer executable definition is command-bearing
    even when it supplies only inputs or metadata.
    """
    binding = require_rust_binding("project_local_commands")
    payload: Any = binding(
        {
            "layer": dict(layer),
            "lower_macros": dict(lower_macros or {}),
            "lower_workflows": dict(lower_workflows or {}),
            "source": source,
        }
    )
    if not isinstance(payload, dict):
        raise LocalCommandTrustError("project_local_commands returned no mapping")
    return LocalCommandProjection.from_wire(payload)


def digest_local_commands(projection: dict[str, Any]) -> LocalCommandDigest:
    """Hash one already-projected command-bearing value."""
    binding = require_rust_binding("digest_local_commands")
    payload: Any = binding({"projection": dict(projection)})
    if not isinstance(payload, dict):
        raise LocalCommandTrustError("digest_local_commands returned no mapping")
    return LocalCommandDigest.from_wire(payload)


def filter_trusted_local_layer(
    layer: dict[str, Any],
    *,
    trusted: bool,
    lower_macros: dict[str, Any] | None = None,
    lower_workflows: dict[str, Any] | None = None,
    source: str = "local_config",
) -> LocalTrustFilterResult:
    """Apply one trust verdict to one decoded local layer.

    Untrusted filtering removes the whole local ``commit_hooks``
    contribution, omits blocked file-hook entries, and drops only
    command-bearing macro/workflow definitions, preserving ordinary local
    values. The same decoded snapshot is digested and filtered.
    """
    binding = require_rust_binding("filter_trusted_local_layer")
    payload: Any = binding(
        {
            "layer": dict(layer),
            "trusted": bool(trusted),
            "lower_macros": dict(lower_macros or {}),
            "lower_workflows": dict(lower_workflows or {}),
            "source": source,
        }
    )
    if not isinstance(payload, dict):
        raise LocalCommandTrustError("filter_trusted_local_layer returned no mapping")
    return LocalTrustFilterResult.from_wire(payload)


def decide_local_command_trust(
    current_digest: str,
    acknowledged_digest: str | None,
    *,
    current_policy_version: int = LOCAL_COMMAND_TRUST_POLICY_VERSION,
    acknowledged_policy_version: int | None = None,
) -> LocalTrustDecision:
    """Compare the current and acknowledged digests with policy versions."""
    binding = require_rust_binding("decide_local_command_trust")
    payload: Any = binding(
        {
            "current_digest": current_digest,
            "acknowledged_digest": acknowledged_digest,
            "current_policy_version": current_policy_version,
            "acknowledged_policy_version": acknowledged_policy_version,
        }
    )
    if not isinstance(payload, dict):
        raise LocalCommandTrustError("decide_local_command_trust returned no mapping")
    _check_wire_version(payload)
    status = payload.get("status")
    reason = payload.get("reason")
    if not isinstance(status, str) or not isinstance(reason, str):
        raise LocalCommandTrustError("decision status/reason must be strings")
    return LocalTrustDecision(status=status, reason=reason)


__all__ = [
    "LOCAL_COMMAND_DIGEST_DOMAIN",
    "LOCAL_COMMAND_TRUST_POLICY_VERSION",
    "LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION",
    "LocalCommandDigest",
    "LocalCommandProjection",
    "LocalCommandTrustError",
    "LocalTrustDecision",
    "LocalTrustFilterResult",
    "decide_local_command_trust",
    "digest_local_commands",
    "filter_trusted_local_layer",
    "local_command_trust_wire_schema_version",
    "project_local_commands",
]
