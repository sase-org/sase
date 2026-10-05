"""Thin ToolRun adoption-report adapter over ``sase_core_rs``.

Rust owns pairing, shell-launch classification, and aggregation of normalized
LLM-call shell records. This module is a wire-only facade.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding


def tool_adoption_report(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the versioned adoption report for one request envelope."""

    return dict(require_rust_binding("tool_adoption_report")(dict(request)))
