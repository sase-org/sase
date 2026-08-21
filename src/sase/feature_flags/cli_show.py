"""``sase flag show`` — value, config layers, bead, and call sites for one flag."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from rich.console import Console
from rich.text import Text

import sase
from sase.bead_flag_presentation import flag_due_presentation, flag_key_chip
from sase.core import time as core_time
from sase.feature_flags.beads import FlagBeadSnapshot
from sase.feature_flags.cli_json import diagnostic_json, flag_view_json
from sase.feature_flags.cli_render import (
    on_off,
    render_diagnostics,
    resolve_console,
    source_text,
)
from sase.feature_flags.cli_views import FlagView, flag_views
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDefinition,
    FeatureFlagDiagnostic,
    FeatureFlagSnapshot,
)
from sase.feature_flags.references import FlagCallSite, find_flag_call_sites
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import FeatureFlagLayerInput
from sase.feature_flags.snapshot import current_flag_layers, current_flags


_SHOW_JSON_SCHEMA_VERSION = 1
_MISSING: object = object()


def handle_flag_show(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    snapshot: FeatureFlagSnapshot | None = None,
    beads: tuple[FlagBeadSnapshot, ...] | None = None,
    layers: Sequence[FeatureFlagLayerInput] | None = None,
    call_sites: Sequence[FlagCallSite] | None = None,
    today: date | None = None,
    release: str | None = None,
) -> int:
    """Run ``sase flag show <key>``."""
    key = str(getattr(args, "flag_key", "") or "")
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    if key not in resolved_definitions:
        print(f"Error: unknown feature flag: {key}", file=sys.stderr)
        return 1
    resolved_snapshot = current_flags() if snapshot is None else snapshot
    views = flag_views(
        definitions=resolved_definitions,
        snapshot=resolved_snapshot,
        beads=beads,
        today=today,
        release=release,
    )
    view = next(item for item in views if str(item.definition.key) == key)
    sites = tuple(call_sites) if call_sites is not None else find_flag_call_sites(key)
    layer_rows = _layer_rows(
        key,
        view.definition,
        layers if layers is not None else current_flag_layers(),
        saved_value=view.saved,
        saved_detail=resolved_snapshot.state_path,
        env_value=_env_value_from_decision(view.decision),
        env_detail=view.decision.source_detail,
        cli_value=_cli_value_from_decision(view.decision),
        cli_detail=view.decision.source_detail,
    )
    if bool(getattr(args, "json", False)):
        print(
            json.dumps(
                _show_json(
                    view,
                    layers=layer_rows,
                    call_sites=sites,
                    diagnostics=resolved_snapshot.diagnostics,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _render_show(
        view,
        layers=layer_rows,
        call_sites=sites,
        diagnostics=resolved_snapshot.diagnostics,
        console=resolve_console(console),
        today=today or core_time.local_now().date(),
        release=release or sase.__version__,
    )
    return 0


def _render_show(
    view: FlagView,
    *,
    layers: Sequence[dict[str, Any]],
    call_sites: Sequence[FlagCallSite],
    diagnostics: Sequence[FeatureFlagDiagnostic] = (),
    console: Console,
    today: date,
    release: str,
) -> None:
    key = str(view.definition.key)
    console.print(flag_key_chip(key))
    console.print(f"kind:        {view.definition.kind}")
    console.print(f"description: {view.definition.description}")
    console.print()
    console.print("[bold]VALUE[/bold]")
    console.print(f"  default:    {on_off(view.definition.default)}")
    console.print(f"  effective:  {on_off(view.decision.enabled)}")
    console.print(f"  saved:      {_format_layer_value(view.saved)}")
    console.print(Text("  source:     ") + source_text(view.decision))
    console.print(f"  overridden: {'yes' if view.decision.overridden else 'no'}")
    console.print()
    console.print("[bold]LAYERS[/bold]")
    if not layers:
        console.print("  (no config layers reported a value)")
    for layer in layers:
        note = f"  {layer['note']}" if layer["note"] else ""
        console.print(
            f"  {layer['name']:<18} {_format_layer_value(layer['value'])}{note}"
        )
    console.print()
    console.print("[bold]BEAD[/bold]")
    if view.bead is None:
        console.print("  (no flag bead)")
    else:
        console.print(f"  id:         {view.bead.id}")
        console.print(f"  status:     {view.bead.status}")
        if view.bead.title:
            console.print(f"  title:      {view.bead.title}")
        if view.bead.remove_by_date and view.bead.remove_by_release:
            console.print(
                f"  remove_by:  {view.bead.remove_by_date} / "
                f"{view.bead.remove_by_release}"
            )
            due = flag_due_presentation(
                view.bead.remove_by_date,
                view.bead.remove_by_release,
                today=today,
                release=release,
            )
            console.print(f"  due:        {due.label} ({due.state})")
    console.print()
    console.print("[bold]CALL SITES[/bold]")
    if not call_sites:
        console.print("  (none found in the installed SASE package)")
    else:
        for site in call_sites:
            console.print(f"  {site.path}:{site.line}  {site.text}")
    render_diagnostics(diagnostics, console)


def _layer_rows(
    key: str,
    definition: FeatureFlagDefinition,
    layers: Sequence[FeatureFlagLayerInput],
    *,
    saved_value: bool | None = None,
    saved_detail: str = "",
    env_value: bool | None = None,
    env_detail: str = "",
    cli_value: bool | None = None,
    cli_detail: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "name": "default",
            "value": definition.default,
            "note": "(registry)",
        }
    ]
    for layer in layers:
        if layer.name == "default":
            continue
        raw = layer.values.get(key, _MISSING)
        if raw is _MISSING:
            note = "(unset)"
            value: Any = None
        else:
            value = raw
            note = _layer_note(layer, raw)
        rows.append({"name": layer.name, "value": value, "note": note})
    if saved_value is not None:
        rows.append(
            {
                "name": "state",
                "value": saved_value,
                "note": saved_detail or "(saved)",
            }
        )
    if env_value is not None:
        rows.append(
            {
                "name": "env",
                "value": env_value,
                "note": env_detail or SASE_FEATURE_FLAGS_ENV,
            }
        )
    if cli_value is not None:
        rows.append(
            {
                "name": "cli",
                "value": cli_value,
                "note": cli_detail
                or ("--enable-feature" if cli_value else "--disable-feature"),
            }
        )
    return rows


def _layer_note(
    layer: FeatureFlagLayerInput,
    raw: object,
) -> str:
    if layer.name.startswith("plugin:"):
        return "(plugin layers cannot flip a first-party default)"
    if type(raw) is not bool:
        return "(ignored: not boolean)"
    if layer.name == "local":
        return "(ignored: local config cannot set a flag)"
    if layer.detail:
        return f"({layer.detail})"
    return "(applied)"


def _env_value_from_decision(decision: FeatureFlagDecision) -> bool | None:
    if decision.source == "env":
        return decision.enabled
    return None


def _cli_value_from_decision(decision: FeatureFlagDecision) -> bool | None:
    if decision.source == "cli":
        return decision.enabled
    return None


def _format_layer_value(value: object) -> str:
    if value is None:
        return "—"
    if type(value) is bool:
        return on_off(value)
    return repr(value)


def _show_json(
    view: FlagView,
    *,
    layers: Sequence[dict[str, Any]],
    call_sites: Sequence[FlagCallSite],
    diagnostics: Sequence[FeatureFlagDiagnostic] = (),
) -> dict[str, Any]:
    payload = flag_view_json(view)
    payload["schema_version"] = _SHOW_JSON_SCHEMA_VERSION
    payload["layers"] = list(layers)
    payload["call_sites"] = [
        {"path": site.path, "line": site.line, "text": site.text} for site in call_sites
    ]
    payload["diagnostics"] = [diagnostic_json(item) for item in diagnostics]
    return payload


__all__ = [
    "handle_flag_show",
]
