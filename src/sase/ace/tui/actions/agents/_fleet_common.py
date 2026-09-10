"""Shared helpers for unified Agents fleet projection."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.config import get_machine_name

from ...models.fleet_agents import FleetRowsProjection

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)

_PUBLIC_FLEET_MODULE = "sase.ace.tui.actions.agents._fleet"

_AGENTS_SUBTABS: tuple[str, str] = ("focus", "fleet")
_FLEET_CATALOG_PAGE_LIMIT = 100
_FLEET_CATALOG_MAX_PAGES = 16
_LOCAL_ACTIVE_STATUSES = frozenset(
    {
        "approved",
        "approval",
        "asking",
        "pending",
        "question",
        "queued",
        "running",
        "starting",
        "waiting",
        "waiting_input",
    }
)
_LOCAL_ATTENTION_STATUSES = frozenset(
    {
        "approval",
        "asking",
        "question",
        "waiting_input",
    }
)


def fleet_public_override(name: str, default: Any) -> Any:
    """Return a symbol from the public fleet facade when tests monkeypatch it."""
    module = sys.modules.get(_PUBLIC_FLEET_MODULE)
    if module is None:
        return default
    return getattr(module, name, default)


def local_machine_label() -> str:
    get_name = fleet_public_override("get_machine_name", get_machine_name)
    try:
        return get_name() or "here"
    except Exception:
        log.debug("local machine name lookup failed", exc_info=True)
        return "here"


def _agent_status_key(agent: Agent) -> str:
    value = getattr(agent, "status_bucket", None) or getattr(agent, "status", "")
    return str(value).casefold().replace("-", "_").replace(" ", "_")


def agent_counts_as_active(agent: Agent) -> bool:
    return _agent_status_key(agent) in _LOCAL_ACTIVE_STATUSES


def unified_attention_count(rows: list[Agent]) -> int:
    count = 0
    seen_remote: set[str] = set()
    for agent in rows:
        if getattr(agent, "fleet_origin_alias", None):
            attention = getattr(agent, "fleet_attention", None)
            if not isinstance(attention, Mapping):
                continue
            if str(attention.get("state") or "").casefold() != "pending":
                continue
            key = (
                getattr(agent, "fleet_logical_key", None)
                or getattr(agent, "fleet_exact_key", None)
                or repr(agent.identity)
            )
            if key in seen_remote:
                continue
            seen_remote.add(key)
            count += 1
            continue
        if _agent_status_key(agent) in _LOCAL_ATTENTION_STATUSES:
            count += 1
    return count


def unified_diagnostic_text(projection: FleetRowsProjection) -> str:
    diagnostics = projection.diagnostics
    if not diagnostics:
        return ""
    aliases = tuple(
        dict.fromkeys(
            str(alias)
            for diagnostic in diagnostics
            if isinstance(diagnostic, Mapping)
            and isinstance(alias := diagnostic.get("alias"), str)
            and alias
        )
    )
    if aliases and len(aliases) <= 2:
        return f"{', '.join(aliases)} unknown"
    issue_count = len(diagnostics)
    suffix = "issue" if issue_count == 1 else "issues"
    return f"{issue_count} machine {suffix}"


__all__ = [
    "_AGENTS_SUBTABS",
    "_FLEET_CATALOG_MAX_PAGES",
    "_FLEET_CATALOG_PAGE_LIMIT",
    "agent_counts_as_active",
    "fleet_public_override",
    "local_machine_label",
    "unified_attention_count",
    "unified_diagnostic_text",
]
