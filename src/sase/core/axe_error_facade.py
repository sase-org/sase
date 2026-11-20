"""Thin facade over the Rust axe error-signature engine.

The Rust core owns signature normalization (volatile-token masking) and
the pure entry-grouping fold. Python owns entry collection, the durable
interval counter, and the sample ring in ``sase.axe.state``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def _axe_error_wire_schema_version() -> int:
    """Return the axe error-group wire schema version from ``sase_core_rs``."""
    binding = require_rust_binding("axe_error_wire_schema_version")
    return int(binding())


def normalize_error_signature(text: str) -> str:
    """Turn scheduler error text into a stable grouping signature."""
    binding = require_rust_binding("normalize_error_signature")
    return str(binding(text))


def signature_for_entry(entry: Mapping[str, Any]) -> str:
    """Return the grouping signature for one error-ring entry.

    An entry's explicit ``failure_signature`` wins; otherwise the
    signature comes from its ``error`` text.
    """
    explicit = entry.get("failure_signature")
    if isinstance(explicit, str) and explicit:
        return explicit
    error = entry.get("error", "")
    return normalize_error_signature(error if isinstance(error, str) else str(error))


def group_errors(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold entries into per-cause groups in first-seen group order.

    Each input entry carries ``routine``, ``job``, ``signature``,
    ``timestamp``, and ``sample``. The response carries ``schema_version``
    and ``groups`` (each with ``routine``, ``job``, ``signature``,
    ``count``, ``first_ts``, ``last_ts``, and one bounded ``sample``).
    """
    binding = require_rust_binding("group_axe_errors")
    return dict(
        binding(
            {
                "schema_version": _axe_error_wire_schema_version(),
                "entries": [dict(entry) for entry in entries],
            }
        )
    )


__all__ = [
    "group_errors",
    "normalize_error_signature",
    "signature_for_entry",
]
