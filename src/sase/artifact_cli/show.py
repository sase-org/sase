"""Implementation of ``sase artifact show``."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.artifact_refs import render_artifact_ref
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    artifact_file_json_dict,
    resolve_cli_reference,
)
from sase.core.artifact_consumption_query import (
    ArtifactConsumptionSummary,
    summarize_artifact_consumption,
)
from sase.sdd.artifact_link_store import (
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)


def handle_show(args: argparse.Namespace) -> int:
    """Render metadata and resolution details for one reference."""

    try:
        result = resolve_cli_reference(args.reference)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: malformed artifact reference: {exc}", file=sys.stderr)
        return 1

    consumption_reference = render_artifact_ref(replace(result.parsed, fragment=None))
    summary = summarize_artifact_consumption([consumption_reference]).get(
        consumption_reference
    )
    result = replace(result, consumption=summary)
    links = _load_links(consumption_reference)

    if bool(getattr(args, "json", False)):
        payload = result.to_json_dict()
        ordered: dict[str, object] = {}
        for key, value in payload.items():
            ordered[key] = value
            if key == "consumption":
                ordered["links"] = links
        json.dump(ordered, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif result.parsed.kind_type == "file" and result.file is not None:
        _print_file(result, links=links)
    else:
        _print_resolution(result, links=links)

    if result.parsed.kind_type == "file" and result.file is None:
        print(
            f"Error: no indexed file record found for {result.canonical_reference}",
            file=sys.stderr,
        )
        return 1
    return 0


def _print_file(
    result: ResolvedArtifactReference, *, links: list[dict[str, object]]
) -> None:
    assert result.file is not None
    table = _metadata_table()
    payload = artifact_file_json_dict(result.file)
    table.add_row("ref", result.canonical_reference)
    for key, value in payload.items():
        if key == "ref":
            continue
        table.add_row(key, _display_value(value))
    table.add_row(
        "stored_path_status",
        (
            f"vcs-backed ({result.resolution.locator or 'locator unavailable'})"
            if result.file.is_vcs_backed
            else _path_status(result.file.path)
        ),
    )
    table.add_row(
        "source_path_status",
        (
            "not recorded"
            if result.file.source_path is None
            else _path_status(result.file.source_path)
        ),
    )
    table.add_row("resolution_status", result.resolution.status)
    table.add_row(
        "resolution_candidates",
        "\n".join(result.resolution.candidates) or "-",
    )
    _add_consumption_rows(table, result.consumption)
    _add_link_rows(table, links)
    Console().print(
        Panel(
            table,
            title=f"Artifact {result.canonical_reference}",
            border_style="cyan",
        )
    )


def _print_resolution(
    result: ResolvedArtifactReference, *, links: list[dict[str, object]]
) -> None:
    table = _metadata_table()
    table.add_row("kind", result.parsed.kind)
    table.add_row("reference", result.canonical_reference)
    table.add_row(
        "fragment",
        (
            "-"
            if result.parsed.fragment is None
            else json.dumps(result.to_json_dict()["fragment"], sort_keys=True)
        ),
    )
    table.add_row("status", result.resolution.status)
    table.add_row("locator", result.resolution.locator or "-")
    table.add_row(
        "path",
        (
            "-"
            if result.resolution.resolved_path is None
            else str(result.resolution.resolved_path)
        ),
    )
    table.add_row(
        "candidates",
        "\n".join(result.resolution.candidates) or "-",
    )
    _add_consumption_rows(table, result.consumption)
    _add_link_rows(table, links)
    Console().print(
        Panel(
            table,
            title="Artifact Reference",
            border_style="cyan",
        )
    )


def _metadata_table() -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    return table


def _add_consumption_rows(
    table: Table,
    summary: ArtifactConsumptionSummary | None,
) -> None:
    if summary is None:
        table.add_row("consumption_count", "never consumed")
        table.add_row("consumed_by_agents", "-")
        table.add_row("consuming_agents", "-")
        table.add_row("last_consumed_at", "-")
        return

    names = list(summary.agent_names[:5])
    remaining = len(summary.agent_names) - len(names)
    consuming_agents = ", ".join(names)
    if remaining:
        consuming_agents = f"{consuming_agents} +{remaining} more"
    table.add_row("consumption_count", str(summary.consumption_count))
    table.add_row("consumed_by_agents", str(summary.distinct_agent_count))
    table.add_row("consuming_agents", consuming_agents or "-")
    table.add_row("last_consumed_at", summary.last_consumed_at or "-")


def _add_link_rows(table: Table, links: list[dict[str, object]]) -> None:
    if not links:
        table.add_row("links", "none")
        return
    rendered = []
    for row in links:
        rendered.append(
            f"{row.get('relation')} {row.get('source_ref')} -> {row.get('target_ref')}"
        )
    table.add_row("links", "\n".join(rendered))


def _load_links(reference: str) -> list[dict[str, object]]:
    try:
        store = resolve_artifact_link_store()
        canonical = canonicalize_artifact_link_ref(reference)
        return [dict(row) for row in store.load_artifact_rows(canonical)]
    except Exception:  # noqa: BLE001 - show still reports metadata
        return []


def _display_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _path_status(path: str | None) -> str:
    if not path:
        return "not recorded"
    try:
        return "live" if Path(path).expanduser().is_file() else "missing"
    except OSError:
        return "missing"


__all__ = ["handle_show"]
