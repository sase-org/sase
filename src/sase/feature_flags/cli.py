"""Handlers and rendering for ``sase flag``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

import sase
from sase.bead.flag_due import FlagRemovalState
from sase.bead.model import FlagRecord
from sase.bead_flag_presentation import (
    flag_due_chip,
    flag_due_presentation,
    flag_key_chip,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.core import time as core_time
from sase.feature_flags.beads import (
    FlagBeadSnapshot,
    create_flag_bead,
    flag_bead_for_id,
    flag_bead_for_key,
    flag_record_from_snapshot,
    load_flag_bead_snapshots,
)
from sase.feature_flags.defaults import default_flag_record
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.managed import project_is_sase_managed
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDefinition,
    FeatureFlagError,
    FeatureFlagSnapshot,
    FlagKind,
    FlagScope,
)
from sase.feature_flags.references import FlagCallSite, find_flag_call_sites
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import FeatureFlagLayerInput
from sase.feature_flags.snapshot import current_flag_layers, current_flags


_LIST_JSON_SCHEMA_VERSION = 1
_SHOW_JSON_SCHEMA_VERSION = 1
_SNAKE_CASE_KEY_MESSAGE = "feature flag key must be snake_case"
_KIND_CHOICES: tuple[FlagKind, ...] = ("beta", "ops", "sunset", "wip")
_SCOPE_CHOICES: tuple[FlagScope, ...] = ("global", "project")
_UNMANAGED_NEW_ERROR = (
    "`sase flag new` can only run in a SASE-managed checkout "
    "(set is_sase_managed: true in sase/sase.yml). The registry lives in "
    "the SASE source tree, so a scaffold from another project has nowhere "
    "to paste."
)


@dataclass(frozen=True)
class _FlagView:
    """One flag as the CLI renders it."""

    definition: FeatureFlagDefinition
    decision: FeatureFlagDecision
    bead: FlagBeadSnapshot | None
    due_state: FlagRemovalState | None


def handle_flag_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase flag ...`` command."""
    sub = getattr(args, "flag_subcommand", None) or "list"
    if sub == "list":
        sys.exit(_handle_flag_list_command(args))
    if sub == "new":
        sys.exit(_handle_flag_new_command(args))
    if sub == "show":
        sys.exit(_handle_flag_show_command(args))
    print("Usage: sase flag {list,new,show}", file=sys.stderr)
    sys.exit(2)


