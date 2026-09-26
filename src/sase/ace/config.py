"""Validated accessors for ACE-specific configuration."""

from __future__ import annotations

from typing import Any

from sase.config.core import load_merged_config

_DEFAULT_ACE_PAGE_SIZE = 100

_DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT = 20


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


def get_ace_prompt_stash_trash_limit() -> int:
    """Return the stash Trash row limit, defaulting to 20.

    This is an entry-count limit, not a byte quota; zero disables recovery.
    Invalid, missing, or unloadable values fall back to the bundled default
    rather than raising: a hand-edited ``sase.yml`` must not crash ACE.
    Booleans are rejected explicitly because ``bool`` subclasses ``int``.
    """
    try:
        ace = load_merged_config().get("ace", {})
    except Exception:  # noqa: BLE001 - trash limit is fail-open.
        return _DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT
    if not isinstance(ace, dict):
        return _DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT
    section: Any = ace.get("prompt_stash", {})
    if not isinstance(section, dict):
        return _DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT
    value: Any = section.get("trash_limit", _DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT)
    if type(value) is int and value >= 0:
        return value
    return _DEFAULT_ACE_PROMPT_STASH_TRASH_LIMIT


__all__ = ["get_ace_page_size", "get_ace_prompt_stash_trash_limit"]
