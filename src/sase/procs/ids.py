"""Generation and unique-prefix resolution for proc ids."""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from .models import Proc

PROC_ID_LENGTH = 12
SHORT_PROC_ID_LENGTH = 6
MIN_PROC_REF_LENGTH = 3
PROC_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


class ProcRefError(ValueError):
    """A proc reference was too short, unknown, or ambiguous."""


def new_proc_id() -> str:
    """Mint a 12-character lowercase unambiguous base32 proc id."""
    return "".join(secrets.choice(PROC_ID_ALPHABET) for _ in range(PROC_ID_LENGTH))


def short_proc_id(proc_id: str) -> str:
    """Return the standard six-character proc-id display prefix."""
    return proc_id[:SHORT_PROC_ID_LENGTH]


def resolve_proc_ref(prefix: str, procs: Sequence[Proc]) -> Proc:
    """Resolve a unique proc-id prefix of at least three characters."""
    ref = prefix.strip().lower()
    if len(ref) < MIN_PROC_REF_LENGTH:
        raise ProcRefError(
            f"proc reference must be at least {MIN_PROC_REF_LENGTH} characters"
        )
    matches = [proc for proc in procs if proc.proc_id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ProcRefError(f"no proc matches reference {prefix!r}")
    candidates = ", ".join(
        f"{short_proc_id(proc.proc_id)} ({proc.label})" for proc in matches
    )
    raise ProcRefError(
        f"proc reference {prefix!r} is ambiguous; candidates: {candidates}"
    )


__all__ = [
    "MIN_PROC_REF_LENGTH",
    "PROC_ID_ALPHABET",
    "PROC_ID_LENGTH",
    "SHORT_PROC_ID_LENGTH",
    "ProcRefError",
    "new_proc_id",
    "resolve_proc_ref",
    "short_proc_id",
]
