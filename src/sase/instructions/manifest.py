"""Instruction manifest assembly over the Rust wire contract (decision 8).

Builds the normalized v1 manifest dict from a compiled bundle, host facts,
and delivery identity. Validation, invariants, and ``common_digest`` are
owned by ``sase-core``; this module only shapes the dict and routes it
through the adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.instruction_manifest import (
    InstructionManifestError,
    normalize_instruction_manifest,
)
from sase.instructions.compile import (
    COMPILER_NAME,
    COMPILER_VERSION,
    CompiledBundle,
)
from sase.instructions.facts import InstructionFacts, parse_facts

#: Delivery fields the caller must supply; the rest gain wire defaults.
_REQUIRED_DELIVERY_FIELDS = (
    "status",
    "invocation_id",
    "invocation_seq",
    "attempt",
    "agent_name",
    "agent_type",
    "model",
    "rendered_at",
)


def preview_delivery(
    *,
    agent_name: str = "preview",
    agent_type: str = "preview",
    model: str = "",
    invocation_id: str = "00000000-0000-4000-8000-000000000000",
    rendered_at: str = "1970-01-01T00:00:00Z",
) -> dict[str, Any]:
    """Return a ``preview`` delivery mapping for CLI renders (decision 8)."""
    return {
        "status": "preview",
        "channel": None,
        "invocation_id": invocation_id,
        "invocation_seq": 0,
        "attempt": 1,
        "agent_name": agent_name,
        "agent_type": agent_type,
        "model": model,
        "parent_invocation_id": None,
        "session_ids": [],
        "provider_cli_version": None,
        "rendered_at": rendered_at,
    }


def build_manifest(
    compiled: CompiledBundle,
    facts: InstructionFacts | Mapping[str, Any],
    delivery: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble and normalize the instruction manifest for *compiled*.

    Fills ``bundle.common_digest`` (via Rust normalize), ``delivery.render_ms``
    and ``delivery.cache`` from the compiled bundle, then returns the
    normalized dict. Raises :class:`InstructionManifestError` for missing
    delivery fields and the adapter error for wire violations.
    """
    from sase import __version__ as sase_version

    parsed = facts if isinstance(facts, InstructionFacts) else parse_facts(facts)
    missing = [name for name in _REQUIRED_DELIVERY_FIELDS if name not in delivery]
    if missing:
        raise InstructionManifestError(
            f"delivery is missing required field(s): {', '.join(missing)}"
        )
    delivery_wire: dict[str, Any] = {
        "status": delivery["status"],
        "channel": delivery.get("channel"),
        "invocation_id": delivery["invocation_id"],
        "invocation_seq": delivery["invocation_seq"],
        "attempt": delivery["attempt"],
        "agent_name": delivery["agent_name"],
        "agent_type": delivery["agent_type"],
        "model": delivery["model"],
        "parent_invocation_id": delivery.get("parent_invocation_id"),
        "session_ids": list(delivery.get("session_ids") or []),
        "provider_cli_version": delivery.get("provider_cli_version"),
        "rendered_at": delivery["rendered_at"],
        "render_ms": compiled.render_ms,
        "cache": compiled.cache,
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "compiler": {
            "name": COMPILER_NAME,
            "version": COMPILER_VERSION,
            "sase_version": str(sase_version),
        },
        "facts": parsed.to_dict(),
        "bundle": {
            "sha256": compiled.sha256,
            "common_digest": None,
            "bytes": compiled.total_bytes,
            "lines": compiled.total_lines,
            "tokens_est": compiled.tokens_est,
            "store_path": compiled.store_path,
        },
        "budget": {
            "by_layer": {
                layer: {
                    "bytes": totals["bytes"],
                    "tokens_est": totals["tokens_est"],
                }
                for layer, totals in sorted(compiled.layers.items())
            }
        },
        "sections": list(compiled.sections),
        "delivery": delivery_wire,
        "observation": {"status": "unobserved"},
    }
    return normalize_instruction_manifest(manifest)


__all__ = [
    "build_manifest",
    "preview_delivery",
]
