"""Rich renderers for ``sase plan show``.

``full`` and ``compact`` share the exact palette and row styling the ACE TUI's
PLAN lane uses (:mod:`sase.sdd.plan_display`) so the two surfaces read as one
visual family; ``compact`` matches the row :mod:`sase.main.plan_search_render`
prints for the same plan. ``json``/``raw`` are handled directly by
:mod:`sase.main.plan_show_handler` and never reach this module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO, cast

from rich.console import Console, Group, RenderableType
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sase import plan_style
from sase.cli_show_palette import SECTION_COLOR
from sase.markdown_wrap import wrap_markdown
from sase.phase_size_presentation import (
    PHASE_SIZE_CHIP_WIDTH,
    PhaseSizeValue,
    normalize_phase_size,
    phase_size_chip,
)
from sase.plan_show.model import (
    PlanShowAmbiguity,
    PlanShowMiss,
    PlanShowPlan,
    PlanShowProposal,
    PlanShowRecord,
)
from sase.sdd.plan_display import (
    COLOR_PLAN_EMPTY,
    COLOR_PLAN_PATH,
    COLOR_PLAN_PRIMARY,
    COLOR_PLAN_REASON,
    COLOR_PLAN_SUMMARY,
    PLAN_SIZE_ROW_LABEL,
    PlanDisplay,
    PlanDisplayPhase,
    plan_field_rows,
    plan_phase_metadata,
    plan_provenance_rows,
)

_LABEL_WIDTH = 12
_TITLE_STYLE = "bold"
_LEGACY_TALE_LAUNCH_SIZE = "medium"


# --- PlanDisplay adapter ---------------------------------------------------


def _plan_display(record: PlanShowRecord) -> PlanDisplay:
    """Bridge a show record into the value the TUI PLAN-lane renderers take."""
    plan = record.plan
    size, size_defaulted = _plan_size(plan)
    phases = tuple(
        PlanDisplayPhase(
            id=phase.id,
            title=phase.title,
            depends_on=phase.depends_on,
            description=phase.description,
            size=cast(Any, phase.size),
            model=phase.model,
        )
        for phase in plan.phases
    )
    if plan.tier != "epic":
        phase_availability = "not-applicable"
    elif plan.phases:
        phase_availability = "available"
    else:
        phase_availability = "unavailable"
    provenance = cast(
        Any,
        tuple(
            _ProvenanceRow(
                kind=section.kind,
                entries=section.entries,
                targets=section.targets,
                omitted=section.omitted,
            )
            for section in plan.provenance
        ),
    )
    return PlanDisplay(
        title=plan.title,
        goal=plan.goal,
        authored_tier=cast(Any, plan.tier),
        effective_tier=cast(Any, plan.tier),
        actual_path=plan.path,
        display_path=plan.relpath,
        committed=plan.source != "file",
        exists=plan.exists,
        readable=True,
        frontmatter_readable=True,
        phase_availability=cast(Any, phase_availability),
        phases=phases,
        validation_ok=plan.validation.ok,
        validation_diagnostics=plan.validation.diagnostics,
        provenance=provenance,
        size=size,
        size_defaulted=size_defaulted,
    )


def _plan_size(plan: PlanShowPlan) -> tuple[PhaseSizeValue | None, bool]:
    if plan.tier != "tale":
        return None, False
    size = normalize_phase_size(plan.frontmatter.get("size"))
    if size is not None or "size" in plan.frontmatter:
        return size, False
    if plan.validation.ok:
        return normalize_phase_size(_LEGACY_TALE_LAUNCH_SIZE), True
    return None, False


class _ProvenanceRow:
    """Structurally matches the private ``PlanProvenanceSection`` shape."""

    __slots__ = ("entries", "kind", "omitted", "targets")

    def __init__(
        self,
        *,
        kind: str,
        entries: tuple[str, ...],
        targets: tuple[str | None, ...],
        omitted: int,
    ) -> None:
        self.kind = kind
        self.entries = entries
        self.targets = targets
        self.omitted = omitted


# --- full -------------------------------------------------------------------


def render_full(record: PlanShowRecord, *, console: Console, wrap: int | None) -> None:
    """Render the complete section-structured detail view."""
    console.print(_header(record))
    if record.proposal is not None:
        _print_section(console, "PROPOSAL", _proposal_table(record.proposal))
    _print_section(console, "PROPERTIES", _properties(record))
    if record.plan.provenance:
        _print_section(console, "PROVENANCE", _provenance(record))
    if not record.plan.validation.ok:
        _print_section(console, "DIAGNOSTICS", _diagnostics(record, wrap=wrap))
    if record.plan.tier == "epic":
        _print_section(console, _phases_title(record), _phases(record, wrap=wrap))
    if record.plan.body.strip():
        _print_section(console, "BODY", _body(record))
    console.print()
    console.print(_hint(record))


def _header(record: PlanShowRecord) -> RenderableType:
    plan = record.plan
    table = Table.grid(expand=True, padding=0)
    table.add_column(ratio=1, overflow="fold")
    table.add_column(justify="right", no_wrap=True)
    title = Text(plan.title or "(untitled)", style=COLOR_PLAN_PRIMARY)
    table.add_row(title, Text(" · ".join(_header_chips(record)), style="dim"))
    rows: list[RenderableType] = [table]
    if plan.goal:
        rows.append(
            Text(plan.goal, style=COLOR_PLAN_REASON, overflow="fold", no_wrap=False)
        )
    return Group(*rows)


def _header_chips(record: PlanShowRecord) -> list[str]:
    plan = record.plan
    chips = [plan.tier or "tier unavailable"]
    if plan.status:
        chips.append(plan.status)
    if plan.tier == "epic":
        chips.append(f"{len(plan.phases)} phases")
    if record.target.status == "drifted":
        chips.append("drifted")
    if not plan.exists:
        chips.append("missing")
    if not plan.validation.ok:
        chips.append("invalid")
    return chips


def _proposal_table(proposal: PlanShowProposal) -> Table:
    table = _detail_table()
    _add_row(table, "id", proposal.id_prefix)
    _add_row(table, "agent", proposal.agent)
    _add_row(table, "project", proposal.project)
    _add_row(table, "model", proposal.provider_model)
    _add_row(table, "age", proposal.age)
    _add_row(table, "response dir", proposal.response_dir)
    return table


def _properties(record: PlanShowRecord) -> Table:
    plan = record.plan
    field_rows = plan_field_rows(_plan_display(record))
    field_values = dict(field_rows)
    table = _detail_table()
    _add_row(
        table, "reference", Text(plan.reference or "(none)", style=COLOR_PLAN_PATH)
    )
    table.add_row("", "title", field_values["  Title: "])
    table.add_row("", "goal", field_values["   Goal: "])
    size_value = field_values.get(PLAN_SIZE_ROW_LABEL)
    if size_value is not None:
        table.add_row("", "size", size_value)
    _add_row(table, "tier", plan.tier or "unavailable")
    _add_row(table, "status", plan.status or "-")
    _add_row(table, "created", plan.created_at or "-")
    _add_row(table, "source", plan.source)
    table.add_row("", "path", field_rows[-1][1])
    table.add_row("", "matched", _matched_text(record))
    table.add_row("", "validation", _validation_text(record))
    return table


def _matched_text(record: PlanShowRecord) -> Text:
    target = record.target
    text = Text(target.kind, style=COLOR_PLAN_SUMMARY)
    if target.status == "drifted":
        detail = _drift_detail(target.raw, record.plan.relpath)
        text.append(
            f" ({detail})" if detail else " (month drift)", style=COLOR_PLAN_EMPTY
        )
    return text


def _drift_detail(raw: str | None, relpath: str) -> str | None:
    authored = _month_token(raw or "")
    found = _month_token(relpath)
    if authored and found and authored != found:
        return f"month drift: authored {authored}, found {found}"
    return None


def _month_token(value: str) -> str | None:
    for part in value.replace("\\", "/").split("/"):
        if len(part) == 6 and part.isdigit():
            return part
    return None


def _validation_text(record: PlanShowRecord) -> Text:
    validation = record.plan.validation
    if validation.ok:
        return Text("ok", style="green")
    count = len(validation.diagnostics)
    suffix = "issue" if count == 1 else "issues"
    return Text(f"invalid ({count} {suffix})", style="#FF8787")


def _provenance(record: PlanShowRecord) -> RenderableType:
    rows = [
        _labeled_line(label.strip().rstrip(":"), value)
        for label, value in plan_provenance_rows(_plan_display(record))
    ]
    return Group(*rows)


def _diagnostics(record: PlanShowRecord, *, wrap: int | None) -> RenderableType:
    rows = []
    for diagnostic in record.plan.validation.diagnostics:
        stripped = diagnostic.strip()
        text = wrap_markdown(stripped, width=wrap) if wrap else stripped
        for line in text.split("\n"):
            rows.append(Text(f"  {line}", style=COLOR_PLAN_REASON, overflow="fold"))
    return Group(*rows)


def _phases_title(record: PlanShowRecord) -> str:
    plan = record.plan
    if not plan.phases:
        return "PHASES"
    waves = len(plan.waves) if plan.waves is not None else 0
    wave_label = "wave" if waves == 1 else "waves"
    phase_label = "phase" if len(plan.phases) == 1 else "phases"
    return f"PHASES  {len(plan.phases)} {phase_label} · {waves} {wave_label}"


def _phases(record: PlanShowRecord, *, wrap: int | None) -> RenderableType:
    plan = record.plan
    if not plan.phases:
        return Text("phases unavailable", style=COLOR_PLAN_EMPTY)
    display_phases = _plan_display(record).phases
    rows: list[RenderableType] = []
    for ordinal, phase in enumerate(display_phases, start=1):
        title = Text()
        title.append(f"  {ordinal} ", style=COLOR_PLAN_SUMMARY)
        title.append("◆ ", style=COLOR_PLAN_PRIMARY)
        title.append(phase.title, style=COLOR_PLAN_PRIMARY)
        title.append_text(phase_size_chip(phase.size, width=PHASE_SIZE_CHIP_WIDTH))
        rows.append(title)
        meta = Text("    ")
        meta.append_text(plan_phase_metadata(phase))
        rows.append(meta)
        description = phase.description.strip() if phase.description else ""
        if description:
            if wrap:
                description = wrap_markdown(description, width=max(wrap - 4, 1))
            for line in description.split("\n"):
                rows.append(
                    Text(f"    {line}", style=COLOR_PLAN_REASON, overflow="fold")
                )
    return Group(*rows)


def _body(record: PlanShowRecord) -> RenderableType:
    return Syntax(
        record.plan.body, "markdown", word_wrap=True, background_color="default"
    )


def _hint(record: PlanShowRecord) -> Text:
    style = "dim"
    if record.proposal is not None:
        prefix = record.proposal.id_prefix
        text = Text("  ", style=style)
        text.append(f"sase plan approve {prefix}", style=style)
        text.append("   ", style=style)
        text.append(f"sase plan reject {prefix}", style=style)
        return text
    text = Text("  ", style=style)
    text.append(f"sase plan validate {record.plan.path}", style=style)
    return text


def _labeled_line(label: str, value: Text) -> Text:
    line = Text(f"  {label}: ", style=COLOR_PLAN_SUMMARY)
    line.append_text(value)
    return line


def _print_section(console: Console, title: str, body: RenderableType) -> None:
    console.print(Rule(style="dim"))
    console.print(Text(title, style=f"bold {SECTION_COLOR}"))
    console.print(body)


def _detail_table() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(width=2)
    table.add_column(width=_LABEL_WIDTH, style="dim", no_wrap=True)
    table.add_column(overflow="fold")
    return table


def _add_row(table: Table, label: str, value: str | Text) -> None:
    table.add_row("", label, value if isinstance(value, Text) else Text(value))


# --- compact -----------------------------------------------------------------


def render_compact(record: PlanShowRecord, *, console: Console) -> None:
    """Render the same single-row shape ``sase plan search --format compact``
    prints for this plan, so the two subcommands stay pixel-consistent."""
    console.print(_compact_text(record))


def _compact_text(record: PlanShowRecord) -> Text:
    plan = record.plan
    text = Text("  ")
    status = plan.status or ""
    text.append(plan_style.status_icon(status), style=plan_style.status_style(status))
    text.append(" ")
    kind = _compact_kind(plan)
    text.append(kind, style=plan_style.kind_style(kind))
    text.append("  ")
    text.append(_compact_display_path(plan))
    text.append("  ")
    text.append(plan.title or Path(plan.path).stem, style=_TITLE_STYLE)
    return text


def _compact_kind(plan: PlanShowPlan) -> str:
    if plan.source == "local":
        return "local"
    return plan.tier or "file"


def _compact_display_path(plan: PlanShowPlan) -> str:
    return plan.relpath.removesuffix(".md")


# --- miss / ambiguity ---------------------------------------------------


def print_miss(miss: PlanShowMiss, *, file: TextIO | None = None) -> None:
    """Print the ``sase xprompt show``-shaped miss to stderr (or *file*)."""
    out = file or sys.stderr
    header = miss.reason if miss.reason is not None else f"unknown plan: {miss.target}"
    print(header, file=out)
    if not miss.suggestions:
        return
    print("suggestions:", file=out)
    for suggestion in miss.suggestions:
        print(f"  {suggestion}", file=out)


def print_ambiguity(
    ambiguity: PlanShowAmbiguity, *, file: TextIO | None = None
) -> None:
    """Print every candidate plan an ambiguous target matched."""
    out = file or sys.stderr
    count = len(ambiguity.candidates)
    print(f"ambiguous plan: {ambiguity.target} — {count} plans match", file=out)
    width = max((len(c.reference) for c in ambiguity.candidates), default=0)
    for candidate in ambiguity.candidates:
        tier = candidate.tier or "-"
        created = candidate.created_at or "-"
        title = candidate.title or "-"
        print(
            f"  {candidate.reference.ljust(width)}  {tier}  {created}  {title}",
            file=out,
        )
    print(
        "pass one of the references above, or narrow with --target",
        file=out,
    )


__all__ = [
    "print_ambiguity",
    "print_miss",
    "render_compact",
    "render_full",
]
