"""Schema-checked facade for Rust-owned project-onboarding policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION = 1
"""Must match ``sase_core::project_onboarding``."""


def classify_project_candidates(request: Mapping[str, Any]) -> dict[str, Any]:
    """Classify candidates into grouped and search-only rows."""
    return _call(
        "classify_project_candidates",
        request,
        "project candidate list",
    )


def evaluate_repo_creation_form(
    form: Mapping[str, Any],
    values: Mapping[str, str],
    mode: str,
) -> dict[str, Any]:
    """Evaluate a provider creation form in ``strict`` or ``lenient`` mode."""
    payload = {
        "schema_version": PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION,
        "form": dict(form),
        "values": {str(key): str(value) for key, value in dict(values).items()},
        "mode": mode,
    }
    return _call(
        "evaluate_repo_creation_form",
        payload,
        "repo creation form",
    )


def _call(name: str, request: Mapping[str, Any], label: str) -> dict[str, Any]:
    _require_wire_schema()
    payload = dict(request)
    payload.setdefault("schema_version", PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION)
    binding = require_rust_binding(name)
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError(f"sase_core_rs returned an invalid {label}")
    if raw.get("schema_version") != PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an incompatible {label}: "
            f"schema_version must be {PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION}"
        )
    return raw


def _require_wire_schema() -> None:
    binding = require_rust_binding("project_onboarding_wire_schema_version")
    version = int(binding())
    if version != PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs project-onboarding wire is stale: expected "
            f"{PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION}, got {version}"
        )


__all__ = [
    "PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION",
    "classify_project_candidates",
    "evaluate_repo_creation_form",
]
