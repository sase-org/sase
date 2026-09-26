"""Named proc addressing: qualification, validation, and completion."""

from __future__ import annotations

import os
from collections.abc import Sequence

from .ids import PROC_ID_ALPHABET, PROC_ID_LENGTH, short_proc_id
from .models import Proc

_NAMED_PROC_CONCURRENCY_PREFIX = "named-proc:"
# legacy sase-shell spelling: pre-rename concurrency keys carry ``shell:``.
_LEGACY_SHELL_CONCURRENCY_PREFIX = "shell:"


class NamedProcNameError(ValueError):
    """A named proc is empty, malformed, or ambiguous with a proc id."""


def calling_sase_agent() -> str | None:
    """Return the calling sase agent, or ``None`` outside an agent run."""
    raw = (
        os.environ.get("SASE_AGENT_NAME") or os.environ.get("SASE_AGENT") or ""
    ).strip()
    if not raw:
        return None
    return _sase_agent_projection(raw)


def named_proc_concurrency_key(project: str | None, proc_name: str) -> str:
    """Return the namespaced concurrency key derived from a named proc.

    This is distinct from :attr:`Proc.concurrency_keys`. The store uses the
    namespaced form for conflict detection and does not write it back into
    that field.
    """
    return f"{_NAMED_PROC_CONCURRENCY_PREFIX}{project or ''}:{proc_name}"


def _normalize_concurrency_key_for_compare(key: str) -> str:
    """Normalize a concurrency key so legacy and new prefixes compare equal."""
    # legacy sase-shell spelling: ``shell:<project>:<name>`` equals
    # ``named-proc:<project>:<name>`` for the same project and name.
    if key.startswith(_LEGACY_SHELL_CONCURRENCY_PREFIX):
        return (
            _NAMED_PROC_CONCURRENCY_PREFIX
            + key[len(_LEGACY_SHELL_CONCURRENCY_PREFIX) :]
        )
    return key


def normalize_concurrency_keys_for_compare(keys: Sequence[str]) -> set[str]:
    """Return *keys* with legacy prefixes normalized for equality checks."""

    return {_normalize_concurrency_key_for_compare(str(key)) for key in keys}


def qualify_named_proc_name(
    name: str,
    *,
    agent: str | None = None,
) -> str:
    """Return a fully qualified named proc, or raise ``NamedProcNameError``.

    A name that already contains ``--`` is treated as fully qualified. A bare
    name is attached beneath the calling sase agent. Slash, proc-id-shaped
    names, invalid agent components, and malformed qualification fail.
    """
    raw = name.strip()
    if not raw:
        raise NamedProcNameError("named proc must not be empty")
    _reject_slash(raw)
    if _is_full_proc_id(raw):
        raise NamedProcNameError(f"named proc {name!r} is ambiguous with a proc id")
    if "--" in raw:
        return _validate_qualified(raw)

    caller = (agent if agent is not None else calling_sase_agent()) or ""
    caller = caller.strip()
    if not caller:
        raise NamedProcNameError(
            f"bare named proc {name!r} requires a calling sase agent; "
            "pass a fully qualified name such as <agent>--<name>"
        )
    caller = _sase_agent_projection(caller)
    if _is_full_proc_id(raw):
        raise NamedProcNameError(f"named proc {name!r} is ambiguous with a proc id")
    return _validate_qualified(f"{caller}--{raw}")


def proc_name_keys(name: str, *, agent: str | None = None) -> tuple[str, ...]:
    """Return stored-name keys that should match *name* in filters and refs.

    The raw spelling is always included so historical names stay visible even
    when they would not pass new-write qualification.
    """
    raw = name.strip()
    if not raw:
        return ()
    keys = [raw]
    try:
        qualified = qualify_named_proc_name(raw, agent=agent)
    except NamedProcNameError:
        qualified = None
    if qualified is not None and qualified not in keys:
        keys.append(qualified)
    return tuple(keys)


def matching_procs_by_proc_name(
    name: str,
    procs: Sequence[Proc],
    *,
    agent: str | None = None,
) -> list[Proc]:
    """Return procs whose stored named proc equals *name* or its FQ form."""
    keys = set(proc_name_keys(name, agent=agent))
    if not keys:
        return []
    return [proc for proc in procs if proc.proc_name in keys]


def complete_proc_refs(prefix: str, procs: Sequence[Proc]) -> list[str]:
    """Return named procs and proc ids that start with *prefix*."""
    needle = prefix.strip()
    results: list[str] = []
    seen: set[str] = set()
    for proc in procs:
        candidates = []
        if proc.proc_name:
            candidates.append(proc.proc_name)
        candidates.append(proc.proc_id)
        candidates.append(short_proc_id(proc.proc_id))
        for candidate in candidates:
            if candidate.startswith(needle) and candidate not in seen:
                seen.add(candidate)
                results.append(candidate)
    return results


def _validate_qualified(name: str) -> str:
    if name.count("--") != 1:
        raise NamedProcNameError(f"named proc {name!r} has malformed qualification")
    base, role = name.rsplit("--", 1)
    if not base or not role or "." in role:
        raise NamedProcNameError(f"named proc {name!r} has malformed qualification")
    if _is_full_proc_id(role):
        raise NamedProcNameError(f"named proc {name!r} is ambiguous with a proc id")
    try:
        from sase.core.agent_identity_facade import validate_new_agent_name

        validate_new_agent_name(name)
    except NamedProcNameError:
        raise
    except Exception as exc:
        raise NamedProcNameError(
            f"named proc {name!r} has invalid agent components: {exc}"
        ) from exc
    return name


def _sase_agent_projection(name: str) -> str:
    try:
        from sase.sase_agent import sase_agent_name

        return sase_agent_name(name)
    except Exception:
        return name


def _reject_slash(name: str) -> None:
    if "/" in name or "\\" in name:
        raise NamedProcNameError(f"named proc {name!r} must not contain a slash")


def _is_full_proc_id(value: str) -> bool:
    lowered = value.strip().lower()
    return len(lowered) == PROC_ID_LENGTH and all(
        char in PROC_ID_ALPHABET for char in lowered
    )


__all__ = [
    "NamedProcNameError",
    "calling_sase_agent",
    "complete_proc_refs",
    "matching_procs_by_proc_name",
    "named_proc_concurrency_key",
    "normalize_concurrency_keys_for_compare",
    "proc_name_keys",
    "qualify_named_proc_name",
]
