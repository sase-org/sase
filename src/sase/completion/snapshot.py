"""Drift check between the checked-in structural snapshot and the live spec."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sase.completion.build import build_spec

_REGENERATE_HINT = "Run `just sync-completion-spec` to regenerate it."


def _stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


# symvision: tools/sync_completion_spec
def current_structural_view() -> dict[str, Any]:
    """Return the structural view built fresh from the live argparse tree."""
    return build_spec().structural_view()


# symvision: tools/sync_completion_spec
def completion_spec_drift(document: Mapping[str, Any] | None) -> str | None:
    """Return a human-readable drift message, or ``None`` when *document* matches.

    *document* is the parsed contents of the checked-in structural snapshot,
    or ``None`` when the snapshot file is missing entirely.
    """
    expected = current_structural_view()
    if document == expected:
        return None
    if document is None:
        return f"completion spec snapshot is missing\n{_REGENERATE_HINT}"
    return (
        "sase CLI completion spec is out of sync with the argparse tree\n"
        f"expected:\n{_stable_json(expected)}\n"
        f"actual:\n{_stable_json(document)}\n"
        f"{_REGENERATE_HINT}"
    )


__all__ = ["completion_spec_drift", "current_structural_view"]
