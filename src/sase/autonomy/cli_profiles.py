"""``sase autonomy list`` and ``sase autonomy show``.

``list`` prints the built-in profile catalog with one-liners, marking
``standard`` as the default. ``show`` prints one profile's matrix, its
layer, the selections that pick it, and the coverage line. Both come only
from core; Python never composes profile text.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.autonomy.record import COVERAGE_LINE, profiles_catalog


def handle_autonomy_list(args: argparse.Namespace) -> int:
    """Run ``sase autonomy list``."""
    as_json = bool(getattr(args, "json", False))
    try:
        catalog = profiles_catalog()
    except Exception as exc:
        print(f"sase autonomy list: {exc}", file=sys.stderr)
        sys.exit(1)
    if as_json:
        print(json.dumps({"profiles": catalog, "coverage": COVERAGE_LINE}))
        return 0
    console = Console()
    console.print(Text("Autonomy profiles", style="bold"), soft_wrap=True)
    for profile in catalog:
        console.print(_profile_line(profile), soft_wrap=True)
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


def handle_autonomy_show(args: argparse.Namespace) -> int:
    """Run ``sase autonomy show PROFILE``."""
    as_json = bool(getattr(args, "json", False))
    wanted = str(getattr(args, "profile", ""))
    try:
        catalog = profiles_catalog()
    except Exception as exc:
        print(f"sase autonomy show: {exc}", file=sys.stderr)
        sys.exit(1)
    profile = next((item for item in catalog if item.get("name") == wanted), None)
    if profile is None:
        known = ", ".join(str(item.get("name")) for item in catalog)
        print(
            f"sase autonomy show: unknown profile '{wanted}' (choose from {known})",
            file=sys.stderr,
        )
        sys.exit(2)
    if as_json:
        print(json.dumps({"profile": profile, "coverage": COVERAGE_LINE}))
        return 0
    console = Console()
    console.print(_profile_detail(profile), soft_wrap=True)
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


def _profile_line(profile: dict[str, Any]) -> Text:
    line = Text("  ")
    name = str(profile.get("name", "?"))
    line.append(name, style="bold")
    if profile.get("kind") == "default":
        line.append(" (default)", style="dim")
    oneliner = profile.get("oneliner")
    if oneliner:
        line.append(f" · {oneliner}", style="dim")
    return line


def _profile_detail(profile: dict[str, Any]) -> Text:
    body = Text()
    body.append(f"{profile.get('name', '?')}", style="bold")
    layer = profile.get("layer")
    if layer:
        body.append(f" · layer {layer}", style="dim")
    kind = profile.get("kind")
    if kind:
        body.append(f" · {kind}", style="dim")
    selections = profile.get("selections")
    if isinstance(selections, list) and selections:
        rendered = ", ".join(
            "%auto" if str(item) in ("",) else f"%auto:{item}" for item in selections
        )
        body.append(f"\nSelected by: {rendered}")
    cells = profile.get("cells")
    if isinstance(cells, list):
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            line = Text("\n  ")
            glyph = cell.get("glyph")
            if glyph:
                line.append(f"{glyph} ", style="bold")
            line.append(f"{cell.get('kind', '?')}: ", style="bold")
            line.append(str(cell.get("effect", "")))
            body.append(line)
    return body


__all__ = ["handle_autonomy_list", "handle_autonomy_show"]
