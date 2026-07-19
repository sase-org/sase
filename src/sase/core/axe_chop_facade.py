"""Thin JSON facade over the Rust axe chop engine.

Python owns snapshots, YAML/file IO, subprocesses, launches, and persistence.
The functions here only marshal plain JSON-compatible values into the shared
Rust decision layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding

CHOP_ENGINE_SCHEMA_VERSION = 1
CHOP_RESULT_SCHEMA_VERSION = 1
CHOP_STATE_SCHEMA_VERSION = 1


def parse_chop_result(document: str) -> dict[str, Any]:
    """Parse and fail-closed validate one script result JSON document."""

    binding = require_rust_binding("parse_chop_result")
    return dict(binding(document))


def validate_chop_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed validate an already-decoded result document."""

    binding = require_rust_binding("validate_chop_result")
    return dict(binding(dict(result)))


def validate_chop_proposal(
    proposal: Mapping[str, Any],
    *,
    index: int = 0,
    prior_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Validate one proposal and its optional earlier-proposal reference."""

    binding = require_rust_binding("validate_chop_proposal")
    return dict(binding(dict(proposal), index, list(prior_ids)))


def derive_chop_agent_name(
    chop_name: str,
    *,
    target_key: str | None = None,
    proposal_index: int = 0,
    run_token: str | None = None,
) -> str:
    """Derive a default agent name stable within one chop run."""

    binding = require_rust_binding("derive_chop_agent_name")
    return str(binding(chop_name, target_key, proposal_index, run_token))


def evaluate_chop_decision(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate guards and the trigger against host-provided snapshots."""

    binding = require_rust_binding("evaluate_chop_decision")
    return dict(binding(dict(request)))


def apply_chop_checkpoint_update(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a lifecycle event to a checkpoint document."""

    binding = require_rust_binding("apply_chop_checkpoint_update")
    return dict(binding(dict(request)))


def check_and_record_chop_once_per(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Check and atomically transform a bounded once-per store."""

    binding = require_rust_binding("check_and_record_chop_once_per")
    return dict(binding(dict(request)))


def release_chop_once_per(request: Mapping[str, Any]) -> dict[str, Any]:
    """Release exact keys from a bounded once-per store."""

    binding = require_rust_binding("release_chop_once_per")
    return dict(binding(dict(request)))


def expand_chop_targets(request: Mapping[str, Any]) -> dict[str, Any]:
    """Expand literal or host-provided source targets into stable instances."""

    binding = require_rust_binding("expand_chop_targets")
    return dict(binding(dict(request)))


def parse_chop_duration(value: str) -> int:
    """Parse a strict positive compound chop duration into seconds."""

    binding = require_rust_binding("parse_chop_duration")
    return int(binding(value))


def validate_axe_config(
    config: Mapping[str, Any],
    *,
    provenance: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return fail-closed, provenance-aware diagnostics for an axe config."""

    binding = require_rust_binding("validate_axe_config")
    payload = binding(
        {
            "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
            "config": dict(config),
            "provenance": dict(provenance or {}),
        }
    )
    return [dict(item) for item in payload]
