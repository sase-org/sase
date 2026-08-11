"""Rich detail renderer for ``sase xprompt show``."""

from __future__ import annotations

from collections.abc import Mapping
import json

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.xprompt.cli_show_body import body_block, highlighted_body, syntax_body
from sase.xprompt.cli_show_model import (
    ShowInput,
    ShowReference,
    ShowStep,
    XPromptShowRecord,
)
from sase.xprompt.highlight import XPromptHighlightRole
from sase.xprompt.highlight_theme import HighlightStyle, highlight_theme

_LABEL_WIDTH = 12
_STEP_BODY_LIMIT = 20


def render_show(record: XPromptShowRecord, *, console: Console) -> None:
    """Render the complete human-facing view of one show record."""
    styles_enabled = not bool(console.no_color)
    known_skills = frozenset(
        reference.name for reference in record.references if reference.kind == "skill"
    )
    console.print(_header(record, styles_enabled=styles_enabled))
    if record.description:
        console.print(Text(record.description, overflow="fold", no_wrap=False))

    _print_section(
        console,
        _section_title("PROPERTIES", styles_enabled=styles_enabled),
        _properties(record, styles_enabled=styles_enabled),
        styles_enabled=styles_enabled,
    )
    if record.inputs:
        _print_section(
            console,
            _inputs_title(record, styles_enabled=styles_enabled),
            _inputs(record.inputs, styles_enabled=styles_enabled),
            styles_enabled=styles_enabled,
        )
    if record.local_xprompts:
        _print_section(
            console,
            _section_title("LOCAL XPROMPTS", styles_enabled=styles_enabled),
            _local_xprompts(record, styles_enabled=styles_enabled),
            styles_enabled=styles_enabled,
        )
    if record.steps:
        _print_section(
            console,
            _section_title("WORKFLOW STEPS", styles_enabled=styles_enabled),
            _workflow_steps(
                record.steps,
                known_skills=known_skills,
                styles_enabled=styles_enabled,
            ),
            styles_enabled=styles_enabled,
        )
    if record.body is not None:
        _print_section(
            console,
            _definition_title(record, styles_enabled=styles_enabled),
            body_block(
                record.body,
                first_line=record.body_first_line,
                known_skills=known_skills,
                styles_enabled=styles_enabled,
            ),
            styles_enabled=styles_enabled,
        )
    if record.references:
        _print_section(
            console,
            _section_title("REFERENCES", styles_enabled=styles_enabled),
            _references(record.references, styles_enabled=styles_enabled),
            styles_enabled=styles_enabled,
        )
    if record.warnings:
        _print_section(
            console,
            _section_title("WARNINGS", styles_enabled=styles_enabled),
            Group(*(Text(f"  {warning}") for warning in record.warnings)),
            styles_enabled=styles_enabled,
        )

    console.print()
    console.print(_hint(record, styles_enabled=styles_enabled))


def _header(record: XPromptShowRecord, *, styles_enabled: bool) -> Table:
    table = Table.grid(expand=True, padding=0)
    table.add_column(ratio=1, overflow="fold")
    table.add_column(justify="right", no_wrap=True)
    reference = Text(
        record.reference,
        style=_role_style("xprompt.invocation", styles_enabled=styles_enabled),
    )
    if record.kind == "memory" and record.memory_type is not None:
        chips = [f"memory · {record.memory_type}"]
    else:
        chips = [record.kind.replace("_", " ")]
    if record.is_skill:
        chips.append(f"skill · /{record.skill_name}" if record.skill_name else "skill")
    if record.is_swarm:
        chips.append(f"swarm · {record.segment_count} segments")
    if record.steps:
        chips.append(f"{len(record.steps)} steps")
    table.add_row(
        reference,
        Text(" · ".join(chips), style=_style("dim", styles_enabled=styles_enabled)),
    )
    return table


