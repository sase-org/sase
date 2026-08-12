"""Pure Rich renderers for the xprompt properties band and full properties view.

Neither function touches Textual: both take an already-projected
:class:`~sase.xprompt.properties.XPromptProperties` and return a Rich
renderable, so they are unit-testable without an app.
"""

from __future__ import annotations

import textwrap

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import SECTION_COLOR
from sase.xprompt.cli_show_model import ShowInput, ShowLocalXPrompt, ShowStep
from sase.xprompt.highlight import XPromptHighlightRole
from sase.xprompt.highlight_theme import highlight_theme
from sase.xprompt.properties import XPromptProperties, single_line_default

_DEFAULT_MAX_INPUT_ROWS = 6
_DESCRIPTION_MAX_LINES = 2
_DESCRIPTION_WRAP_WIDTH = 88
_ENUM_CHOICE_LIMIT = 3


def build_properties_band(
    properties: XPromptProperties,
    *,
    max_input_rows: int = _DEFAULT_MAX_INPUT_ROWS,
) -> RenderableType | None:
    """Render the compact, always-on properties band, or ``None`` when empty."""
    if properties.is_empty:
        return None

    parts: list[RenderableType] = []
    if properties.description:
        parts.append(_fold_description(properties.description))
    if properties.inputs:
        if parts:
            parts.append(Text(""))
        parts.append(_inputs_table(properties.inputs, max_input_rows=max_input_rows))
    chips = _chips(properties)
    if chips:
        if parts:
            parts.append(Text(""))
        parts.append(Text(chips, style="dim"))
    return Group(*parts)


def build_properties_view(properties: XPromptProperties) -> RenderableType:
    """Render the complete, scrollable properties view: every row, no cap."""
    sections: list[RenderableType] = [_properties_summary(properties)]
    if properties.inputs:
        sections.append(Rule(style="dim"))
        sections.append(_section_title("INPUTS"))
        sections.append(
            _inputs_table(properties.inputs, max_input_rows=len(properties.inputs))
        )
    if properties.local_xprompts:
        sections.append(Rule(style="dim"))
        sections.append(_section_title("LOCAL XPROMPTS"))
        sections.append(_local_xprompts_table(properties.local_xprompts))
    if properties.steps:
        sections.append(Rule(style="dim"))
        sections.append(_section_title("WORKFLOW STEPS"))
        sections.append(_steps_view(properties.steps))
    return Group(*sections)


def _fold_description(description: str) -> Text:
    wrapped = textwrap.wrap(
        " ".join(description.split()),
        width=_DESCRIPTION_WRAP_WIDTH,
    )
    if not wrapped:
        return Text("")
    if len(wrapped) > _DESCRIPTION_MAX_LINES:
        head = wrapped[:_DESCRIPTION_MAX_LINES]
        head[-1] = head[-1].rstrip() + " …"
        wrapped = head
    return Text("\n".join(wrapped), overflow="fold", no_wrap=False)


