"""The merged Updates-tab row model: capability derivation and version labels.

Pure and widget-free: :func:`build_update_rows` projects a completed
:class:`~.plugins_browser_loading.PluginsLoadResult` into one flat tuple of
:class:`UpdateRow`, one per SASE core package, plugin, and registered agent
CLI. Every existing detail renderer keeps working unchanged because ``payload``
carries the original domain object.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdatesReady,
)
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.render_common import _COMMUNITY_STYLE
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.versions import CorePackageVersion

if TYPE_CHECKING:
    from .plugins_browser_loading import PluginsLoadResult

UpdateRowKind = Literal["core", "plugin", "agent-cli"]
UpdateRowSection = Literal["sase", "plugins-builtin", "plugins-community", "agent-clis"]
UpdateScope = Literal["outdated", "installed", "all"]
UpdateCapability = Literal[
    "install", "uninstall", "update", "mark_update", "manual", "history"
]

SCOPE_ORDER: tuple[UpdateScope, ...] = ("outdated", "installed", "all")
SCOPE_LABELS: dict[UpdateScope, str] = {
    "outdated": "Outdated",
    "installed": "Installed",
    "all": "All",
}

_SECTIONS: tuple[tuple[UpdateRowSection, str, str], ...] = (
    ("sase", "── SASE ──", "bold dim"),
    ("plugins-builtin", "── Plugins · Built-in ──", "bold dim"),
    ("plugins-community", "── Plugins · Community ──", f"bold {_COMMUNITY_STYLE}"),
    ("agent-clis", "── Agent CLIs ──", "bold dim"),
)

PlanAgentCliUpdatesFn = Callable[..., AgentCliUpdatePlan]

_CORE_ACCENT = "#AF87FF"
_PLUGIN_ACCENT = "#AF87FF"
_DEFAULT_AGENT_CLI_ACCENT = "#87D7FF"


@dataclass(frozen=True, slots=True)
class UpdateRow:
    """One row in the merged Updates inventory, across every domain."""

    key: str  # "core:sase" | "plugin:github" | "cli:claude"
    kind: UpdateRowKind
    section: UpdateRowSection
    label: str  # display name only, never a composed row string
    accent: str
    installed: bool
    installed_version: str | None
    latest_version: str | None
    version_label: str  # the kind-specific installed/latest cell
    update_available: bool
    source: str  # managed | editable | git | npm | manual | …
    capabilities: frozenset[UpdateCapability]
    error: str | None
    haystack: str  # casefolded, built once per load
    payload: CorePackageVersion | PluginCatalogEntry | AgentCliStatus


def _row_in_scope(row: UpdateRow, scope: UpdateScope) -> bool:
    """Return whether *row* belongs in *scope*."""
    if scope == "outdated":
        return row.update_available or row.error is not None
    if scope == "installed":
        return row.installed
    return True


def scope_counts(rows: Sequence[UpdateRow]) -> dict[UpdateScope, int]:
    """Count rows in each scope in one pass, ignoring any filter."""
    counts: dict[UpdateScope, int] = dict.fromkeys(SCOPE_ORDER, 0)
    for row in rows:
        counts["all"] += 1
        if row.installed:
            counts["installed"] += 1
        if row.update_available or row.error is not None:
            counts["outdated"] += 1
    return counts


def select_rows(
    rows: Sequence[UpdateRow],
    *,
    scope: UpdateScope,
    needle: str,
) -> list[tuple[str, str, list[UpdateRow]]]:
    """Project *rows* into the pane's ``_grouped`` shape.

    Empty sections are omitted. *needle* is already ``.strip().casefold()``-ed
    by the caller and matched with ``needle in row.haystack``.
    """
    grouped: dict[UpdateRowSection, list[UpdateRow]] = {
        section: [] for section, _header, _style in _SECTIONS
    }
    for row in rows:
        if not _row_in_scope(row, scope):
            continue
        if needle and needle not in row.haystack:
            continue
        grouped[row.section].append(row)
    result: list[tuple[str, str, list[UpdateRow]]] = []
    for section, header, style in _SECTIONS:
        section_rows = grouped[section]
        if not section_rows:
            continue
        section_rows.sort(
            key=lambda item: (not item.update_available, item.label.casefold())
        )
        result.append((header, style, section_rows))
    return result


def _plugin_version_label(entry: PluginCatalogEntry) -> str:
    """The installed/latest cell text for one plugin row."""
    info = entry.installed
    if info.installed:
        if entry.latest.source == "editable":
            return _dev_version_label(entry)
        if entry.latest.source == "git":
            return "git"
        if entry.update_available and info.version and entry.latest.version:
            return f"v{info.version} → v{entry.latest.version}"
        if info.version:
            return f"v{info.version}"
        return "installed"
    if entry.latest.version:
        return f"latest v{entry.latest.version}"
    return ""


def _dev_version_label(entry: PluginCatalogEntry) -> str:
    latest = entry.latest
    current = latest.current_version or entry.installed.version
    current_label = f"v{current}" if current else "editable"
    if entry.update_available and latest.version:
        return f"{current_label} → v{latest.version}  dev"
    state = dev_state_label(latest.state)
    if state:
        return f"{current_label}  dev · {state}"
    return f"{current_label}  dev"


def dev_state_label(state: str | None) -> str:
    """The human label for a dev-update (editable install) state code."""
    labels = {
        "current": "",
        "update_available": "update available",
        "dirty": "local changes",
        "diverged": "diverged",
        "detached": "detached HEAD",
        "no_upstream": "no upstream",
        "offline": "offline",
        "fetch_failed": "fetch failed",
        "unavailable": "unavailable",
    }
    return labels.get(state or "", state or "")


def _agent_cli_version_label(status: AgentCliStatus) -> str:
    """The installed/latest cell text for one agent-CLI row."""
    installed = status.installed_version
    latest = status.latest_version
    if installed and latest and status.update_available:
        return f"v{installed} → v{latest}"
    if installed:
        return f"v{installed}"
    if status.installed:
        return "version unknown"
    return "not installed"


def _core_version_label(package: CorePackageVersion) -> str:
    """The installed/latest cell text for one SASE core-package row."""
    installed = package.installed_version
    latest = package.latest_version
    if installed is None:
        return "not installed"
    if package.update_available and latest:
        label = f"v{installed} → v{latest}"
    else:
        label = f"v{installed}"
    if package.install_type == "editable":
        label += "   dev"
    return label


def _plugin_label(entry: PluginCatalogEntry) -> str:
    if entry.is_builtin:
        return entry.name
    if entry.full_name:
        return entry.full_name
    if entry.owner and entry.repo:
        return f"{entry.owner}/{entry.repo}"
    if entry.owner and entry.name:
        return f"{entry.owner}/{entry.name}"
    return entry.name or entry.repo or entry.owner or "unknown plugin"


def _plugin_haystack(entry: PluginCatalogEntry) -> str:
    return "\n".join(
        part
        for part in (
            entry.name,
            entry.repo,
            entry.owner,
            entry.full_name,
            _plugin_label(entry),
            entry.description,
            *entry.topics,
        )
        if part
    ).casefold()


def _core_haystack(package: CorePackageVersion) -> str:
    return "\n".join(
        part for part in (package.name, package.distribution_name) if part
    ).casefold()


def _agent_cli_haystack(status: AgentCliStatus) -> str:
    return "\n".join(
        part
        for part in (
            status.name,
            status.display_name,
            status.binary,
            status.install_method.value,
        )
        if part
    ).casefold()


def _build_core_row(package: CorePackageVersion) -> UpdateRow:
    return UpdateRow(
        key=f"core:{package.name}",
        kind="core",
        section="sase",
        label=package.name,
        accent=_CORE_ACCENT,
        installed=package.installed_version is not None,
        installed_version=package.installed_version,
        latest_version=package.latest_version,
        version_label=_core_version_label(package),
        update_available=package.update_available,
        source=package.install_type or "managed",
        capabilities=frozenset(),
        error=package.latest_error,
        haystack=_core_haystack(package),
        payload=package,
    )


def build_plugin_row(entry: PluginCatalogEntry, *, blocked: bool) -> UpdateRow:
    """Build the :class:`UpdateRow` for one plugin catalog entry.

    Exposed publicly (not just used internally by :func:`build_update_rows`)
    because a lazy per-row latest-version completion patches exactly one
    plugin's row in place without rebuilding the whole tuple.
    """
    installed = entry.installed.installed
    update_available = entry.update_available
    capabilities: set[UpdateCapability] = set()
    if not blocked:
        if not installed:
            capabilities.add("install")
        else:
            capabilities.add("uninstall")
            if update_available:
                capabilities.add("update")
    section: UpdateRowSection = (
        "plugins-builtin" if entry.is_builtin else "plugins-community"
    )
    return UpdateRow(
        key=f"plugin:{entry.name}",
        kind="plugin",
        section=section,
        label=_plugin_label(entry),
        accent=_PLUGIN_ACCENT,
        installed=installed,
        installed_version=entry.installed.version,
        latest_version=entry.latest.version,
        version_label=_plugin_version_label(entry),
        update_available=update_available,
        source=entry.latest.source,
        capabilities=frozenset(capabilities),
        error=entry.latest.error,
        haystack=_plugin_haystack(entry),
        payload=entry,
    )


def _agent_cli_update_entry(
    status: AgentCliStatus,
    *,
    offline: bool,
    plan_fn: PlanAgentCliUpdatesFn,
) -> AgentCliUpdateEntry:
    plan = plan_fn(
        (status.name,),
        all_clis=False,
        refresh=False,
        offline=offline,
        status_fn=lambda **_kwargs: (status,),
    )
    if isinstance(plan, (AgentCliUpdatesReady, AgentCliNothingToUpdate)):
        return plan.entries[0]
    raise RuntimeError(f"Could not plan registered agent CLI {status.name}")


def _build_agent_cli_row(
    status: AgentCliStatus,
    update_entry: AgentCliUpdateEntry | None,
    *,
    accent: str,
) -> UpdateRow:
    capabilities: set[UpdateCapability] = {"history"}
    if update_entry is not None and update_entry.ready:
        capabilities.add("mark_update")
    if (
        status.update_available
        and update_entry is not None
        and update_entry.argv is None
        and bool(update_entry.manual_argv)
    ):
        capabilities.add("manual")
    return UpdateRow(
        key=f"cli:{status.name}",
        kind="agent-cli",
        section="agent-clis",
        label=status.display_name,
        accent=accent,
        installed=status.installed,
        installed_version=status.installed_version,
        latest_version=status.latest_version,
        version_label=_agent_cli_version_label(status),
        update_available=status.update_available,
        source=status.install_method.value,
        capabilities=frozenset(capabilities),
        error=status.latest_error or status.version_error,
        haystack=_agent_cli_haystack(status),
        payload=status,
    )


def build_update_rows(
    result: PluginsLoadResult,
    *,
    uv_tool: UvToolInstall | NotUvToolInstall | None,
    offline: bool,
    plan_fn: PlanAgentCliUpdatesFn | None = None,
) -> tuple[UpdateRow, ...]:
    """Project one completed load result into the flat merged row tuple.

    Pure: no widget access, no I/O beyond *plan_fn*. *plan_fn* defaults to a
    deferred ``plugins_browser_pane._plan_agent_cli_updates`` lookup so unit
    tests stay pure (pass a stub directly) while the existing monkeypatch seam
    still works when the pane calls this for real.
    """
    blocked = isinstance(uv_tool, NotUvToolInstall)
    resolved_plan_fn = plan_fn
    if resolved_plan_fn is None:
        from . import plugins_browser_pane as pane_module

        resolved_plan_fn = pane_module._plan_agent_cli_updates

    rows: list[UpdateRow] = []

    core_versions = getattr(result, "core_versions", None)
    if core_versions is not None:
        rows.extend(_build_core_row(package) for package in core_versions.packages)

    catalog = getattr(result, "catalog", None)
    if catalog is not None:
        rows.extend(
            build_plugin_row(entry, blocked=blocked) for entry in catalog.entries
        )

    agent_cli_colors = getattr(result, "agent_cli_colors", None) or {}
    for status in getattr(result, "agent_cli_statuses", ()) or ():
        try:
            update_entry = _agent_cli_update_entry(
                status, offline=offline, plan_fn=resolved_plan_fn
            )
        except RuntimeError:
            update_entry = None
        accent = agent_cli_colors.get(status.name, _DEFAULT_AGENT_CLI_ACCENT)
        rows.append(_build_agent_cli_row(status, update_entry, accent=accent))

    return tuple(rows)
