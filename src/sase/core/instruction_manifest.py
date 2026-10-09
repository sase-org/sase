"""Thin adapter over the Rust instruction-manifest wire contract.

The Rust core owns the closed vocabulary, the validation invariants, and
the ``common_digest`` definition. This module mirrors the constants for
Python callers and routes normalization through ``sase_core_rs`` without
reimplementing any validation.
"""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

#: Mirrors Rust ``INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION``.
INSTRUCTION_MANIFEST_WIRE_SCHEMA_VERSION = 1

#: Closed layer vocabulary (decision 8).
INSTRUCTION_MANIFEST_LAYERS = (
    "frame",
    "package",
    "plugin",
    "home",
    "project",
    "launch",
)

#: Section status vocabulary.
INSTRUCTION_MANIFEST_SECTION_STATUSES = ("included", "excluded")

#: Exclusion reason vocabulary.
INSTRUCTION_MANIFEST_SECTION_REASONS = (
    "superseded_input",
    "shadowed",
    "overlay",
    "mode",
    "no_directive",
    "empty",
)

#: Lifecycle overlay vocabulary.
INSTRUCTION_MANIFEST_LIFECYCLES = ("neutral", "root", "helper")

#: Source scope vocabulary.
INSTRUCTION_MANIFEST_SOURCE_SCOPES = (
    "package",
    "plugin",
    "home",
    "project",
    "launch",
)

#: Source kind vocabulary.
INSTRUCTION_MANIFEST_SOURCE_KINDS = (
    "package_template",
    "helper_template",
    "provider_directive",
    "memory_note",
    "memory_web",
    "memory_strands",
    "config",
    "generated",
    "legacy_fallback",
)

#: Delivery status vocabulary (last four frozen for E3, unused in E2).
INSTRUCTION_MANIFEST_DELIVERY_STATUSES = (
    "preview",
    "shadow",
    "explicit",
    "inherits_native",
    "inherits_root",
    "none",
)

#: Cache outcome vocabulary.
INSTRUCTION_MANIFEST_CACHE_STATUSES = ("hit", "miss", "bypass")

#: Observation status vocabulary.
INSTRUCTION_MANIFEST_OBSERVATION_STATUSES = (
    "unobserved",
    "observed",
    "partial",
    "unavailable",
)

#: Fact names set by the host (decision 4).
INSTRUCTION_MANIFEST_FACT_NAMES = (
    "actor",
    "mode",
    "purpose",
    "provider",
    "project",
    "host",
    "vcs",
)

#: Fact value vocabularies (decision 4).
INSTRUCTION_MANIFEST_ACTORS = ("sase_root", "native_helper", "interactive")
INSTRUCTION_MANIFEST_MODES = ("runtime", "interactive", "export")
INSTRUCTION_MANIFEST_PURPOSES = (
    "ordinary",
    "declaration_recovery",
    "conflict_repair",
)


class _InstructionManifestError(ValueError):
    """Raised when an instruction manifest fails Rust normalization."""


def wire_schema_version() -> int:
    """Return the Rust instruction-manifest wire schema version."""
    binding = require_rust_binding("instruction_manifest_wire_schema_version")
    return int(binding())


def normalize_instruction_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an instruction manifest dict via Rust.

    Fills ``bundle.common_digest`` when null and rejects a wrong value
    or any invariant failure with :class:`_InstructionManifestError`.
    """
    binding = require_rust_binding("normalize_instruction_manifest")
    try:
        return dict(binding(manifest))
    except _InstructionManifestError:
        raise
    except ValueError as exc:
        raise _InstructionManifestError(str(exc)) from exc
