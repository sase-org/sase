"""Rich and Markdown rendering for ``sase snippet`` output."""

from __future__ import annotations

from io import StringIO
from typing import Literal, cast

from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.snippet.models import (
    SnippetEntry,
    SnippetLayerDiagnostic,
    SnippetMutationOutcome,
    SnippetSourceContribution,
)

_ColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]
_SUMMARY_WIDTH = 48
_ACCENT = SECTION_COLOR


def _compact_template(template: str, *, width: int = _SUMMARY_WIDTH) -> str:
    """Collapse *template* whitespace into a table-cell summary."""
    one_line = " ".join(template.split())
    if len(one_line) <= width:
        return one_line
    return one_line[: width - 3].rstrip() + "..."


def _origin_label(origin: SnippetSourceContribution) -> str:
    """Return a compact origin badge for list tables."""
    badge = origin.kind
    if not origin.writable:
        return f"{badge} RO"
    return badge


def _join_names(names: tuple[str, ...]) -> str:
    """Return a compact joined name list, or an em dash when empty."""
    if not names:
        return "—"
    return ", ".join(names)


def print_rich(console: Console, renderable: RenderableType) -> None:
    """Print *renderable* with wrap-padding stripped from every line."""
    buffer = StringIO()
    capture = Console(
        file=buffer,
        width=console.width,
        force_terminal=console.is_terminal,
        color_system=cast(_ColorSystem | None, console.color_system),
        highlight=False,
        markup=False,
    )
    capture.print(renderable)
    console.file.write(_rstrip_output_lines(buffer.getvalue()))


def build_list_table(
    *,
    project_name: str,
    entries: tuple[SnippetEntry, ...],
    diagnostics: tuple[SnippetLayerDiagnostic, ...],
) -> Table:
    """Build the Rich table for ``sase snippet list``."""
    title = Text("SNIPPET", style=f"bold {_ACCENT}")
    if project_name:
        title.append("  ")
        title.append(project_name, style="bold")
    table = Table(
        title=title,
        caption=_list_caption(entries, diagnostics),
        show_header=True,
        header_style="bold",
    )
    table.add_column("Trigger")
    table.add_column("Origin", no_wrap=True)
    table.add_column("Calls")
    table.add_column("Backlinks")
    table.add_column("Summary")
    for entry in entries:
        table.add_row(
            entry.trigger,
            _origin_label(entry.origin),
            _join_names(entry.relations.outbound),
            _join_names(entry.relations.inbound),
            _compact_template(entry.raw_template),
        )
    return table


