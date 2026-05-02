"""Wire records for the Git query parser facade.

Companion to :mod:`sase.core.wire`, :mod:`sase.core.query_wire`,
:mod:`sase.core.agent_scan_wire`, and :mod:`sase.core.status_wire`. Defines
the **stable** boundary between Python and a future Rust implementation of
the deterministic Git query parsers (Phase 5 of
``sdd/research/202604/rust_backend_migration.md`` and
``sdd/tales/202604/rust_backend_phase5_git_query_ops.md``).

Scope of the contract
---------------------

The Git query wire models *pure parsing* of strings/bytes that the host
already collected by running ``git`` itself. Process execution, timeouts,
fetch retries, filesystem checks, rebase state, and every mutating sync
or reword operation stay in Python and are NEVER described by these
records.

Only one structured record is currently needed:

- :class:`GitNameStatusEntryWire` — a single parsed row from
  ``git diff --name-status -z``. Rust returns these as plain dicts; the
  facade rehydrates them into the dataclass so call sites see a stable
  Python type regardless of backend.

The remaining Phase 5 parsers (``parse_git_branch_name``,
``derive_git_workspace_name``, ``parse_git_conflicted_files``,
``parse_git_local_changes``) only need primitive wire shapes
(``str | None``, ``list[str]``) and therefore do not require dedicated
records.

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- ``None`` is preserved (becomes JSON ``null``).
- The status field carries the raw status token from ``git diff``
  (e.g. ``"A"``, ``"M"``, ``"R100"``, ``"C75"``); rename/copy entries
  carry both paths joined by a literal tab character so callers can
  recover the legacy ``list[tuple[str, str]]`` shape with no extra
  parsing.

Schema version
--------------

:data:`GIT_QUERY_WIRE_SCHEMA_VERSION` is bumped whenever the shape
changes incompatibly. The Rust implementation pins the same version
constant in its serde structs; mismatches surface immediately in
:func:`git_name_status_entry_from_dict`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

GIT_QUERY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GitNameStatusEntryWire:
    """One parsed row from ``git diff --name-status -z``.

    Attributes:
        status: Status token from ``git diff`` (``A``, ``M``, ``D``,
            ``T``, ``U``, ``R<score>``, ``C<score>``, ...). Carried
            verbatim so the facade can preserve the legacy semantics
            of ``list[tuple[str, str]]``.
        path: Path field. For renames and copies (``R``/``C``) this is
            ``"<old>\\t<new>"`` (a literal tab) so callers can split the
            pair without an extra wire field.
    """

    status: str
    path: str


def git_query_wire_to_json_dict(record: Any) -> Any:
    """Project a Git-query wire record (or list of them) to a JSON-safe shape.

    Mirrors :func:`sase.core.agent_scan_wire.agent_scan_wire_to_json_dict`
    so the Git-query wire stays independent of other facades' schema bumps.
    """
    if isinstance(record, (list, tuple)):
        return [git_query_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: git_query_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def git_name_status_entry_from_dict(data: dict[str, Any]) -> GitNameStatusEntryWire:
    """Rehydrate a :class:`GitNameStatusEntryWire` from a JSON-safe dict.

    Inverse of :func:`git_query_wire_to_json_dict` for entry records. Used
    by the future PyO3 binding adapter and by tests that round-trip an
    entry through JSON.
    """
    return GitNameStatusEntryWire(
        status=str(data["status"]),
        path=str(data["path"]),
    )


__all__ = [
    "GIT_QUERY_WIRE_SCHEMA_VERSION",
    "GitNameStatusEntryWire",
    "git_name_status_entry_from_dict",
    "git_query_wire_to_json_dict",
]
