"""Pure projection of cached update evidence into Update panel rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.updates import UpdateSourceStatus, UpdateStatus

from .widgets.update_accents import (
    AGENT_CLI_ACCENT,
    CORE_UPDATE_ACCENT,
    UPDATE_GLYPH,
    UPDATES_ACCENT,
)

UpdateOptionChipKind = Literal["available", "current", "unknown", "failed"]
UpdateOptionScope = Literal["everything", "sase", "providers"]

_EVERYTHING_ACCENT = "$primary"
_STALE_AFTER_SECONDS = 30 * 60
_DETAIL_NAME_LIMIT = 4

_ROW_COPY: dict[UpdateOptionScope, tuple[str, str, str]] = {
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


@dataclass(frozen=True, slots=True)
class UpdateOptionRow:
    """One selectable Update panel option."""

    scope: UpdateOptionScope
    key: str
    title: str
    description: str
    chip: UpdateOptionChip
    detail: str | None
    accent: str


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
) -> UpdatePanelState:
    """Project the cached update-status snapshot into three option rows."""
    sase_row = _sase_row(status)
    providers_row = _providers_row(status)
    everything_row = _everything_row(sase_row, providers_row)
    freshness_label, stale = _freshness(status, now)
    return UpdatePanelState(
        rows=(everything_row, sase_row, providers_row),
        freshness_label=freshness_label,
        stale=stale,
        rechecking=rechecking,
    )


def _sase_row(status: UpdateStatus | None) -> UpdateOptionRow:
    count = 0 if status is None else status.component_count
    kind, error = _sase_kind(status)
    detail: str | None
    if kind == "failed":
        detail = error
    elif kind == "available" and status is not None:
        detail = _sase_detail(status)
    else:
        detail = None
    accent = UPDATES_ACCENT
    if status is not None and status.has_core_update:
        accent = CORE_UPDATE_ACCENT
    return _row("sase", kind, count, detail, accent)


def _providers_row(status: UpdateStatus | None) -> UpdateOptionRow:
    count = 0 if status is None else status.agent_cli_count
    kind, error = _single_source_kind(
        None if status is None else status.agent_cli_source,
        count=count,
        missing=status is None,
    )
    if kind == "failed":
        detail = error
    elif kind == "available" and status is not None:
        detail = _providers_detail(status)
    else:
        detail = None
    return _row("providers", kind, count, detail, AGENT_CLI_ACCENT)


def _everything_row(
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
    detail = None
    if kind == "failed":
        errors = tuple(
            row.detail
            for row in (sase_row, providers_row)
            if row.chip.kind == "failed" and row.detail
        )
        detail = " · ".join(dict.fromkeys(errors)) or None
    return _row("everything", kind, count, detail, _EVERYTHING_ACCENT)


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


def _providers_detail(status: UpdateStatus) -> str | None:
    names = [candidate.display_name for candidate in status.provider_candidates]
    if not names:
        return None
    shown = names[:_DETAIL_NAME_LIMIT]
    remaining = len(names) - _DETAIL_NAME_LIMIT
    if remaining > 0:
        shown.append(f"+{remaining} more")
    detail = ", ".join(shown)
    manual = status.manual_agent_cli_count
    if manual:
        verb = "needs" if manual == 1 else "need"
        detail = f"{detail} · {manual} {verb} manual steps"
    return detail


def _row(
    scope: UpdateOptionScope,
    kind: UpdateOptionChipKind,
    count: int,
    detail: str | None,
    accent: str,
    *,
    glyph: str = UPDATE_GLYPH,
) -> UpdateOptionRow:
    key, title, description = _ROW_COPY[scope]
    return UpdateOptionRow(
        scope=scope,
        key=key,
        title=title,
        description=description,
        chip=_chip(kind, count, glyph=glyph),
        detail=detail,
        accent=accent,
    )


def _chip(
    kind: UpdateOptionChipKind,
    count: int,
    *,
    glyph: str,
) -> UpdateOptionChip:
    if kind == "available":
        text = f"{glyph} {count} available"
    elif kind == "current":
        text = "✓ up to date"
    elif kind == "unknown":
        text = "· not checked yet"
    else:
        text = "! check failed"
    return UpdateOptionChip(kind=kind, text=text, count=count)


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
