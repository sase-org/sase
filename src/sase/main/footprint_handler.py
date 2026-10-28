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
    if subcommand == "decide":
        return _handle_decide(args)
    if subcommand == "list":
        return _handle_list(args)
    if subcommand == "show":
        return _handle_show(args)
    if subcommand == "status":
        return _handle_status(args)
    print(
        f"sase footprint: unknown view {subcommand!r}. "
        "Implemented views: catalog, clear, decide, list, mode, show, status.",
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


def _handle_list(args: argparse.Namespace) -> int:
    from sase.footprint.fold import fold_if_stale
    from sase.footprint.query import (
        build_report_request,
        fetch_report,
        parse_range_days,
    )
    from sase.footprint.render import report_markdown

    fmt = getattr(args, "format", None) or "rich"
    lens = getattr(args, "lens", None) or "map"
    actor = getattr(args, "actor", None) or "you"
    try:
        window_days = parse_range_days(getattr(args, "range", None) or "60d")
    except ValueError as exc:
        print(f"sase footprint list: {exc}", file=sys.stderr)
        return 2
    try:
        fold_if_stale()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not fold Footprint spool: {exc}", file=sys.stderr)
        return 1
    try:
        report = fetch_report(
            build_report_request(
                lens=lens,
                actor=actor,
                window_days=window_days,
                area=getattr(args, "area", None),
            )
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not read Footprint report: {exc}", file=sys.stderr)
        return 1
    if fmt == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if fmt == "markdown":
        print(report_markdown(report, lens), end="")
        return 0
    _print_report_rich(report, lens)
    return 0


def _handle_show(args: argparse.Namespace) -> int:
    from sase.footprint.fold import fold_if_stale
    from sase.footprint.query import (
        build_card_request,
        build_report_request,
        fetch_card,
        fetch_report,
        parse_range_days,
    )
    from sase.footprint.render import card_markdown

    fmt = getattr(args, "format", None) or "rich"
    actor = getattr(args, "actor", None) or "you"
    target = getattr(args, "feature_id", None) or ""
    try:
        window_days = parse_range_days(getattr(args, "range", None) or "60d")
    except ValueError as exc:
        print(f"sase footprint show: {exc}", file=sys.stderr)
        return 2
    try:
        fold_if_stale()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not fold Footprint spool: {exc}", file=sys.stderr)
        return 1
    try:
        card = fetch_card(
            build_card_request(target=target, actor=actor, window_days=window_days)
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not read Footprint card: {exc}", file=sys.stderr)
        return 1
    try:
        header_report = fetch_report(
            build_report_request(lens="map", actor=actor, window_days=window_days)
        )
    except (OSError, RuntimeError, TimeoutError, ValueError):
        header_report = {"header": {"actor": actor, "observed_active_days": {}}}
    header = dict(header_report.get("header", {}))
    if fmt == "json":
        print(json.dumps(card, indent=2, sort_keys=True))
        return 0
    if fmt == "markdown":
        print(card_markdown(card, header), end="")
        return 0
    _print_card_rich(card, header)
    return 0


def _handle_decide(args: argparse.Namespace) -> int:
    from sase.footprint.ids import is_valid_feature_id
    from sase.footprint.query import record_decision

    feature_id = getattr(args, "feature_id", None) or ""
    decision = getattr(args, "decision", None) or ""
    reason = getattr(args, "reason", None)
    if not is_valid_feature_id(feature_id):
        print(
            f"sase footprint decide: invalid feature ID {feature_id!r}",
            file=sys.stderr,
        )
        return 2
    try:
        result = record_decision(feature_id, decision, reason)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Could not record Footprint decision: {exc}", file=sys.stderr)
        return 1
    stored = result.get("decision")
    if stored is None:
        Console().print(f"Cleared decision for `{feature_id}`.", style="dim")
    else:
        suffix = f" ({result.get('reason')})" if result.get("reason") else ""
        Console().print(
            f"Recorded `{feature_id}` → {stored}{suffix}.",
            style="green",
        )
    return 0


def _print_report_rich(report: dict[str, Any], lens: str) -> None:
    from rich.columns import Columns

    from sase.footprint.render import (
        area_row_text,
        feature_row_text,
        header_chip,
        header_text,
        legend_text,
        tiles_row,
    )

    console = Console()
    header_line = header_text(report)
    header_line.append("   ")
    header_line.append_text(header_chip(report))
    console.print(header_line)
    header = dict(report.get("header", {}))
    tiles = dict(report.get("tiles", {}))
    if int(tiles.get("total", 0) or 0) <= 0 and not header.get("recording_since"):
        console.print(
            "No Footprint data yet · recording since now · first fold within the hour",
            style="dim",
        )
        console.print(legend_text())
        return
    tile_group = tiles_row(report)
    assert isinstance(tile_group, Group)
    console.print(Columns(list(tile_group.renderables), equal=True))
    if lens == "map":
        width = max(12, min(48, console.size.width - 44))
        areas = report.get("areas", [])
        if not areas:
            console.print("No areas in this lens.", style="dim")
        for area in areas if isinstance(areas, list) else []:
            if isinstance(area, dict):
                console.print(area_row_text(area, strip_width=width))
    elif lens == "coverage":
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("SURFACE")
        table.add_column("MEASURED", justify="right")
        table.add_column("ACTIVE", justify="right")
        table.add_column("TORN", justify="right")
        table.add_column("DROPPED", justify="right")
        table.add_column("UNKNOWN", justify="right")
        table.add_column("INCOMPLETE", justify="right")
        for item in (
            report.get("coverage", [])
            if isinstance(report.get("coverage"), list)
            else []
        ):
            if not isinstance(item, dict):
                continue
            table.add_row(
                str(item.get("surface", "")),
                str(item.get("measured_days", 0)),
                str(item.get("active_days", 0)),
                str(item.get("torn", 0)),
                str(item.get("dropped", 0)),
                str(item.get("unknown_ids", 0)),
                str(item.get("incomplete_days", 0)),
            )
        console.print(table)
    else:
        rows = report.get("rows", [])
        if not rows:
            console.print("No features in this lens.", style="dim")
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                console.print(feature_row_text(row))
    console.print(legend_text())


def _print_card_rich(card: dict[str, Any], header: dict[str, Any]) -> None:
    from sase.footprint.render import card_panel, legend_text

    console = Console()
    console.print(card_panel(card, header))
    console.print(legend_text())


__all__ = ["handle_footprint_command"]
