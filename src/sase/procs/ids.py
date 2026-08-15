"""Generation and unique-prefix resolution for proc ids."""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from .models import ACTIVE_PROC_STATUSES, Proc

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
    """Resolve a named proc shell, exact id, or unique id prefix.

    Fully qualified named proc shells win, then an exact proc id, then a
    unique id prefix of at least three characters. A bare name is derived
    beneath the calling sase agent before the name lookup.
    """
    raw = prefix.strip()
    if not raw:
        raise ProcRefError(
            f"proc reference must be at least {MIN_PROC_REF_LENGTH} characters"
        )
    named = _resolve_named_proc_shell(raw, procs)
    if named is not None:
        return named
    ref = raw.lower()
    exact = [proc for proc in procs if proc.proc_id == ref]
    if len(exact) == 1:
        return exact[0]
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


def _resolve_named_proc_shell(raw: str, procs: Sequence[Proc]) -> Proc | None:
    from .names import matching_procs_by_shell_name

    matches = matching_procs_by_shell_name(raw, procs)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    active = [proc for proc in matches if proc.status in ACTIVE_PROC_STATUSES]
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        candidates = ", ".join(
            f"{short_proc_id(proc.proc_id)} ({proc.label})" for proc in active
        )
        raise ProcRefError(
            f"named proc shell {raw!r} is ambiguous; candidates: {candidates}"
        )
    return matches[0]


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
