"""Thin Python wrapper around the Rust agent-tab canonicalizer."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding


def canonicalize_agent_tab(raw: str) -> str | None:
    """Return the stored tab name for *raw*, or None for the default tab.

    Kind ``named`` returns the canonical (trimmed, lowercased) name. Kind
    ``default`` (explicit ``%tab:main``) is stored as absent, so it returns
    None. The Rust binding's ``ValueError`` (whose text is the user-facing
    message) propagates unchanged.
    """
    binding = require_rust_binding("canonicalize_agent_tab_name")
    result: Any = binding(raw)
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned non-dict tab canonicalization")
    kind = result.get("kind")
    if kind == "default":
        return None
    if kind == "named":
        name = result.get("name")
        if isinstance(name, str) and name:
            return name
        raise TypeError("sase_core_rs returned named tab without a name")
    raise TypeError(f"sase_core_rs returned unknown tab kind: {kind!r}")


__all__ = ["canonicalize_agent_tab"]