def _handle_flag_list_command(
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
    views = _flag_views(
        definitions=definitions,
        snapshot=snapshot,
        beads=beads,
        today=today,
        release=release,
    )
    if bool(getattr(args, "json", False)):
        print(json.dumps(_list_json(views), indent=2, sort_keys=True))
        return 0
    _render_list(
        views,
        console=_console(console),
        today=today or core_time.local_now().date(),
        release=release or sase.__version__,
    )
    return 0


def _handle_flag_show_command(
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
    views = _flag_views(
        definitions=resolved_definitions,
        snapshot=snapshot,
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
        env_value=_env_value_from_decision(view.decision),
    )
    if bool(getattr(args, "json", False)):
        print(
            json.dumps(
                _show_json(view, layers=layer_rows, call_sites=sites),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    _render_show(
        view,
        layers=layer_rows,
        call_sites=sites,
        console=_console(console),
        today=today or core_time.local_now().date(),
        release=release or sase.__version__,
    )
    return 0


def _handle_flag_new_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    today: date | None = None,
    version: str | None = None,
    cwd: Path | None = None,
    create_bead: bool = True,
) -> int:
    """Run ``sase flag new <key>``."""
    if not project_is_sase_managed(cwd):
        print(f"Error: {_UNMANAGED_NEW_ERROR}", file=sys.stderr)
        return 1

    key = str(getattr(args, "flag_key", "") or "")
    try:
        scaffold = _build_flag_scaffold(
            key,
            description=getattr(args, "description", None),
            kind=getattr(args, "kind", None),
            remove_by=getattr(args, "remove_by", None),
            scope=getattr(args, "scope", None),
            size=getattr(args, "size", None),
            definitions=definitions,
            today=today,
            version=version,
            cwd=cwd,
            create_bead=create_bead,
        )
    except FeatureFlagError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _console(console).print(scaffold)
    return 0


def _build_flag_scaffold(
    key: str,
    *,
    description: str | None = None,
    kind: FlagKind | str | None = None,
    remove_by: str | None = None,
    scope: FlagScope | str | None = None,
    size: str | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    today: date | None = None,
    version: str | None = None,
    cwd: Path | None = None,
    create_bead: bool = True,
) -> str:
    """Create the flag bead (when needed) and return the paste-ready scaffold."""
    from sase.feature_flags.models import is_feature_flag_key

    if not is_feature_flag_key(key):
        raise FeatureFlagError(f"{_SNAKE_CASE_KEY_MESSAGE}: {key!r}")
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    if key in resolved_definitions:
        raise FeatureFlagError(f"feature flag {key!r} is already registered")

    resolved_kind: FlagKind = _coerce_kind(kind)
    resolved_scope: FlagScope = _coerce_scope(scope)
    resolved_description = (description or "").strip() or (
        f"Remove the {key} feature flag once both thresholds pass."
    )
    if resolved_kind == "ops" and not (description or "").strip():
        raise FeatureFlagError(
            "ops feature flags need a rationale; pass it with -d/--description"
        )

    bead_id: str | None = None
    record: FlagRecord | None = None
    if resolved_kind != "ops":
        record = default_flag_record(
            key,
            today=today or core_time.local_now().date(),
            version=version or sase.__version__,
            remove_by=remove_by,
        )
        if create_bead:
            issue = create_flag_bead(
                record,
                title=f"Retire {key}",
                description=resolved_description,
                size=size,
                cwd=cwd,
            )
            bead_id = issue.id
        else:
            bead_id = "<flag-bead-id>"

    return _scaffold_text(
        key,
        kind=resolved_kind,
        description=resolved_description,
        scope=resolved_scope,
        bead_id=bead_id,
        record=record,
        default=_default_for_kind(resolved_kind),
    )


def _flag_views(
    *,
    definitions: Mapping[str, FeatureFlagDefinition] | None,
    snapshot: FeatureFlagSnapshot | None,
    beads: tuple[FlagBeadSnapshot, ...] | None,
    today: date | None,
    release: str | None,
) -> tuple[_FlagView, ...]:
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    resolved_snapshot = current_flags() if snapshot is None else snapshot
    resolved_beads = load_flag_bead_snapshots() if beads is None else beads
    resolved_today = core_time.local_now().date() if today is None else today
    resolved_release = sase.__version__ if release is None else release
    views: list[_FlagView] = []
    for key, definition in sorted(resolved_definitions.items()):
        try:
            decision = resolved_snapshot.decision(key)
        except FeatureFlagError:
            decision = FeatureFlagDecision(
                key=key,
                enabled=definition.default,
                default=definition.default,
                source="default",
                source_detail="",
                overridden=False,
            )
        bead = None
        if definition.bead:
            bead = flag_bead_for_id(resolved_beads, definition.bead)
        if bead is None:
            bead = flag_bead_for_key(resolved_beads, key)
        due_state: FlagRemovalState | None = None
        record = None if bead is None else flag_record_from_snapshot(bead)
        if record is not None:
            due_state = flag_due_presentation(
                record, today=resolved_today, release=resolved_release
            ).state
        views.append(
            _FlagView(
                definition=definition,
                decision=decision,
                bead=bead,
                due_state=due_state,
            )
        )
    return tuple(views)


def _render_list(
    views: Sequence[_FlagView],
    *,
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
        return
    for view in views:
        console.print(_list_row(view, today=today, release=release))


def _list_row(
    view: _FlagView,
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
    line.append(f"default={_on_off(view.definition.default)}")
    line.append("  ")
    line.append(
        _on_off(view.decision.enabled),
        style="bold green" if view.decision.enabled else "bold",
    )
    line.append("  ")
    line.append_text(_source_text(view.decision))
    line.append("  ")
    line.append(view.definition.scope)
    line.append("  ")
    line.append_text(_bead_text(view.bead))
    record = None if view.bead is None else flag_record_from_snapshot(view.bead)
    if record is not None:
        line.append("  ")
        line.append_text(_flag_due_text(record, today, release))
    return line


def _flag_due_text(record: FlagRecord, today: date, release: str) -> Text:
    return flag_due_chip(record, today=today, release=release)


def _source_text(decision: FeatureFlagDecision) -> Text:
    if decision.source == "env":
        return Text(f"ENV:{SASE_FEATURE_FLAGS_ENV}", style="bold reverse")
    if decision.source == "default":
        return Text("default", style="dim")
    if decision.source_detail:
        return Text(f"{decision.source}:{decision.source_detail}")
    return Text(decision.source)


def _bead_text(bead: FlagBeadSnapshot | None) -> Text:
    if bead is None:
        return Text("—", style="dim")
    text = Text(bead.id)
    text.append(" ")
    status = bead_status_presentation(bead.status)
    text.append(f"{status.glyph} {bead.status}", style=status.rich_style)
    return text


def _render_show(
    view: _FlagView,
    *,
    layers: Sequence[dict[str, Any]],
    call_sites: Sequence[FlagCallSite],
    console: Console,
    today: date,
    release: str,
) -> None:
    key = str(view.definition.key)
    console.print(flag_key_chip(key))
    console.print(f"kind:        {view.definition.kind}")
    console.print(f"scope:       {view.definition.scope}")
    console.print(f"description: {view.definition.description}")
    if view.definition.kind == "ops" and view.definition.rationale:
        console.print(f"rationale:   {view.definition.rationale}")
    console.print()
    console.print("[bold]VALUE[/bold]")
    console.print(f"  default:    {_on_off(view.definition.default)}")
    console.print(f"  effective:  {_on_off(view.decision.enabled)}")
    console.print(Text("  source:     ") + _source_text(view.decision))
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
        record = flag_record_from_snapshot(view.bead)
        console.print(f"  id:         {view.bead.id}")
        console.print(f"  status:     {view.bead.status}")
        if view.bead.title:
            console.print(f"  title:      {view.bead.title}")
        if record is not None:
            console.print(
                f"  remove_by:  {record.remove_by_date} / {record.remove_by_release}"
            )
            due = flag_due_presentation(
                record,
                today=today,
                release=release,
            )
            console.print(f"  due:        {due.label} ({due.state})")
    console.print()
    console.print("[bold]CALL SITES[/bold]")
    if not call_sites:
        console.print("  (none found in the installed SASE package)")
        return
    for site in call_sites:
        console.print(f"  {site.path}:{site.line}  {site.text}")


def _layer_rows(
    key: str,
    definition: FeatureFlagDefinition,
    layers: Sequence[FeatureFlagLayerInput],
    *,
    env_value: bool | None,
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
            note = _layer_note(definition, layer, raw)
        rows.append({"name": layer.name, "value": value, "note": note})
    if env_value is not None:
        rows.append(
            {
                "name": "env",
                "value": env_value,
                "note": SASE_FEATURE_FLAGS_ENV,
            }
        )
    return rows


def _layer_note(
    definition: FeatureFlagDefinition,
    layer: FeatureFlagLayerInput,
    raw: object,
) -> str:
    if layer.name.startswith("plugin:"):
        return "(plugin layers cannot flip a first-party default)"
    if type(raw) is not bool:
        return "(ignored: not boolean)"
    if layer.name == "local" and definition.scope == "global":
        return "(ignored: global flag)"
    if layer.detail:
        return f"({layer.detail})"
    return "(applied)"


def _env_value_from_decision(decision: FeatureFlagDecision) -> bool | None:
    if decision.source == "env":
        return decision.enabled
    return None


def _list_json(views: Sequence[_FlagView]) -> dict[str, Any]:
    return {
        "schema_version": _LIST_JSON_SCHEMA_VERSION,
        "flags": [_view_json(view) for view in views],
    }


def _show_json(
    view: _FlagView,
    *,
    layers: Sequence[dict[str, Any]],
    call_sites: Sequence[FlagCallSite],
) -> dict[str, Any]:
    payload = _view_json(view)
    payload["schema_version"] = _SHOW_JSON_SCHEMA_VERSION
    payload["layers"] = list(layers)
    payload["call_sites"] = [
        {"path": site.path, "line": site.line, "text": site.text} for site in call_sites
    ]
    return payload


def _view_json(view: _FlagView) -> dict[str, Any]:
    record = None if view.bead is None else flag_record_from_snapshot(view.bead)
    return {
        "bead": None if view.bead is None else view.bead.id,
        "bead_status": None if view.bead is None else view.bead.status,
        "default": view.definition.default,
        "description": view.definition.description,
        "due_state": view.due_state,
        "enabled": view.decision.enabled,
        "key": str(view.definition.key),
        "kind": view.definition.kind,
        "overridden": view.decision.overridden,
        "remove_by_date": None if record is None else record.remove_by_date,
        "remove_by_release": None if record is None else record.remove_by_release,
        "scope": view.definition.scope,
        "source": view.decision.source,
        "source_detail": view.decision.source_detail,
    }


def _scaffold_text(
    key: str,
    *,
    kind: FlagKind,
    description: str,
    scope: FlagScope,
    bead_id: str | None,
    record: FlagRecord | None,
    default: bool,
) -> str:
    bead_line = (
        f"        bead={bead_id!r}," if bead_id is not None else "        bead=None,"
    )
    rationale_line = f"        rationale={description!r},\n" if kind == "ops" else ""
    thresholds = ""
    if record is not None:
        thresholds = (
            f"remove_by: {record.remove_by_date} / {record.remove_by_release}\n"
        )
    created = (
        f"Created flag bead: {bead_id} — Retire {key}\n" if bead_id is not None else ""
    )
    if kind == "ops":
        created = (
            "No flag bead created (ops flags are permanent and carry a rationale).\n"
        )
    return (
        f"{created}{thresholds}\n"
        "Paste this registry entry into src/sase/feature_flags/registry.py:\n\n"
        f"    {key} = {key!r}\n\n"
        f"    FeatureFlag.{key}: FeatureFlagDefinition(\n"
        f"        key=FeatureFlag.{key},\n"
        f"        kind={kind!r},\n"
        f"        description={description!r},\n"
        f"        default={default},\n"
        f"        scope={scope!r},\n"
        f"{bead_line}\n"
        f"{rationale_line}"
        "    ),\n\n"
        "Both-states test checklist:\n"
        "- [ ] enabled=true path is covered\n"
        "- [ ] enabled=false path is covered\n"
        f"- [ ] snapshot.enabled(FeatureFlag.{key}) is used at every call site\n"
        "- [ ] no import-time resolution\n"
    )


def _coerce_kind(value: FlagKind | str | None) -> FlagKind:
    if value is None:
        return "beta"
    if value in _KIND_CHOICES:
        return value  # type: ignore[return-value]
    raise FeatureFlagError(f"unknown flag kind: {value!r}")


def _coerce_scope(value: FlagScope | str | None) -> FlagScope:
    if value is None:
        return "global"
    if value in _SCOPE_CHOICES:
        return value  # type: ignore[return-value]
    raise FeatureFlagError(f"unknown flag scope: {value!r}")


def _default_for_kind(kind: FlagKind) -> bool:
    return kind == "sunset"


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def _format_layer_value(value: object) -> str:
    if value is None:
        return "—"
    if type(value) is bool:
        return _on_off(value)
    return repr(value)


def _console(console: Console | None) -> Console:
    if console is not None:
        return console
    return Console(highlight=False)


_MISSING: object = object()


__all__ = [
    "handle_flag_command",
]
