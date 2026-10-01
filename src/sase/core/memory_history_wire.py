"""Wire records for the memory-history facade.

Sidecar to :mod:`sase.core.memory_history_facade`. Defines the **stable**
boundary between Python and the Rust ``memory_history`` implementation in
``sase-core`` that backs ``sase memory history``.

Scope of the contract
---------------------

Python owns scope assembly (repo roots, the instruction inventory, the
generated-note list, the snapshot root) and all presentation. Rust owns
lineage, classification, cause attribution, the per-scope snapshot, and
the queries. These records carry the scope inputs down and are otherwise
opaque: every query response is passed through to JSON output unchanged,
so responses stay plain ``dict`` values and are NEVER described by these
records.

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- Times are epoch seconds (``git log %ct`` / ``%at``).
- OIDs are full lowercase hex SHAs; an absent OID is ``None``, never the
  all-zero placeholder git prints for created/deleted sides.

Schema version
--------------

:data:`MEMORY_HISTORY_WIRE_SCHEMA_VERSION` mirrors the Rust
``MEMORY_HISTORY_WIRE_SCHEMA_VERSION`` constant. It is bumped only when a
serialized meaning changes. A test asserts it equals the value reported
by the ``memory_history_wire_schema_version`` binding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: Mirrors the Rust ``MEMORY_HISTORY_WIRE_SCHEMA_VERSION`` constant.
MEMORY_HISTORY_WIRE_SCHEMA_VERSION = 1

ScopeKind = Literal["project", "home"]

_SCOPE_KINDS: frozenset[str] = frozenset(("project", "home"))


@dataclass(frozen=True, slots=True)
class MemoryHistoryInstructionFile:
    """One instruction render directory in a scope."""

    dir: str
    agents_path: str
    shim_paths: tuple[str, ...] = ()
    template: bool = False
    managed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the Rust ``MemoryHistoryInstructionFileWire`` shape."""
        return {
            "dir": self.dir,
            "agents_path": self.agents_path,
            "shim_paths": list(self.shim_paths),
            "template": self.template,
            "managed": self.managed,
        }


@dataclass(frozen=True, slots=True)
class MemoryHistoryScope:
    """Caller identity for one memory-history scope."""

    scope_key: str
    scope_kind: ScopeKind
    repo_root: str = ""
    memory_roots: tuple[str, ...] = ()
    instruction_files: tuple[MemoryHistoryInstructionFile, ...] = ()
    generated_notes: tuple[str, ...] = ()
    renderer_prefixes: tuple[str, ...] = ()
    config_paths: tuple[str, ...] = ()
    cache_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the Rust ``MemoryHistoryScopeWire`` shape."""
        if self.scope_kind not in _SCOPE_KINDS:
            raise ValueError(f"invalid memory-history scope kind: {self.scope_kind!r}")
        if not self.scope_key:
            raise ValueError("memory-history scope_key must not be empty")
        return {
            "scope_key": self.scope_key,
            "scope_kind": self.scope_kind,
            "repo_root": self.repo_root,
            "memory_roots": list(self.memory_roots),
            "instruction_files": [entry.to_dict() for entry in self.instruction_files],
            "generated_notes": list(self.generated_notes),
            "renderer_prefixes": list(self.renderer_prefixes),
            "config_paths": list(self.config_paths),
            "cache_dir": self.cache_dir,
        }


__all__ = [
    "MEMORY_HISTORY_WIRE_SCHEMA_VERSION",
    "MemoryHistoryInstructionFile",
    "MemoryHistoryScope",
    "ScopeKind",
]
