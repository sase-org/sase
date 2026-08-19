"""Deterministic single-key shortcut assignment for the tmux Agent catalog."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Navigation keys in both surfaces (OptionList/tmux menu). Never auto-assigned,
#: but a user's explicit config key or a provider's declared ``menu_key`` may
#: still claim one deliberately (matching how ``qwen`` keeps ``q``).
_RESERVED_AUTO_KEYS = frozenset({"j", "k"})
_DIGITS = "123456789"
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class MenuKeyCandidate:
    """One provider's inputs to menu-key assignment."""

    provider: str
    display_name: str
    configured_key: str = ""
    descriptor_key: str = ""


def assign_menu_keys(candidates: Sequence[MenuKeyCandidate]) -> dict[str, str]:
    """Return ``{provider: key}``, assigning a single shortcut to each entry.

    Processes *candidates* in provider-name (registry/alphabetical) order so
    assignment never depends on iteration accidents. A provider that cannot
    claim any key gets ``""`` and remains selectable by navigation alone.
    """
    claimed: set[str] = set()
    assigned: dict[str, str] = {}
    for candidate in sorted(candidates, key=lambda item: item.provider):
        key = _assign_one(candidate, claimed)
        assigned[candidate.provider] = key
        if key:
            claimed.add(key)
    return assigned


def _assign_one(candidate: MenuKeyCandidate, claimed: set[str]) -> str:
    if candidate.configured_key and candidate.configured_key not in claimed:
        return candidate.configured_key
    if candidate.descriptor_key and candidate.descriptor_key not in claimed:
        return candidate.descriptor_key
    for source in (candidate.provider, candidate.display_name):
        key = _first_free_letter(source, claimed)
        if key:
            return key
    key = _first_free(_DIGITS, claimed)
    if key:
        return key
    return _first_free(_ALPHABET, claimed, exclude=_RESERVED_AUTO_KEYS)


def _first_free_letter(text: str, claimed: set[str]) -> str:
    for char in text.lower():
        if char.isalpha() and char not in claimed and char not in _RESERVED_AUTO_KEYS:
            return char
    return ""


def _first_free(
    chars: str, claimed: set[str], *, exclude: frozenset[str] = frozenset()
) -> str:
    for char in chars:
        if char not in claimed and char not in exclude:
            return char
    return ""


__all__ = [
    "MenuKeyCandidate",
    "assign_menu_keys",
]
