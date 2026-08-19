"""Validated accessors for ACE-specific configuration."""

from __future__ import annotations

from typing import Any

from sase.config.core import load_merged_config

_DEFAULT_ACE_PAGE_SIZE = 100


def get_ace_page_size() -> int:
    """Return the Ctrl+J / Ctrl+K page size, defaulting to 100.

    Invalid, missing, or unloadable values fall back to the bundled default
    rather than raising: a hand-edited ``sase.yml`` must not crash ACE.
    """
    try:
        ace = load_merged_config().get("ace", {})
    except Exception:  # noqa: BLE001 - page size is fail-open.
        return _DEFAULT_ACE_PAGE_SIZE
    if not isinstance(ace, dict):
        return _DEFAULT_ACE_PAGE_SIZE
    value: Any = ace.get("page_size", _DEFAULT_ACE_PAGE_SIZE)
    if type(value) is int and value >= 1:
        return value
    return _DEFAULT_ACE_PAGE_SIZE


__all__ = ["get_ace_page_size"]
