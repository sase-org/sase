"""Rust-backed policy facade for agents-sidecar content protection."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION = 1


def publication_scan_disposition(
    *,
    scan: dict[str, object] | None = None,
    failure: str | None = None,
) -> dict[str, object]:
    """Map a scanner result or scanner failure into the Rust policy contract."""
    binding = require_rust_binding("publication_scan_disposition")
    raw = binding(
        {
            "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
            "scan": scan,
            "failure": failure,
        }
    )
    return _wire_dict(raw, "scan disposition")


def publication_protection_ledger_empty() -> dict[str, object]:
    """Return a Rust-owned empty protection ledger."""
    binding = require_rust_binding("publication_protection_ledger_empty")
    return _wire_dict(binding(), "protection ledger")


def publication_protection_ledger_validate(
    ledger: dict[str, object],
) -> dict[str, object]:
    """Validate and normalize one durable ledger through Rust core."""
    binding = require_rust_binding("publication_protection_ledger_validate")
    return _wire_dict(binding(ledger), "protection ledger")


def publication_protection_record_from_scan(
    request: dict[str, object],
) -> dict[str, object] | None:
    """Create a durable protection row for a blocked or unverified scan."""
    binding = require_rust_binding("publication_protection_record_from_scan")
    raw = binding(request)
    if raw is not None and not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict protection record")
    return raw


def publication_protection_record_from_rejection(
    request: dict[str, object],
) -> dict[str, object] | None:
    """Create a block only for a Rust-classified secret-scanning rejection."""
    binding = require_rust_binding("publication_protection_record_from_rejection")
    raw = binding(request)
    if raw is not None and not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict protection record")
    return raw


def publication_protection_upsert(
    ledger: dict[str, object],
    record: dict[str, object],
) -> dict[str, object]:
    """Apply a Rust-owned idempotent content-record transition."""
    binding = require_rust_binding("publication_protection_upsert")
    return _wire_dict(
        binding(
            {
                "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
                "ledger": ledger,
                "record": record,
            }
        ),
        "protection ledger",
    )


def publication_protection_lookup(
    ledger: dict[str, object],
    identity: dict[str, object],
) -> dict[str, object] | None:
    """Look up one repository, path, and digest identity through Rust core."""
    binding = require_rust_binding("publication_protection_lookup")
    raw = binding(
        {
            "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
            "ledger": ledger,
            "identity": identity,
        }
    )
    if raw is not None and not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned a non-dict protection lookup")
    return raw


def publication_protection_retry_allowed(
    ledger: dict[str, object],
    identity: dict[str, object],
) -> bool:
    """Return whether the exact content digest may be considered for retry."""
    binding = require_rust_binding("publication_protection_retry_allowed")
    raw = binding(
        {
            "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
            "ledger": ledger,
            "identity": identity,
        }
    )
    if not isinstance(raw, bool):
        raise RuntimeError("sase_core_rs returned a non-bool retry decision")
    return raw


def publication_protection_resolve_verified_clean(
    ledger: dict[str, object],
    identity: dict[str, object],
) -> dict[str, object]:
    """Clear only a transient unverified row after a complete clean scan."""
    binding = require_rust_binding("publication_protection_resolve_verified_clean")
    return _wire_dict(
        binding(
            {
                "schema_version": AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION,
                "ledger": ledger,
                "identity": identity,
            }
        ),
        "protection ledger",
    )


def _wire_dict(raw: Any, label: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"sase_core_rs returned a non-dict {label}")
    version = raw.get("schema_version")
    if version != AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(f"sase_core_rs {label} wire is stale: {version}")
    return raw


__all__ = [
    "AGENT_PUBLICATION_PROTECTION_WIRE_SCHEMA_VERSION",
    "publication_protection_ledger_empty",
    "publication_protection_ledger_validate",
    "publication_protection_lookup",
    "publication_protection_record_from_rejection",
    "publication_protection_record_from_scan",
    "publication_protection_retry_allowed",
    "publication_protection_resolve_verified_clean",
    "publication_protection_upsert",
    "publication_scan_disposition",
]