def _properties(record: XPromptShowRecord, *, styles_enabled: bool) -> Table:
    table = _detail_table(styles_enabled=styles_enabled)
    _add_detail_row(table, "reference", Text(record.reference))
    if record.skill_name:
        # The two names are separate: ``#skill/foo`` expands the source that
        # ``/foo`` invokes as an installed agent skill.
        _add_detail_row(
            table,
            "slash",
            Text(
                f"/{record.skill_name}",
                style=_role_style("xprompt.invocation", styles_enabled=styles_enabled),
            ),
        )
    if record.memory_type:
        _add_detail_row(table, "memory type", Text(record.memory_type))
    if record.project:
        _add_detail_row(table, "project", Text(record.project))

    source = Text(record.provenance.source_bucket or "(unknown)")
    if record.provenance.source_display:
        source.append(" · ", style=_style("dim", styles_enabled=styles_enabled))
        source.append(record.provenance.source_display)
    _add_detail_row(table, "source", source)
    _add_detail_row(
        table,
        "definition",
        _path_or_unknown(
            record.provenance.definition_path,
            styles_enabled=styles_enabled,
        ),
    )
    if record.provenance.hosted_url:
        _add_detail_row(
            table,
            "hosted",
            Text(
                record.provenance.hosted_url,
                style=_style(PATH_COLOR, styles_enabled=styles_enabled),
            ),
        )
    if record.tags:
        _add_detail_row(table, "tags", Text(", ".join(record.tags)))
    if record.skill is not None:
        skill_value = (
            ", ".join(record.skill)
            if isinstance(record.skill, list)
            else _yes_no(record.skill)
        )
        _add_detail_row(table, "skill", Text(skill_value))
    if record.snippet is not None:
        _add_detail_row(
            table,
            "snippet",
            Text(
                _yes_no(record.snippet)
                if isinstance(record.snippet, bool)
                else record.snippet
            ),
        )
    if record.log_skill_use is not None:
        _add_detail_row(
            table,
            "log skill use",
            Text(_yes_no(record.log_skill_use)),
        )
    return table


def _inputs_title(record: XPromptShowRecord, *, styles_enabled: bool) -> Text:
    title = _section_title("INPUTS", styles_enabled=styles_enabled)
    title.append("  ")
    title.append(
        record.reference,
        style=_role_style("xprompt.invocation", styles_enabled=styles_enabled),
    )
    if record.input_signature:
        title.append(
            record.input_signature,
            style=_role_style(
                "xprompt.invocation_arg",
                styles_enabled=styles_enabled,
            ),
        )
    return title


def _inputs(
    inputs: list[ShowInput],
    *,
    styles_enabled: bool,
) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(
        style=_role_style(
            "xprompt.invocation_arg",
            styles_enabled=styles_enabled,
        ),
        no_wrap=True,
    )
    table.add_column(no_wrap=True)
    table.add_column(
        style=_style("dim", styles_enabled=styles_enabled),
        no_wrap=True,
    )
    table.add_column(overflow="fold")
    for item in inputs:
        marker = (
            "required"
            if item.required
            else "default"
            if item.default_display is not None
            else "optional"
        )
        detail = Text(item.description or "", overflow="fold", no_wrap=False)
        if item.default_display is not None:
            default = _single_line_default(item.default_display)
            if detail:
                detail.append("\n")
            detail.append(
                f"default: {default}",
                style=_style("dim", styles_enabled=styles_enabled),
            )
        table.add_row(item.name, item.type, marker, detail)
    return Padding(table, (0, 0, 0, 2))


def _local_xprompts(
    record: XPromptShowRecord,
    *,
    styles_enabled: bool,
) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(
        style=_role_style(
            "xprompt.invocation_arg",
            styles_enabled=styles_enabled,
        ),
        no_wrap=True,
    )
    table.add_column(
        style=_style("dim", styles_enabled=styles_enabled),
        no_wrap=True,
    )
    table.add_column(overflow="fold")
    for item in record.local_xprompts:
        reference = item.name if item.name.startswith("#") else f"#{item.name}"
        if item.input_signature:
            reference += item.input_signature
        description = item.description or "(no description)"
        description_style = (
            _style("dim italic", styles_enabled=styles_enabled)
            if item.description is None
            else ""
        )
        table.add_row(
            reference,
            f"{item.line_count} lines",
            Text(description, style=description_style),
        )
    return Padding(table, (0, 0, 0, 2))


def _workflow_steps(
    steps: list[ShowStep],
    *,
    known_skills: frozenset[str],
    styles_enabled: bool,
) -> Group:
    rows: list[RenderableType] = []
    for step in steps:
        heading = Text(
            f"  {step.index:>2}. ",
            style=_style("dim", styles_enabled=styles_enabled),
        )
        heading.append(step.name, style=_style("bold", styles_enabled=styles_enabled))
        heading.append(
            f"  {step.type}",
            style=_role_style("xprompt.directive", styles_enabled=styles_enabled),
        )
        if step.hidden:
            heading.append(
                " · hidden",
                style=_style("dim", styles_enabled=styles_enabled),
            )
        if step.condition:
            heading.append(
                " · if ",
                style=_style("dim", styles_enabled=styles_enabled),
            )
            heading.append(
                step.condition,
                style=_style("italic", styles_enabled=styles_enabled),
            )
        rows.append(heading)

        if step.body is not None:
            body, omitted = _elide_lines(step.body, limit=_STEP_BODY_LIMIT)
            if step.type in {"bash", "python"}:
                rendered = syntax_body(
                    body,
                    step.type,
                    styles_enabled=styles_enabled,
                )
            else:
                rendered = highlighted_body(
                    body,
                    known_skills=known_skills,
                    styles_enabled=styles_enabled,
                )
            rows.append(Padding(rendered, (0, 0, 0, 6)))
            if omitted:
                rows.append(
                    Text(
                        f"      … ({omitted} more lines)",
                        style=_style("dim", styles_enabled=styles_enabled),
                    )
                )
        elif step.label:
            rows.append(
                Text(
                    f"      {step.label}",
                    style=_style("dim", styles_enabled=styles_enabled),
                )
            )

        if step.output_schema:
            schema = json.dumps(step.output_schema, ensure_ascii=False, sort_keys=True)
            rows.append(
                Text(
                    f"      output: {schema}",
                    style=_style("dim", styles_enabled=styles_enabled),
                )
            )
    return Group(*rows)


