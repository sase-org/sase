"""Shared helpers for the ``sase gate answer`` split modules.

This module is private (``_``-prefixed) so the split can share helpers
without importing ``_``-prefixed names across files: everything defined
here carries a public name, and every consumer lives in one of the
``cli_answer_*`` sibling modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.notification_gates.cli_support import ResolvedGateCliBundle


def answered_payload(
    bundle: ResolvedGateCliBundle,
    response: Mapping[str, Any],
    already_completed: bool,
) -> dict[str, Any]:
    """Build the stable terminal payload for one answered gate."""
    return {
        "already_answered": already_completed,
        "feedback": response.get("feedback"),
        "kind": bundle.kind,
        "option_inputs": response.get("option_inputs", {}),
        "option_results": response.get("option_results", []),
        "request_id": bundle.request_id,
        "response_path": str(bundle.response_path),
        "selected_option_ids": list(response.get("selected_option_ids", [])),
        "status": "answered",
    }


__all__ = ["answered_payload"]
