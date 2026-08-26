"""Suffix and id allocation for gate shell family members."""

from __future__ import annotations

from sase.plan_chain import PLAN_CHAIN_GATE_SUFFIX
from sase.shells.naming import (
    SequenceSuffixSpec,
    ShellIdSpec,
    allocate_shell_suffix,
    new_shell_id,
    short_shell_id,
)

GATE_SEQUENCE_SUFFIX_TEMPLATE = f"{PLAN_CHAIN_GATE_SUFFIX}-@"

_GATE_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_GATE_ID_LENGTH = 12
SHORT_GATE_ID_LENGTH = 6

_GATE_ID_SPEC = ShellIdSpec(
    alphabet=_GATE_ID_ALPHABET,
    length=_GATE_ID_LENGTH,
    short_length=SHORT_GATE_ID_LENGTH,
)
_GATE_SUFFIX_SPEC = SequenceSuffixSpec(
    first_suffix=PLAN_CHAIN_GATE_SUFFIX,
    sequence_template=GATE_SEQUENCE_SUFFIX_TEMPLATE,
)


def new_gate_shell_id() -> str:
    """Mint a 12-character lowercase unambiguous base32 gate-shell id."""
    return new_shell_id(_GATE_ID_SPEC)


def short_gate_shell_id(gate_id: str) -> str:
    """Return the standard six-character gate-shell id display prefix."""
    return short_shell_id(gate_id, _GATE_ID_SPEC)


def allocate_gate_suffix(lane: str, *, has_existing_gate: bool) -> str:
    """Return the next free gate suffix for ``lane``."""
    return allocate_shell_suffix(
        lane,
        has_existing_shell=has_existing_gate,
        spec=_GATE_SUFFIX_SPEC,
    )


__all__ = [
    "GATE_SEQUENCE_SUFFIX_TEMPLATE",
    "SHORT_GATE_ID_LENGTH",
    "allocate_gate_suffix",
    "new_gate_shell_id",
    "short_gate_shell_id",
]
