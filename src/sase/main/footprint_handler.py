"""Dispatch for the ``sase footprint`` command group."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.footprint.catalog import CatalogEntry, load_catalog
from sase.footprint.ids import NAMESPACES
from sase.main.parser import create_parser
from sase.main.parser_root_help import root_subparser_action


def handle_footprint_command(args: argparse.Namespace) -> int:
    """Handle ``sase footprint`` and its implemented subcommands."""
    subcommand = getattr(args, "footprint_subcommand", None)
    if subcommand is None:
        _print_group_help()
        return 0
    if subcommand == "mode":
        from sase.footprint._mode import DISCLOSURE, current_mode, set_mode

        selected = getattr(args, "mode", None)
        if selected is None:
            print(f"Footprint recording mode: {current_mode()}")
            print(DISCLOSURE)
            return 0
        set_mode(selected)
        print(f"Footprint recording mode set to {selected}.")
        return 0
    if subcommand == "catalog":
        return _handle_catalog(args)
    if subcommand == "clear":
        return _handle_clear(args)
    if subcommand == "status":
        return _handle_status(args)
    print(
        f"sase footprint: unknown view {subcommand!r}. "
        "Implemented views: catalog, clear, mode, status.",
        file=sys.stderr,
    )
    return 2


def _print_group_help() -> None:
    parser = create_parser(only="footprint")
    root_subparser_action(parser).choices["footprint"].print_help()


def _handle_catalog(args: argparse.Namespace) -> int:
    header, entries = load_catalog()
    area = getattr(args, "area", None)
    namespace = getattr(args, "namespace", None)
    fmt = getattr(args, "format", None) or "rich"
    if area is not None:
        entries = [entry for entry in entries if entry.area == area]
    if namespace is not None:
        entries = [entry for entry in entries if entry.ns == namespace]
    if fmt == "json":
        print(
            json.dumps(
                {
                    "schema": header.schema,
                    "rev": header.rev,
                    "count": len(entries),
                    "entries": [
                        {
                            "id": entry.id,
                            "ns": entry.ns,
                            "area": entry.area,
                            "kind": entry.kind,
                            "label": entry.label,
                            "parent": entry.parent,
                            "src": entry.src,
                        }
                        for entry in entries
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if fmt == "markdown":
        _print_catalog_markdown(header.rev, entries)
        return 0
    _print_catalog_rich(header.rev, entries)
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    from sase.footprint.fold import fold_if_stale

    try:
        status = fold_if_stale()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not read Footprint status: {exc}", file=sys.stderr)
        return 1
    fmt = getattr(args, "format", None) or "rich"
    if fmt == "json":
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        _print_status(status)
    return 0


def _handle_clear(args: argparse.Namespace) -> int:
    from rich.prompt import Confirm

    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            print(
                "Confirmation required; rerun with `sase footprint clear -y`.",
                file=sys.stderr,
            )
            return 2
        try:
            confirmed = Confirm.ask(
                "Clear the Footprint ledger and local spool?", default=False
            )
        except (EOFError, OSError):
            confirmed = False
        if not confirmed:
            Console().print("Footprint data was not cleared.", style="dim")
            return 0

    from sase.footprint.fold import clear_ledger

    try:
        result = clear_ledger()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not clear Footprint data: {exc}", file=sys.stderr)
        return 1
    Console().print(
        f"Footprint data cleared · generation {result['generation']}",
        style="green",
    )
    return 0


def _print_status(status: dict[str, object]) -> None:
    from sase.footprint._mode import current_mode
    from sase.footprint.paths import sase_home
    from sase.core.footprint_facade import footprint_ledger_path

    header, entries = load_catalog()
    surfaces = sorted(
        {entry.ns for entry in entries},
        key=lambda item: NAMESPACES.index(item) if item in NAMESPACES else item,
    )
    now = datetime.now(UTC)
    today = date.today()
    dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold")
    details.add_column()
    mode = current_mode()
    mode_style = "green" if mode == "local" else "yellow" if mode == "test" else "red"
    details.add_row("Mode", Text(mode, style=mode_style))
    details.add_row(
        "Privacy",
        "feature IDs and counts only · stays on this machine",
    )
    details.add_row(
        "Recording since",
        str(status.get("first_record_day") or "no records yet"),
    )
    details.add_row(
        "Ledger",
        f"{footprint_ledger_path(sase_home())} · {_format_bytes(status.get('ledger_bytes'))}",
    )
    details.add_row(
        "Last fold",
        _relative_age(status.get("last_fold_at"), now),
    )
    details.add_row(
        "Spool backlog",
        f"{_count(status.get('spool_files_pending'))} file(s) · "
        f"{_format_bytes(status.get('spool_bytes_pending'))}",
    )
    catalog_rev = status.get("catalog_rev")
    if catalog_rev:
        catalog_summary = (
            f"{_count(status.get('catalog_count'))} ingested · "
            f"{len(surfaces)} surfaces · rev {catalog_rev}"
        )
    else:
        catalog_summary = (
            f"{len(entries)} bundled features · {len(surfaces)} surfaces · "
            f"rev {header.rev} (not ingested)"
        )
    details.add_row("Catalog", catalog_summary)

    coverage_table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        padding=(0, 1),
    )
    coverage_table.add_column("Surface")
    for day in dates:
        coverage_table.add_column(day.strftime("%m-%d"), justify="center")
    coverage = _coverage_by_day(status.get("coverage"), dates)
    for surface in surfaces:
        cells = [
            _coverage_glyph(coverage.get(surface, {}).get(day.isoformat(), {}))
            for day in dates
        ]
        coverage_table.add_row(surface, *cells)

    faults = {
        "dropped": _count(status.get("dropped_total")),
        "torn": _count(status.get("torn_total")),
        "unknown IDs": _count(status.get("unknown_ids_total")),
    }
    fault_summary = Text("Faults: ")
    nonzero = [(name, value) for name, value in faults.items() if value]
    if nonzero:
        fault_summary.append(
            " · ".join(f"{name} {value}" for name, value in nonzero),
            style="red",
        )
    else:
        fault_summary.append("none", style="dim")

    Console().print(
        Panel(
            Group(
                details,
                Rule("Coverage · last 7 days", style="dim"),
                coverage_table,
                fault_summary,
            ),
            title="Footprint status",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _coverage_by_day(
    raw: object,
    dates: list[date],
) -> dict[str, dict[str, dict[str, int]]]:
    if not isinstance(raw, list):
        return {}
    start = dates[0].isoformat()
    end = dates[-1].isoformat()
    result: dict[str, dict[str, dict[str, int]]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        surface = str(item.get("surface") or "")
        day = str(item.get("day") or "")
        if not surface or day < start or day > end:
            continue
        cell = result.setdefault(surface, {}).setdefault(
            day,
            {"measured": 0, "human_active": 0, "records": 0, "incomplete": 0},
        )
        for key in cell:
            try:
                cell[key] += max(0, int(item.get(key, 0)))
            except (TypeError, ValueError):
                continue
    return result


def _coverage_glyph(values: Mapping[str, int]) -> Text:
    if values.get("incomplete", 0):
        return Text("!", style="yellow")
    if not values.get("measured", 0):
        return Text("·", style="dim")
    if values.get("human_active", 0):
        return Text("●", style="green")
    if values.get("records", 0):
        return Text("•", style="cyan")
    return Text("○", style="dim")


def _relative_age(value: object, now: datetime) -> str:
    if not isinstance(value, str) or not value:
        return "never"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    seconds = max(0, int((now - parsed.astimezone(UTC)).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _format_bytes(value: object) -> str:
    size = _count(value)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _count(value: Any) -> int:
    if isinstance(value, int):
        return max(0, value)
    if not isinstance(value, str):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _print_catalog_rich(rev: str, entries: list[CatalogEntry]) -> None:
    counts = Counter(entry.area for entry in entries)
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("AREA")
    table.add_column("FEATURES", justify="right")
    for area in sorted(counts):
        table.add_row(area, str(counts[area]))
    console.print(table)
    console.print(
        f"{len(entries)} features · catalog rev {rev}",
        style="dim",
    )


def _print_catalog_markdown(rev: str, entries: list[CatalogEntry]) -> None:
    print(f"# Footprint catalog (rev {rev})")
    print()
    for area in sorted({entry.area for entry in entries}):
        print(f"## {area}")
        print()
        for entry in [entry for entry in entries if entry.area == area]:
            print(f"- `{entry.id}` — {entry.label}")
        print()


__all__ = ["handle_footprint_command"]
