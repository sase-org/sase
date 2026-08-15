"""Implementation of ``sase artifact pane show``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table

from sase.ace.tui.artifact_tabs import (
    artifacts_pane_contract,
    configured_artifacts_pane_ids,
    reset_artifacts_subtabs_cache,
)
from sase.ace.tui._artifact_tab_model import (
    ArtifactsPaneContract,
    PaneCapability,
    PaneRelationDecl,
    PaneStatusCounter,
)


PANE_SHOW_SCHEMA_VERSION = 1


def handle_pane(args: argparse.Namespace) -> int:
    """Dispatch a parsed artifact-pane subcommand."""

    handlers = {"show": _handle_show}
    subcommand = getattr(args, "pane_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print("Usage: sase artifact pane {show}", file=sys.stderr)
        return 2
    return handler(args)


def _handle_show(args: argparse.Namespace) -> int:
    reset_artifacts_subtabs_cache()
    pane_id = str(getattr(args, "pane_id", "") or "")
    contract = artifacts_pane_contract(pane_id)
    if contract is None:
        configured = configured_artifacts_pane_ids()
        listed = ", ".join(configured) if configured else "(none)"
        print(
            f"Error: unknown Artifacts pane {pane_id!r}. Configured panes: {listed}",
            file=sys.stderr,
        )
        return 2
    payload = _payload(contract)
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_text(contract, payload)
    return 0


def _payload(contract: ArtifactsPaneContract) -> dict[str, object]:
    explanation = contract.explanation_payload()
    return {
        "schema_version": PANE_SHOW_SCHEMA_VERSION,
        **explanation,
    }


def _print_text(contract: ArtifactsPaneContract, payload: dict[str, object]) -> None:
    console = Console()
    header = Table.grid(padding=(0, 1))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Pane", f"[bold]{contract.label}[/] [dim]({contract.id})[/]")
    header.add_row("Adapter", contract.adapter or contract.ref_kind or "host")
    header.add_row("Accent", contract.accent)
    header.add_row("Digit", contract.digit or "—")
    header.add_row("Ref kind", contract.ref_kind or "—")
    header.add_row("Copy group", contract.copy_group)
    header.add_row("Digest", contract.presentation_digest)
    header.add_row(
        "Relations",
        str(len(_relation_names(contract.relations))),
    )
    header.add_row(
        "Status counters",
        str(len(_status_counter_names(contract.status_counters))),
    )
    console.print(header)
    console.print()

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        title="Capabilities",
        title_style="bold",
    )
    table.add_column("CAPABILITY")
    table.add_column("STATE")
    table.add_column("RULE")
    table.add_column("FACT")
    table.add_column("REASON")
    known = {item.value for item in PaneCapability}
    capabilities = payload["capabilities"]
    if not isinstance(capabilities, list):
        return
    for raw in capabilities:
        if not isinstance(raw, dict):
            continue
        state = str(raw["state"])
        style = "green" if state == "ON" else "red"
        suppression = raw.get("suppression")
        reason = str(raw["reason"])
        if isinstance(suppression, str) and suppression:
            reason = f"{reason} [suppressed: {suppression}]"
        name = str(raw["capability"])
        if name not in known:
            continue
        table.add_row(
            name,
            f"[{style}]{state}[/]",
            str(raw["rule"]),
            str(raw["fact"]),
            reason,
        )
    console.print(table)


def _relation_names(items: tuple[PaneRelationDecl, ...]) -> tuple[str, ...]:
    return tuple(item.name for item in items)


def _status_counter_names(items: tuple[PaneStatusCounter, ...]) -> tuple[str, ...]:
    return tuple(item.name for item in items)


__all__ = ["PANE_SHOW_SCHEMA_VERSION", "handle_pane"]
