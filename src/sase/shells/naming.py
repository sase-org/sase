"""Reusable suffix and id allocation for family shell members."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass

from sase.plan_chain import allocate_agent_family_child_suffix

SuffixAllocator = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class ShellIdSpec:
    """Shape of a shell id and its short display prefix."""

    alphabet: str
    length: int
    short_length: int


@dataclass(frozen=True, slots=True)
class SequenceSuffixSpec:
    """First and subsequent suffixes for one sequential family shell kind."""

    first_suffix: str
    sequence_template: str


def new_shell_id(spec: ShellIdSpec) -> str:
    """Mint a shell id using *spec*'s alphabet and length."""
    return "".join(secrets.choice(spec.alphabet) for _ in range(spec.length))


def short_shell_id(shell_id: str, spec: ShellIdSpec) -> str:
    """Return *shell_id*'s standard display prefix."""
    return shell_id[: spec.short_length]


def allocate_shell_suffix(
    lane: str,
    *,
    has_existing_shell: bool,
    spec: SequenceSuffixSpec,
    allocator: SuffixAllocator | None = None,
) -> str:
    """Return the next free suffix for a sequential shell kind in *lane*."""
    if not has_existing_shell:
        return spec.first_suffix
    allocate = allocator or allocate_agent_family_child_suffix
    return allocate(lane, spec.sequence_template)


__all__ = [
    "SequenceSuffixSpec",
    "ShellIdSpec",
    "allocate_shell_suffix",
    "new_shell_id",
    "short_shell_id",
]
