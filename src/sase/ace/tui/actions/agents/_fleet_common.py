"""Shared helpers for unified Agents fleet projection."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any

from ...models.agent import format_compact_duration
from ...models.fleet_agents import FleetRowsProjection

_PUBLIC_FLEET_MODULE = "sase.ace.tui.actions.agents._fleet"

_AGENTS_SUBTABS: tuple[str, str] = ("focus", "fleet")
_FLEET_CATALOG_PAGE_LIMIT = 100
_FLEET_CATALOG_MAX_PAGES = 16


def fleet_public_override(name: str, default: Any) -> Any:
    """Return a symbol from the public fleet facade when tests monkeypatch it."""
    module = sys.modules.get(_PUBLIC_FLEET_MODULE)
    if module is None:
        return default
    return getattr(module, name, default)


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


def host_feed_issue_text(projection: FleetRowsProjection) -> str:
    """Compact host/machine-level feed-error summary for the status line.

    A host normalized to ``invalid_federation_host`` carries zero summaries,
    so it never appears as a row or a BY_MACHINE banner; this is the only
    place its feed error is guaranteed to surface.
    """
    issues = projection.host_feed_issues
    if not issues:
        return ""
    if len(issues) == 1:
        issue = issues[0]
        label = issue.status or "error"
        detail_parts = [
            item
            for item in (
                issue.error,
                issue.diagnostic if issue.diagnostic != issue.error else None,
            )
            if item
        ]
        detail = f": {' - '.join(detail_parts)}" if detail_parts else ""
        if issue.cache_age_seconds is not None:
            age = format_compact_duration(issue.cache_age_seconds)
            return f"{issue.alias}: feed {label}{detail} (cached {age} ago)"
        return f"{issue.alias}: feed {label}{detail}"
    count = len(issues)
    return f"{count} machines with feed errors"


__all__ = [
    "_AGENTS_SUBTABS",
    "_FLEET_CATALOG_MAX_PAGES",
    "_FLEET_CATALOG_PAGE_LIMIT",
    "fleet_public_override",
    "host_feed_issue_text",
    "unified_diagnostic_text",
]
