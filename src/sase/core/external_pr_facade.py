"""Facade for the external pull-request mirror classifier."""

from __future__ import annotations

from typing import Any

from sase.core.external_pr_wire import (
    CanonicalPullRequestUrl,
    ExternalPrImportPlanWire,
    ExternalPrImportRequestWire,
    canonical_pull_request_url_from_dict,
    external_pr_plan_from_dict,
    external_pr_request_to_json_dict,
)
from sase.core.rust import require_rust_binding


def canonical_pull_request_url(url: str) -> CanonicalPullRequestUrl | None:
    """Canonicalize a PR URL via ``sase_core_rs``."""
    binding = require_rust_binding("canonical_pull_request_url")
    payload: dict[str, Any] | None = binding(url)
    return canonical_pull_request_url_from_dict(payload)


def plan_external_pr_import(
    request: ExternalPrImportRequestWire,
) -> ExternalPrImportPlanWire:
    """Classify one remote PR against known local Patches via ``sase_core_rs``."""
    binding = require_rust_binding("plan_external_pr_import")
    payload: dict[str, Any] = binding(external_pr_request_to_json_dict(request))
    return external_pr_plan_from_dict(payload)


__all__ = [
    "canonical_pull_request_url",
    "plan_external_pr_import",
]
