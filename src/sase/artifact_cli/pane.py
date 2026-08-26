"""Implementation of ``sase artifact pane show``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.ace.tui.artifact_tabs import (
    artifacts_pane_contract,
    configured_artifacts_pane_ids,
    reset_artifacts_subtabs_cache,
)
from sase.ace.tui._artifact_tab_actions import (
    CAPABILITY_HOST_ACTIONS,
    action_applies_to_contract,
    keymap_actions_by_key,
)
from sase.ace.tui._artifact_tab_descriptions import (
    MAX_PANE_DESCRIPTION_BODY_CHARS,
    MAX_PANE_DESCRIPTION_SUMMARY_CHARS,
    sanitize_description,
)
from sase.ace.tui._artifact_tab_model import (
    ArtifactsPaneContract,
    PaneGroupingModeDecl,
    PaneCapability,
    PaneRelationDecl,
    PaneStatusCounter,
)
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.keymaps.key_validation import is_unbound_key


PANE_SHOW_SCHEMA_VERSION = 3


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
        "keys": _declared_key_payload(contract),
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
        "Grouping",
        str(len(_grouping_mode_names(contract.grouping.modes))),
    )
    header.add_row(
        "Status counters",
        str(len(_status_counter_names(contract.status_counters))),
    )
    console.print(header)
    console.print()

    _print_description(console, contract)
    _print_relations(console, contract.relations)
    _print_grouping(console, contract.grouping.modes)
    _print_keys(console, contract)

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


def _print_description(console: Console, contract: ArtifactsPaneContract) -> None:
    console.print("[bold]Description[/]")
    summary = sanitize_description(
        contract.description,
        max_len=MAX_PANE_DESCRIPTION_SUMMARY_CHARS,
    )
    body = sanitize_description(
        contract.description_body,
        max_len=MAX_PANE_DESCRIPTION_BODY_CHARS,
        preserve_paragraphs=True,
    )
    console.print(Text(summary))
    if body:
        console.print(Text(body))
    console.print(Text(f"summary source: {contract.description_source}", style="dim"))
    console.print(Text(f"body source: {contract.description_body_source}", style="dim"))
    console.print()


def _print_relations(
    console: Console,
    relations: tuple[PaneRelationDecl, ...],
) -> None:
    if not relations:
        console.print("[dim]Relations: none declared[/]")
        console.print()
        return
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        title="Relations",
        title_style="bold",
    )
    table.add_column("NAME")
    table.add_column("KIND")
    table.add_column("SOURCE")
    table.add_column("TARGET")
    table.add_column("INVERSE")
    table.add_column("FLAGS")
    for relation in relations:
        flags = []
        if relation.directed:
            flags.append("directed")
        if relation.transitive:
            flags.append("transitive")
        table.add_row(
            relation.name,
            relation.kind.value,
            relation.source,
            relation.target_pane or "same-pane",
            relation.inverse or "—",
            ", ".join(flags) or "undirected",
        )
    console.print(table)
    console.print()


def _print_grouping(
    console: Console,
    modes: tuple[PaneGroupingModeDecl, ...],
) -> None:
    if not modes:
        console.print("[dim]Grouping: none declared[/]")
        console.print()
        return
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        title="Grouping",
        title_style="bold",
    )
    table.add_column("MODE")
    table.add_column("LABEL")
    table.add_column("KEYS")
    for mode in modes:
        table.add_row(mode.id, mode.label, ", ".join(mode.keys))
    console.print(table)
    console.print()


def _declared_key_payload(contract: ArtifactsPaneContract) -> list[dict[str, str]]:
    registry = load_keymap_registry({})
    by_key = keymap_actions_by_key(registry.app)
    rows: list[dict[str, str]] = []
    for capability in contract.capabilities:
        for action in CAPABILITY_HOST_ACTIONS[capability]:
            if not action_applies_to_contract(contract, action):
                continue
            if not hasattr(registry.app, action):
                continue
            key = getattr(registry.app, action)
            if not isinstance(key, str) or is_unbound_key(key):
                continue
            owners = by_key.get(key, (action,))
            rows.append(
                {
                    "action": action,
                    "key": key,
                    "owners": ",".join(owners),
                }
            )
    return rows


def _print_keys(console: Console, contract: ArtifactsPaneContract) -> None:
    rows = _declared_key_payload(contract)
    if not rows:
        console.print("[dim]Keys: none declared[/]")
        console.print()
        return
    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        title="Keys",
        title_style="bold",
    )
    table.add_column("ACTION")
    table.add_column("KEY")
    for row in rows:
        table.add_row(row["action"], row["key"])
    console.print(table)
    console.print()


def _relation_names(items: tuple[PaneRelationDecl, ...]) -> tuple[str, ...]:
    return tuple(item.name for item in items)


def _grouping_mode_names(items: tuple[PaneGroupingModeDecl, ...]) -> tuple[str, ...]:
    return tuple(item.id for item in items)


def _status_counter_names(items: tuple[PaneStatusCounter, ...]) -> tuple[str, ...]:
    return tuple(item.name for item in items)


__all__ = ["PANE_SHOW_SCHEMA_VERSION", "handle_pane"]