def _inputs_table(inputs: list[ShowInput], *, max_input_rows: int) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=_role_style("xprompt.invocation_arg"), no_wrap=True)
    table.add_column(style=_role_style("xprompt.directive"), no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(style="dim", overflow="fold")

    shown = inputs
    omitted = 0
    if len(inputs) > max_input_rows:
        shown = inputs[: max(1, max_input_rows - 1)]
        omitted = len(inputs) - len(shown)

    for item in shown:
        name = item.name + ("…" if item.repeatable else "")
        table.add_row(
            name,
            item.type,
            _input_marker(item),
            Text(item.description or "", overflow="fold", no_wrap=False),
        )

    if not omitted:
        return table
    overflow_row = Text(f"… +{omitted} more  ·  p for all properties", style="dim")
    return Group(table, overflow_row)


def _input_marker(item: ShowInput) -> Text:
    if item.type == "enum" and item.choices:
        return Text(_enum_marker(item.choices))
    if item.required:
        return Text("required", style=_role_style("xprompt.directive"))
    if item.default_display is not None:
        return Text(f"default: {single_line_default(item.default_display)}")
    return Text("optional")


def _enum_marker(choices: tuple[str, ...]) -> str:
    shown = choices[:_ENUM_CHOICE_LIMIT]
    suffix = (
        ""
        if len(choices) <= _ENUM_CHOICE_LIMIT
        else f", +{len(choices) - _ENUM_CHOICE_LIMIT} more"
    )
    return "one of: " + ", ".join(shown) + suffix


def _chips(properties: XPromptProperties) -> str:
    chips: list[str] = []
    if properties.source_bucket:
        chips.append(properties.source_bucket)
    if properties.inputs:
        count = len(properties.inputs)
        chips.append(f"{count} input{'' if count == 1 else 's'}")
    if properties.tags:
        chips.append(f"tags: {', '.join(properties.tags)}")
    if isinstance(properties.skill, list):
        chips.append(f"skill: {', '.join(properties.skill)}")
    elif properties.skill:
        chips.append("skill")
    if isinstance(properties.snippet, str):
        chips.append(f"snippet: {properties.snippet}")
    elif properties.snippet:
        chips.append("snippet")
    if properties.memory_type:
        chips.append(f"memory · {properties.memory_type}")
    if properties.local_xprompts:
        count = len(properties.local_xprompts)
        chips.append(f"{count} local xprompt{'' if count == 1 else 's'}")
    if properties.steps:
        count = len(properties.steps)
        chips.append(f"{count} step{'' if count == 1 else 's'}")
    if properties.segment_count > 1:
        chips.append(f"swarm · {properties.segment_count} segments")
    if properties.project:
        chips.append(f"project: {properties.project}")
    return " · ".join(chips)


def _properties_summary(properties: XPromptProperties) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(width=2)
    table.add_column(width=12, style="dim", no_wrap=True)
    table.add_column(overflow="fold")

    def row(label: str, value: RenderableType) -> None:
        table.add_row("", label, value)

    row(
        "reference",
        Text(properties.reference, style=_role_style("xprompt.invocation")),
    )
    row("kind", Text(properties.kind))
    if properties.description:
        row(
            "description",
            Text(properties.description, overflow="fold", no_wrap=False),
        )
    if properties.project:
        row("project", Text(properties.project))
    if properties.source_bucket or properties.definition_path:
        source = Text(properties.source_bucket or "(unknown)")
        if properties.definition_path:
            source.append(" · ", style="dim")
            source.append(properties.definition_path)
        row("source", source)
    if properties.tags:
        row("tags", Text(", ".join(properties.tags)))
    if properties.skill is not None:
        skill_value = (
            ", ".join(properties.skill)
            if isinstance(properties.skill, list)
            else _yes_no(properties.skill)
        )
        row("skill", Text(skill_value))
    if properties.skill_name:
        row(
            "slash",
            Text(
                f"/{properties.skill_name}",
                style=_role_style("xprompt.invocation"),
            ),
        )
    if properties.snippet is not None:
        snippet_value = (
            properties.snippet
            if isinstance(properties.snippet, str)
            else _yes_no(properties.snippet)
        )
        row("snippet", Text(snippet_value))
    if properties.log_skill_use is not None:
        row("log skill use", Text(_yes_no(properties.log_skill_use)))
    if properties.memory_type:
        row("memory type", Text(properties.memory_type))
    if properties.segment_count > 1:
        row("swarm", Text(f"{properties.segment_count} segments"))
    return table


def _local_xprompts_table(items: list[ShowLocalXPrompt]) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=_role_style("xprompt.invocation_arg"), no_wrap=True)
    table.add_column(style="dim", no_wrap=True)
    table.add_column(overflow="fold")
    for item in items:
        reference = item.name if item.name.startswith("#") else f"#{item.name}"
        if item.input_signature:
            reference += item.input_signature
        description = item.description or "(no description)"
        table.add_row(reference, f"{item.line_count} lines", description)
    return table


def _steps_view(steps: list[ShowStep]) -> RenderableType:
    rows: list[RenderableType] = []
    for step in steps:
        heading = Text(f"  {step.index:>2}. ", style="dim")
        heading.append(step.name, style="bold")
        heading.append(f"  {step.type}", style=_role_style("xprompt.directive"))
        if step.hidden:
            heading.append(" · hidden", style="dim")
        if step.condition:
            heading.append(" · if ", style="dim")
            heading.append(step.condition, style="italic")
        rows.append(heading)
        if step.label:
            rows.append(Text(f"      {step.label}", style="dim"))
    return Group(*rows)


def _section_title(label: str) -> Text:
    return Text(label, style=f"bold {SECTION_COLOR}")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _role_style(role: XPromptHighlightRole) -> str:
    return highlight_theme()[role].rich_style


__all__ = ["build_properties_band", "build_properties_view"]
