"""Rendering for ``sase macro types``."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.bead.cli_dep_render import resolve_color


def _catalog_entries() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(entries, diagnostics)`` from the Rust catalog projection."""
    from sase.core.rust import require_rust_binding
    from sase.macro.plugin_input_types import get_plugin_input_type_registry

    snapshot = get_plugin_input_type_registry()
    registry = snapshot.get("registry", {})
    diagnostics = list(snapshot.get("diagnostics", []))
    binding = require_rust_binding("macro_input_type_catalog")
    try:
        entries = binding({"registry": registry}) if registry else binding()
    except TypeError:
        entries = binding()
    return list(entries), diagnostics


def _normalize_distribution(dist: str) -> str:
    from sase.version._utils import normalize_distribution_name

    try:
        return normalize_distribution_name(dist)
    except Exception:
        return dist.lower().replace("_", "-").replace(".", "-")


def _find_entry(entries: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    raw = name.strip()
    if "@" in raw:
        plugin, _, type_id = raw.partition("@")
        if plugin.casefold() == "builtin":
            needle = type_id.lower()
            for entry in entries:
                if entry.get("name", "").lower() == needle:
                    return entry
                aliases = [str(a).lower() for a in entry.get("aliases", [])]
                if needle in aliases:
                    return entry
            return None
        normalized = _normalize_distribution(plugin)
        qualified = f"{normalized}@{type_id}"
        for entry in entries:
            if entry.get("name") == qualified:
                return entry
        return None
    needle = raw.lower()
    for entry in entries:
        if entry.get("name", "").lower() == needle:
            return entry
        aliases = [str(a).lower() for a in entry.get("aliases", [])]
        if needle in aliases:
            return entry
    return None


def _values_or_rule(entry: dict[str, Any]) -> str:
    choices = entry.get("choices", [])
    if choices:
        values = [str(item.get("value", "")) for item in choices]
        if len(values) <= 4:
            return "|".join(values)
        return f"{entry.get('name')} ({len(values)})"
    return str(entry.get("rule", ""))


def _source_label(entry: dict[str, Any]) -> str:
    source = entry.get("source", {})
    if isinstance(source, dict):
        kind = str(source.get("kind", ""))
        if kind == "builtin":
            return "builtin"
        if kind == "plugin":
            dist = source.get("distribution", "")
            return f"plugin {dist}"
    return "builtin"


def handle_types(args: argparse.Namespace) -> int:
    """Implement ``sase macro types [NAME] [-j/--json]``."""
    entries, diagnostics = _catalog_entries()
    want_json = bool(getattr(args, "json", False))
    name = getattr(args, "type_name", None)

    if want_json:
        for diagnostic in diagnostics:
            print(
                f"{diagnostic.get('path', '')}: {diagnostic.get('message', '')}",
                file=sys.stderr,
            )
        if name:
            entry = _find_entry(entries, name)
            if entry is None:
                print(f"unknown type: {name}", file=sys.stderr)
                return 1
            json.dump(entry, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        json.dump(entries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if name:
        entry = _find_entry(entries, name)
        if entry is None:
            print(f"unknown type: {name}", file=sys.stderr)
            return 1
        _render_detail(entry)
        for diagnostic in diagnostics:
            print(
                f"{diagnostic.get('path', '')}: {diagnostic.get('message', '')}",
                file=sys.stderr,
            )
        return 0

    _render_grouped(entries)
    for diagnostic in diagnostics:
        print(
            f"{diagnostic.get('path', '')}: {diagnostic.get('message', '')}",
            file=sys.stderr,
        )
    return 0


def _console() -> Console:
    width = shutil.get_terminal_size((100, 24)).columns if sys.stdout.isatty() else 100
    return Console(
        no_color=False,
        force_terminal=False,
        color_system="256",
        width=width,
        markup=False,
        emoji=False,
        highlight=False,
    )


def _render_grouped(entries: list[dict[str, Any]]) -> None:
    console = _console()
    scalars = [e for e in entries if e.get("kind") == "scalar"]
    builtins = [
        e
        for e in entries
        if e.get("kind") in ("named_enum", "domain", "inline_enum")
        and _source_label(e) == "builtin"
    ]
    plugins = [e for e in entries if _source_label(e).startswith("plugin")]
    for title, rows in (
        ("Scalar", scalars),
        ("Builtin", builtins),
        ("Plugin", plugins),
    ):
        if not rows:
            continue
        table = Table(title=title, show_header=True, header_style="bold")
        table.add_column("name")
        table.add_column("kind")
        table.add_column("values or rule")
        table.add_column("source")
        for entry in sorted(rows, key=lambda e: str(e.get("name", ""))):
            table.add_row(
                str(entry.get("name", "")),
                str(entry.get("kind", "")),
                _values_or_rule(entry),
                _source_label(entry),
            )
        console.print(table)


def _render_detail(entry: dict[str, Any]) -> None:
    console = _console()
    console.print(f"[bold]{entry.get('name', '')}[/bold]")
    console.print(str(entry.get("description", "")))
    console.print(f"rule: {entry.get('rule', '')}")
    source = entry.get("source", {})
    if isinstance(source, dict) and source.get("kind") == "plugin":
        console.print(f"source: plugin {source.get('distribution', '')}")
        if source.get("path"):
            console.print(f"file: {source.get('path')}")
    else:
        console.print("source: builtin")
    choices = entry.get("choices", [])
    if choices:
        table = Table(show_header=True, header_style="bold")
        table.add_column("value")
        table.add_column("label")
        table.add_column("description")
        for choice in choices:
            table.add_row(
                str(choice.get("value", "")),
                str(choice.get("label", "") or ""),
                str(choice.get("description", "") or ""),
            )
        console.print(table)


__all__ = ["handle_types"]
