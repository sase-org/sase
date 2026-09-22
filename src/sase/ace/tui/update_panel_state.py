"""Pure projection of cached update evidence into Update panel rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.stale_running_code import RunningCodeRoot, RunningCodeState
from sase.updates import UpdateSourceStatus, UpdateStatus

from .widgets.update_accents import (
    AGENT_CLI_ACCENT,
    UPDATE_CAUTION_ACCENT,
    UPDATE_GLYPH,
    UPDATES_ACCENT,
)

UpdateOptionChipKind = Literal["available", "current", "unknown", "failed", "stale"]
UpdateOptionScope = Literal["everything", "sase", "providers", "restart"]

_EVERYTHING_ACCENT = "$primary"
_STALE_AFTER_SECONDS = 30 * 60
_PROVIDER_DETAIL_LIMIT = 6
_PROVIDER_NAME_LIMIT = 18

_ROW_COPY: dict[UpdateOptionScope, tuple[str, str, str]] = {
    "restart": (
        "x",
        "Restart ACE",
        "Running code changed on disk; restart after tracked procs finish.",
    ),
    "everything": (
        "e",
        "Everything",
        "SASE, core, plugins, and providers in one tracked update.",
    ),
    "sase": (
        "s",
        "SASE, core & plugins",
        "Upgrade the sase host package, sase-core, and every installed plugin.",
    ),
    "providers": (
        "p",
        "Providers",
        "Update every installed LLM / agent CLI provider.",
    ),
}


@dataclass(frozen=True, slots=True)
class UpdateOptionChip:
    """Status chip for one Update panel option row."""

    kind: UpdateOptionChipKind
    text: str
    count: int
    core_rebuild: bool = False


@dataclass(frozen=True, slots=True)
class UpdateOptionRow:
    """One selectable Update panel option."""

    scope: UpdateOptionScope
    key: str
    title: str
    description: str
    chip: UpdateOptionChip
    accent: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdatePanelState:
    """Immutable presentation state for the Update panel."""

    rows: tuple[UpdateOptionRow, ...]
    freshness_label: str
    stale: bool
    rechecking: bool


def build_update_panel_state(
    status: UpdateStatus | None,
    *,
    now: float,
    rechecking: bool = False,
    running_code: RunningCodeState | None = None,
) -> UpdatePanelState:
    """Project the cached update-status snapshot into three option rows."""
    sase_row = _sase_row(status)
    providers_row = _providers_row(status)
    everything_row = _everything_row(status, sase_row, providers_row)
    rows: tuple[UpdateOptionRow, ...] = (everything_row, sase_row, providers_row)
    if running_code is not None and running_code.is_stale:
        rows = (_restart_row(running_code), *rows)
    freshness_label, stale = _freshness(status, now)
    return UpdatePanelState(
        rows=rows,
        freshness_label=freshness_label,
        stale=stale or (running_code is not None and running_code.is_stale),
        rechecking=rechecking,
    )


def _restart_row(running_code: RunningCodeState) -> UpdateOptionRow:
    stale_roots = running_code.stale_roots
    return _row(
        "restart",
        "stale",
        len(stale_roots),
        _one(_stale_running_code_detail(stale_roots)),
        UPDATE_CAUTION_ACCENT,
        glyph="↻",
    )


def _sase_row(status: UpdateStatus | None) -> UpdateOptionRow:
    count = 0 if status is None else status.component_count
    kind, error = _sase_kind(status)
    details: tuple[str, ...]
    if kind == "failed":
        details = _one(error)
    elif kind == "available" and status is not None:
        details = _one(_sase_detail(status))
    else:
        details = ()
    core_rebuild = kind == "available" and bool(
        status is not None and status.has_core_update
    )
    return _row("sase", kind, count, details, UPDATES_ACCENT, core_rebuild=core_rebuild)


def _providers_row(status: UpdateStatus | None) -> UpdateOptionRow:
    count = 0 if status is None else status.agent_cli_count
    kind, error = _single_source_kind(
        None if status is None else status.agent_cli_source,
        count=count,
        missing=status is None,
    )
    details: tuple[str, ...]
    if kind == "failed":
        details = _one(error)
    elif kind == "available" and status is not None:
        details = _provider_details(status)
    else:
        details = ()
    return _row("providers", kind, count, details, AGENT_CLI_ACCENT)


def _everything_row(
    status: UpdateStatus | None,
    sase_row: UpdateOptionRow,
    providers_row: UpdateOptionRow,
) -> UpdateOptionRow:
    count = sase_row.chip.count + providers_row.chip.count
    kinds = (sase_row.chip.kind, providers_row.chip.kind)
    if "failed" in kinds:
        kind: UpdateOptionChipKind = "failed"
    elif all(item == "unknown" for item in kinds):
        kind = "unknown"
    elif count > 0:
        kind = "available"
    else:
        kind = "current"
    details: tuple[str, ...] = ()
    if kind == "failed":
        errors = tuple(
            detail
            for row in (sase_row, providers_row)
            if row.chip.kind == "failed"
            for detail in row.details
            if detail
        )
        details = _one(" · ".join(dict.fromkeys(errors)))
    elif kind == "available":
        details = _one(_everything_summary(status, sase_row, providers_row))
    core_rebuild = kind == "available" and sase_row.chip.core_rebuild
    return _row(
        "everything",
        kind,
        count,
        details,
        _EVERYTHING_ACCENT,
        core_rebuild=core_rebuild,
    )


def _everything_summary(
    status: UpdateStatus | None,
    sase_row: UpdateOptionRow,
    providers_row: UpdateOptionRow,
) -> str:
    """Compact combined line: the SASE breakdown plus a provider count clause."""
    parts: list[str] = []
    if sase_row.chip.kind == "available":
        parts.extend(sase_row.details)
    if providers_row.chip.kind == "available" and status is not None:
        clause = f"providers {status.agent_cli_count}"
        manual = status.manual_agent_cli_count
        if manual:
            clause = f"{clause} ({manual} manual)"
        parts.append(clause)
    return " · ".join(parts)


def _one(text: str | None) -> tuple[str, ...]:
    return (text,) if text else ()


def _sase_kind(
    status: UpdateStatus | None,
) -> tuple[UpdateOptionChipKind, str | None]:
    if status is None:
        return "unknown", None
    errors = tuple(
        error
        for error in (status.core_source.error, status.plugin_source.error)
        if error
    )
    if errors:
        return "failed", " · ".join(dict.fromkeys(errors))
    if not status.core_source.known or not status.plugin_source.known:
        return "unknown", None
    if status.component_count > 0:
        return "available", None
    return "current", None


def _single_source_kind(
    source: UpdateSourceStatus | None,
    *,
    count: int,
    missing: bool,
) -> tuple[UpdateOptionChipKind, str | None]:
    if missing or source is None:
        return "unknown", None
    if source.error:
        return "failed", source.error
    if not source.known:
        return "unknown", None
    if count > 0:
        return "available", None
    return "current", None


def _sase_detail(status: UpdateStatus) -> str | None:
    host = sum(1 for component in status.components if component.role == "host")
    core = sum(1 for component in status.components if component.role == "core")
    plugins = sum(1 for component in status.components if component.role == "plugin")
    parts: list[str] = []
    if host:
        parts.append(f"sase {host}")
    if core:
        parts.append(f"sase-core {core}")
    if plugins:
        parts.append(f"plugins {plugins}")
    if status.has_core_update:
        parts.append("core rebuild")
    return " · ".join(parts) or None


def _provider_details(status: UpdateStatus) -> tuple[str, ...]:
    """One aligned ``name  installed → latest`` line per captured provider."""
    candidates = status.provider_candidates
    shown = candidates[:_PROVIDER_DETAIL_LIMIT]
    names = [_truncate_name(candidate.display_name) for candidate in shown]
    width = max((len(name) for name in names), default=0)
    lines: list[str] = []
    for name, candidate in zip(names, shown, strict=True):
        transition = (
            f"{_version(candidate.installed_version)} → "
            f"{_version(candidate.latest_version)}"
        )
        line = f"• {name.ljust(width)}  {transition}"
        if candidate.manual_only:
            line = f"{line} · manual steps"
        lines.append(line)
    remaining = len(candidates) - len(shown)
    if remaining > 0:
        noun = "provider" if remaining == 1 else "providers"
        lines.append(f"• +{remaining} more {noun}")
    return tuple(lines)


def _truncate_name(name: str) -> str:
    if len(name) <= _PROVIDER_NAME_LIMIT:
        return name
    return f"{name[: _PROVIDER_NAME_LIMIT - 1]}…"


def _version(value: str | None) -> str:
    return value or "unknown"


def _row(
    scope: UpdateOptionScope,
    kind: UpdateOptionChipKind,
    count: int,
    details: tuple[str, ...],
    accent: str,
    *,
    glyph: str = UPDATE_GLYPH,
    core_rebuild: bool = False,
) -> UpdateOptionRow:
    key, title, description = _ROW_COPY[scope]
    return UpdateOptionRow(
        scope=scope,
        key=key,
        title=title,
        description=description,
        chip=_chip(kind, count, glyph=glyph, core_rebuild=core_rebuild),
        accent=accent,
        details=details,
    )


def _chip(
    kind: UpdateOptionChipKind,
    count: int,
    *,
    glyph: str,
    core_rebuild: bool = False,
) -> UpdateOptionChip:
    if kind == "available":
        text = f"{glyph} {count} available"
    elif kind == "current":
        text = "✓ up to date"
    elif kind == "unknown":
        text = "· not checked yet"
    elif kind == "stale":
        text = "↻ code changed"
    else:
        text = "! check failed"
    return UpdateOptionChip(
        kind=kind, text=text, count=count, core_rebuild=core_rebuild
    )


def _stale_running_code_detail(
    stale_roots: tuple[RunningCodeRoot, ...],
) -> str | None:
    if not stale_roots:
        return None
    details = [_stale_root_detail(root) for root in stale_roots[:2]]
    remaining = len(stale_roots) - len(details)
    if remaining > 0:
        details.append(f"+{remaining} more checkout{'s' if remaining != 1 else ''}")
    return " · ".join(details)


def _stale_root_detail(root: RunningCodeRoot) -> str:
    incoming = root.incoming
    if incoming is None:
        return f"{root.label}: {_short(root.imported_sha)}..{_short(root.current_sha)}"
    if incoming.source == "unavailable":
        reason = incoming.error or "commit preview unavailable"
        return f"{root.label}: {_short(root.imported_sha)}..{_short(root.current_sha)} ({reason})"
    noun = "commit" if incoming.total == 1 else "commits"
    if not incoming.commits:
        return f"{root.label}: {incoming.total} {noun}"
    commits = "; ".join(
        f"{commit.short_sha} {commit.subject}" for commit in incoming.commits[:3]
    )
    if incoming.extra:
        commits = f"{commits}; +{incoming.extra} more"
    return f"{root.label}: {incoming.total} {noun} ({commits})"


def _short(sha: str) -> str:
    return sha[:9]


def _freshness(
    status: UpdateStatus | None,
    now: float,
) -> tuple[str, bool]:
    if status is None:
        return "never checked — press r", True
    age = max(0.0, now - status.checked_at)
    return _format_age(age), age > _STALE_AFTER_SECONDS


def _format_age(age: float) -> str:
    seconds = int(age)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


__all__ = [
    "UpdateOptionChip",
    "UpdateOptionRow",
    "UpdatePanelState",
    "build_update_panel_state",
]