def _definition_title(record: XPromptShowRecord, *, styles_enabled: bool) -> Text:
    title = _section_title("DEFINITION", styles_enabled=styles_enabled)
    if record.provenance.source_display:
        title.append("  ")
        title.append(
            record.provenance.source_display,
            style=_style(PATH_COLOR, styles_enabled=styles_enabled),
        )
    return title


def _references(
    references: list[ShowReference],
    *,
    styles_enabled: bool,
) -> RenderableType:
    styles = _theme()
    success = styles["xprompt.invocation"].color
    error = styles["alt.error"].color
    table = Table.grid(padding=(0, 2))
    table.add_column(
        style=_role_style("xprompt.invocation", styles_enabled=styles_enabled),
        no_wrap=True,
    )
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(overflow="fold")
    for reference in references:
        kind = reference.kind or (
            "local helper" if reference.name.startswith("_") else "unknown"
        )
        marker = Text(
            "✓" if reference.resolved else "✗",
            style=_style(
                (success if reference.resolved else error) or "",
                styles_enabled=styles_enabled,
            ),
        )
        table.add_row(
            reference.raw_ref,
            kind.replace("_", " "),
            marker,
            reference.source_display or "",
        )
    return Padding(table, (0, 0, 0, 2))


def _hint(record: XPromptShowRecord, *, styles_enabled: bool) -> Text:
    if record.kind in {"xprompt", "memory"}:
        command = f"sase xprompt expand '{record.reference}'"
        explanation = "preview the expansion"
    else:
        command = f"sase xprompt explain {record.name}"
        explanation = "preview the workflow"
    style = _style("dim", styles_enabled=styles_enabled)
    hint = Text("  ", style=style)
    hint.append(command, style=style)
    hint.append(f"   {explanation}", style=style)
    return hint


def _print_section(
    console: Console,
    title: Text,
    body: RenderableType,
    *,
    styles_enabled: bool,
) -> None:
    console.print(Rule(style=_style("dim", styles_enabled=styles_enabled)))
    console.print(title)
    console.print(body)


def _section_title(label: str, *, styles_enabled: bool) -> Text:
    return Text(
        label,
        style=_style(f"bold {SECTION_COLOR}", styles_enabled=styles_enabled),
    )


def _detail_table(*, styles_enabled: bool) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(width=2)
    table.add_column(
        width=_LABEL_WIDTH,
        style=_style("dim", styles_enabled=styles_enabled),
        no_wrap=True,
    )
    table.add_column(overflow="fold")
    return table


def _add_detail_row(table: Table, label: str, value: Text) -> None:
    table.add_row("", label, value)


def _path_or_unknown(value: str | None, *, styles_enabled: bool) -> Text:
    if value is None:
        return Text(
            "(unknown)",
            style=_style("dim italic", styles_enabled=styles_enabled),
        )
    return Text(
        value,
        style=_style(PATH_COLOR, styles_enabled=styles_enabled),
        overflow="fold",
        no_wrap=False,
    )


def _single_line_default(value: str) -> str:
    lines = value.splitlines()
    if not lines:
        return ""
    return lines[0] + (" …" if len(lines) > 1 else "")


def _elide_lines(text: str, *, limit: int) -> tuple[str, int]:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text, 0
    return "\n".join(lines[:limit]), len(lines) - limit


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _role_style(
    role: XPromptHighlightRole,
    *,
    styles_enabled: bool,
) -> str:
    return _theme()[role].rich_style if styles_enabled else ""


def _style(style: str, *, styles_enabled: bool) -> str:
    return style if styles_enabled else ""


def _theme() -> Mapping[XPromptHighlightRole, HighlightStyle]:
    return highlight_theme()


__all__ = ["render_show"]
