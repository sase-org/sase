"""Shared section helpers needed by more than one sections submodule.

Public names only: no ``_``-prefixed symbol is imported across the new
sections modules, so helpers shared by several of them live here as public
names inside this already-private module.
"""

from __future__ import annotations

import hashlib

from sase.instructions.facts import InstructionFacts


class InstructionCompileError(ValueError):
    """Raised when a bundle cannot be compiled from its inputs."""


def git_blob_oid(data: bytes) -> str:
    """Return the git blob sha1 object id for *data* (40 lowercase hex)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def overlay_exclusion(
    facts: InstructionFacts, *, lifecycle: str, section_id: str
) -> str | None:
    """Return the exclusion reason for a lifecycle section, or null."""
    if lifecycle == "neutral":
        return None
    if facts.mode in ("interactive", "export"):
        return "mode"
    if lifecycle == "root" and not (
        facts.actor == "sase_root" and facts.mode == "runtime"
    ):
        return "overlay"
    if lifecycle == "helper" and not (
        facts.actor == "native_helper" and facts.mode == "runtime"
    ):
        return "overlay"
    if lifecycle not in ("root", "helper"):
        raise InstructionCompileError(
            f"section {section_id!r} has unknown lifecycle {lifecycle!r}"
        )
    return None


__all__ = [
    "InstructionCompileError",
    "git_blob_oid",
    "overlay_exclusion",
]