def build_write_table(outcome: SnippetMutationOutcome) -> Table:
    """Build the Rich key/value table for an add or delete outcome."""
    verb = outcome.action.upper()
    title = Text("SNIPPET", style=f"bold {_ACCENT}")
    title.append("  ")
    title.append(verb, style="bold")
    if outcome.dry_run:
        title.append("  ")
        title.append("DRY-RUN", style="bold yellow")
    if outcome.project_name:
        title.append("  ")
        title.append(outcome.project_name, style="bold")
    table = Table(title=title, show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    table.add_row("Trigger", outcome.trigger)
    table.add_row("Action", outcome.action)
    table.add_row("Template", _compact_template(outcome.template, width=72))
    table.add_row("Path", Text(outcome.write_path, style=PATH_COLOR))
    if outcome.apply_target:
        table.add_row("Apply", Text(outcome.apply_target, style=PATH_COLOR))
    if outcome.removed_paths:
        table.add_row("Removed", " · ".join(outcome.removed_paths))
    if outcome.affected_backlinks:
        table.add_row("Backlinks", _join_names(outcome.affected_backlinks))
    if outcome.action == "deleted":
        table.add_row("Restore", outcome.restore_command)
        table.add_row("Revealed", _revealed_label(outcome))
    return table


def show_renderable(entry: SnippetEntry, *, project_name: str) -> Group:
    """Build the Rich detail view for ``sase snippet show``."""
    blocks: list[RenderableType] = [_show_header(entry, project_name=project_name)]
    blocks.append(Text(""))
    blocks.extend(_field_rows(entry))
    blocks.append(Text(""))
    blocks.append(_section("RAW"))
    blocks.append(Text(entry.raw_template or "—"))
    blocks.append(Text(""))
    blocks.append(_section("COMPOSED"))
    blocks.append(Text(entry.composed_template or "—"))
    blocks.append(Text(""))
    blocks.append(_section("SOURCES"))
    for item in entry.contributions:
        blocks.append(_source_line(item, winning=item.shadowed_by is None))
    blocks.append(Text(""))
    blocks.append(_section("CALLS"))
    if entry.relations.calls:
        for index, call in enumerate(entry.relations.calls, start=1):
            target = call.canonical_target or call.authored_target
            blocks.append(Text(f"{index}  {target}  {call.status}"))
    else:
        blocks.append(Text("—", style="dim"))
    blocks.append(Text(""))
    blocks.append(_section("CALLED BY"))
    if entry.relations.inbound:
        for index, name in enumerate(entry.relations.inbound, start=1):
            blocks.append(Text(f"{index}  {name}"))
    else:
        blocks.append(Text("—", style="dim"))
    if entry.diagnostics:
        blocks.append(Text(""))
        blocks.append(_section("DIAGNOSTICS"))
        for diagnostic in entry.diagnostics:
            blocks.append(Text(f"{diagnostic.code}: {diagnostic.message}"))
    return Group(*blocks)


def show_markdown(entry: SnippetEntry, *, project_name: str) -> str:
    """Return the Markdown detail view for ``sase snippet show``."""
    lines = [f"# {entry.trigger}", ""]
    if project_name:
        lines.append(f"Project: {project_name}")
    lines.append(f"Origin: {_markdown_origin(entry.origin)}")
    lines.append(
        "Aliases: " + (", ".join(entry.aliases) if entry.aliases else "(none)")
    )
    lines.append(
        "Calls: "
        + (
            ", ".join(entry.relations.outbound)
            if entry.relations.outbound
            else "(none)"
        )
    )
    lines.append(
        "Called by: "
        + (", ".join(entry.relations.inbound) if entry.relations.inbound else "(none)")
    )
    lines.extend(["", "## Raw", "", "```", entry.raw_template, "```", ""])
    lines.extend(["## Composed", "", "```", entry.composed_template, "```", ""])
    lines.extend(["## Sources", ""])
    for item in entry.contributions:
        marker = "winning" if item.shadowed_by is None else "shadowed"
        path = item.display_path or item.path or item.kind
        writable = "writable" if item.writable else "read-only"
        lines.append(f"- {item.kind} (`{path}`) · {writable} · {marker}")
        if item.xprompt_name:
            lines.append(f"  - xprompt: {item.xprompt_name}")
    if entry.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for diagnostic in entry.diagnostics:
            lines.append(f"- `{diagnostic.code}`: {diagnostic.message}")
    lines.append("")
    return "\n".join(lines)


def _show_header(entry: SnippetEntry, *, project_name: str) -> RenderableType:
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)
    left = Text()
    left.append("SNIPPET", style=f"bold {_ACCENT}")
    if project_name:
        left.append("  ")
        left.append(project_name, style="bold")
    left.append("  ")
    left.append(entry.trigger, style="bold")
    mutability = "writable" if entry.origin.writable else "read-only"
    right = Text(f"{entry.origin.kind} · {mutability}", style="dim")
    grid.add_row(left, right)
    return grid


def _field_rows(entry: SnippetEntry) -> list[RenderableType]:
    aliases = ", ".join(entry.aliases) if entry.aliases else "—"
    origin_path = entry.origin.display_path or entry.origin.path or entry.origin.kind
    rows: list[RenderableType] = [
        _kv("Aliases", aliases),
        _kv("Origin", f"{entry.origin.kind}  {origin_path}"),
    ]
    if entry.origin.xprompt_name:
        rows.append(_kv("Xprompt", entry.origin.xprompt_name))
    return rows


def _kv(label: str, value: str) -> Table:
    table = Table.grid(padding=(0, 2, 0, 0))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")
    table.add_row(label, value)
    return table


def _section(title: str) -> Text:
    return Text(title, style=f"bold {_ACCENT}")


def _source_line(item: SnippetSourceContribution, *, winning: bool) -> Text:
    path = item.display_path or item.path or item.kind
    flags = ["writable" if item.writable else "read-only"]
    flags.append("winning" if winning else "shadowed")
    line = Text()
    line.append(item.kind, style="bold")
    line.append("  ")
    line.append(path, style=PATH_COLOR)
    line.append("  ")
    line.append(" · ".join(flags), style="dim")
    return line


def _markdown_origin(origin: SnippetSourceContribution) -> str:
    path = origin.display_path or origin.path or origin.kind
    writable = "writable" if origin.writable else "read-only"
    return f"{origin.kind} (`{path}`) · {writable}"


def _list_caption(
    entries: tuple[SnippetEntry, ...],
    diagnostics: tuple[SnippetLayerDiagnostic, ...],
) -> str:
    noun = "snippet" if len(entries) == 1 else "snippets"
    caption = f"{len(entries)} {noun}"
    if diagnostics:
        caption += f" · {len(diagnostics)} source diagnostic"
        if len(diagnostics) != 1:
            caption += "s"
    return caption


def _revealed_label(outcome: SnippetMutationOutcome) -> str:
    revealed = outcome.revealed
    if revealed is None:
        return "(none)"
    origin = revealed.origin
    path = origin.display_path or origin.path or origin.kind
    return f"{origin.kind}  {path}"


def _rstrip_output_lines(text: str) -> str:
    if not text:
        return text
    stripped = "\n".join(line.rstrip() for line in text.splitlines())
    if text.endswith("\n"):
        return stripped + "\n"
    return stripped


__all__ = [
    "build_list_table",
    "build_write_table",
    "print_rich",
    "show_markdown",
    "show_renderable",
]
