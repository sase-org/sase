"""Suffix and id allocation for monitor family members."""

from __future__ import annotations

from sase.plan_chain import PLAN_CHAIN_MONITOR_SUFFIX
from sase.shells.naming import (
    SequenceSuffixSpec,
    ShellIdSpec,
    allocate_shell_suffix,
    new_shell_id,
    short_shell_id,
)

#: Suffix template later monitor members in a lane allocate from, producing
#: ``--mon-0``, ``--mon-1``, ... .
MONITOR_SEQUENCE_SUFFIX_TEMPLATE = f"{PLAN_CHAIN_MONITOR_SUFFIX}-@"

#: Same alphabet/length as :data:`sase.procs.ids.PROC_ID_ALPHABET` /
#: ``PROC_ID_LENGTH`` so monitor ids read consistently with proc ids.
_MONITOR_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_MONITOR_ID_LENGTH = 12

#: Mirrors :data:`sase.procs.ids.SHORT_PROC_ID_LENGTH` for display.
SHORT_MONITOR_ID_LENGTH = 6

_MONITOR_ID_SPEC = ShellIdSpec(
    alphabet=_MONITOR_ID_ALPHABET,
    length=_MONITOR_ID_LENGTH,
    short_length=SHORT_MONITOR_ID_LENGTH,
)
_MONITOR_SUFFIX_SPEC = SequenceSuffixSpec(
    first_suffix=PLAN_CHAIN_MONITOR_SUFFIX,
    sequence_template=MONITOR_SEQUENCE_SUFFIX_TEMPLATE,
)


def new_monitor_id() -> str:
    """Mint a 12-character lowercase unambiguous base32 monitor id."""
    return new_shell_id(_MONITOR_ID_SPEC)


def short_monitor_id(monitor_id: str) -> str:
    """Return the standard six-character monitor-id display prefix."""
    return short_shell_id(monitor_id, _MONITOR_ID_SPEC)


def allocate_monitor_suffix(lane: str, *, has_existing_monitor: bool) -> str:
    """Return the next free monitor suffix for *lane*.

    The lane's first monitor ever takes the plain ``--mon`` suffix. Every
    later monitor -- started after an earlier one in the same lane finished
    -- allocates a sequence suffix (``--mon-0``, ``--mon-1``, ...) since a
    lane is sequential and only ever has one *active* monitor at a time.
    """
    return allocate_shell_suffix(
        lane,
        has_existing_shell=has_existing_monitor,
        spec=_MONITOR_SUFFIX_SPEC,
    )


__all__ = [
    "MONITOR_SEQUENCE_SUFFIX_TEMPLATE",
    "SHORT_MONITOR_ID_LENGTH",
    "allocate_monitor_suffix",
    "new_monitor_id",
    "short_monitor_id",
]
