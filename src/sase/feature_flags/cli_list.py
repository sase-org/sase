"""``sase flag list`` — one row per registered feature flag."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from rich.console import Console
from rich.text import Text

import sase
from sase.bead.model import FlagRecord
from sase.bead_flag_presentation import flag_due_chip, flag_key_chip
from sase.bead_status_presentation import bead_status_presentation
from sase.core import time as core_time
from sase.feature_flags.beads import FlagBeadSnapshot, flag_record_from_snapshot
from sase.feature_flags.cli_json import diagnostic_json, flag_view_json
from sase.feature_flags.cli_render import (
    on_off,
    render_diagnostics,
    resolve_console,
    source_text,
)
from sase.feature_flags.cli_views import FlagView, flag_views
from sase.feature_flags.models import (
    FeatureFlagDefinition,
    FeatureFlagDiagnostic,
    FeatureFlagSnapshot,
)
from sase.feature_flags.snapshot import current_flags


_LIST_JSON_SCHEMA_VERSION = 1


def handle_flag_list(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    snapshot: FeatureFlagSnapshot | None = None,
    beads: tuple[FlagBeadSnapshot, ...] | None = None,
    today: date | None = None,
    release: str | None = None,
) -> int:
    """Run ``sase flag list``."""
    resolved_snapshot = current_flags() if snapshot is None else snapshot
    views = flag_views(
        definitions=definitions,
        snapshot=resolved_snapshot,
        beads=beads,
        today=today,
        release=release,
    )
    if bool(getattr(args, "json", False)):
        print(
            json.dumps(
                _list_json(views, diagnostics=resolved_snapshot.diagnostics),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _render_list(
        views,
        diagnostics=resolved_snapshot.diagnostics,
        console=resolve_console(console),
        today=today or core_time.local_now().date(),
        release=release or sase.__version__,
    )
    return 0


def _render_list(
    views: Sequence[FlagView],
    *,
    diagnostics: Sequence[FeatureFlagDiagnostic] = (),
    console: Console,
    today: date,
    release: str,
) -> None:
    if not views:
        console.print("No feature flags are registered.")
        console.print(
            "Create one with `sase flag new <key>` in a SASE-managed checkout "
            "(is_sase_managed: true)."
        )
        render_diagnostics(diagnostics, console)
        return
    for view in views:
        console.print(_list_row(view, today=today, release=release))
    render_diagnostics(diagnostics, console)


def _list_row(
    view: FlagView,
    *,
    today: date,
    release: str,
) -> Text:
    key = str(view.definition.key)
    line = Text()
    line.append_text(flag_key_chip(key))
    line.append("  ")
    line.append(view.definition.kind, style="italic")
    line.append("  ")
    line.append(f"default={on_off(view.definition.default)}")
    line.append("  ")
    line.append(
        on_off(view.decision.enabled),
        style="bold green" if view.decision.enabled else "bold",
    )
    line.append("  ")
    line.append_text(source_text(view.decision))
    line.append("  ")
    line.append_text(_bead_text(view.bead))
    record = None if view.bead is None else flag_record_from_snapshot(view.bead)
    if record is not None:
        line.append("  ")
        line.append_text(_flag_due_text(record, today, release))
    return line


def _flag_due_text(record: FlagRecord, today: date, release: str) -> Text:
    return flag_due_chip(record, today=today, release=release)


def _bead_text(bead: FlagBeadSnapshot | None) -> Text:
    if bead is None:
        return Text("—", style="dim")
    text = Text(bead.id)
    text.append(" ")
    status = bead_status_presentation(bead.status)
    text.append(f"{status.glyph} {bead.status}", style=status.rich_style)
    return text


def _list_json(
    views: Sequence[FlagView],
    *,
    diagnostics: Sequence[FeatureFlagDiagnostic] = (),
) -> dict[str, Any]:
    return {
        "schema_version": _LIST_JSON_SCHEMA_VERSION,
        "diagnostics": [diagnostic_json(item) for item in diagnostics],
        "flags": [flag_view_json(view) for view in views],
    }


__all__ = [
    "handle_flag_list",
]
