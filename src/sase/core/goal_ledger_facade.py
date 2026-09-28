"""Typed facade over the sase-core goal ledger bindings.

Every function here is a thin wrapper around one ``sase_core_rs`` binding,
called with string-literal names so ``tools/check_sase_core_rs_bindings``
keeps counting them as required. The ledger layout, marker-superset
ordering, and reduction rules all live in sase-core
(``crates/sase_core/src/goal/``); this module only translates call shapes.

Symbols consumed only by later phases of epic ``sase-1bu`` (list, show,
history, doctor, projection status, mint) are whitelisted with
``--epic-symbol 'sase-1bu(<name>)'`` in the Justfile until those phases
land; ``acceptance`` removes every entry this epic adds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

GOAL_LEDGER_WIRE_SCHEMA_VERSION = 1

GOAL_LEDGER_STORE_SCHEMA_VERSION = 1


def _require_goal_binding(name: str) -> Any:
    """Return binding *name* after proving the core wire is current."""
    version_binding = require_rust_binding("goal_ledger_wire_schema_version")
    if int(version_binding()) != GOAL_LEDGER_WIRE_SCHEMA_VERSION:
        raise AttributeError("sase_core_rs goal ledger wire is stale")
    return require_rust_binding(name)


def goal_ledger_init(root: str | Path) -> dict[str, Any]:
    """Create ``STORE.json`` under *root* when missing; return the outcome."""
    binding = _require_goal_binding("goal_ledger_init")
    return dict(binding(str(root)))


def goal_ledger_append(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Plan, write, and mark one goal action; return the append outcome."""
    binding = _require_goal_binding("goal_ledger_append")
    return dict(binding(str(root), dict(request)))


def goal_ledger_list(
    root: str | Path, goal_filter: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Hot-read unsettled goals under *root*; return the list wire."""
    binding = _require_goal_binding("goal_ledger_list")
    if goal_filter is None:
        return dict(binding(str(root)))
    return dict(binding(str(root), dict(goal_filter)))


def goal_ledger_show(root: str | Path, goal_id: str) -> dict[str, Any]:
    """Reduce and return one goal's state wire."""
    binding = _require_goal_binding("goal_ledger_show")
    return dict(binding(str(root), goal_id))


def goal_ledger_history(
    root: str | Path, goal_filter: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Scan settled-goal history under *root*; return the history wire."""
    binding = _require_goal_binding("goal_ledger_history")
    if goal_filter is None:
        return dict(binding(str(root)))
    return dict(binding(str(root), dict(goal_filter)))


def goal_ledger_doctor(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Check (and optionally repair) the ledger; return the doctor report."""
    binding = _require_goal_binding("goal_ledger_doctor")
    return dict(binding(str(root), dict(request)))


def goal_projection_status(
    root: str | Path, projection_path: str | Path
) -> dict[str, Any]:
    """Classify the hot projection against its ledger without reducing."""
    binding = _require_goal_binding("goal_projection_status")
    return dict(binding(str(root), str(projection_path)))


def goal_projection_refresh(
    root: str | Path,
    projection_path: str | Path,
    project: str,
    mode: str,
) -> dict[str, Any]:
    """Refresh the hot projection header and rows; return the refresh wire."""
    binding = _require_goal_binding("goal_projection_refresh")
    return dict(binding(str(root), str(projection_path), project, mode))


def goal_mint_id() -> str:
    """Mint one random 5-character Crockford base32 goal id."""
    binding = _require_goal_binding("goal_mint_id")
    return str(binding())


def goal_ledger_store_schema_version() -> int:
    """Return the ledger STORE layout schema version the core speaks."""
    binding = _require_goal_binding("goal_ledger_store_schema_version")
    return int(binding())


def goal_ledger_probe_list(root: str | Path) -> dict[str, Any]:
    """Count file opens per path class during a hot read; tests only."""
    binding = _require_goal_binding("goal_ledger_probe_list")
    return dict(binding(str(root)))


def goal_card_view(root: str | Path, goal_id: str, now: str) -> dict[str, Any]:
    """Reduce one goal and return its presentation-neutral card view wire."""
    binding = _require_goal_binding("goal_card_view")
    return dict(binding(str(root), goal_id, now))


def goal_card_markdown(card: dict[str, Any]) -> str:
    """Render a card view wire as markdown for ``sase artifact read``."""
    binding = _require_goal_binding("goal_card_markdown")
    return str(binding(dict(card)))


def goal_citation_line(card: dict[str, Any]) -> str:
    """Render a card view wire as the one-line ``@goal`` prompt citation."""
    binding = _require_goal_binding("goal_citation_line")
    return str(binding(dict(card)))
