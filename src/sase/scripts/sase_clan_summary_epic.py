"""Render a launch-time-stable Rich summary for an epic agent clan."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback
from collections.abc import Iterable
from collections import Counter
from dataclasses import dataclass

from rich.markup import escape
from rich.text import Text

from sase.bead.cli_common import get_read_view, status_icon
from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status
from sase.bead_status_presentation import bead_status_presentation
from sase.bead.sync import bead_refresh_mode, refresh_current_bead_store
from sase.phase_size_presentation import phase_size_chip
from sase.scripts._rich_summary import (
    render_markdown_lines,
    serialize_lines,
    shorten_text,
    visible_width,
)
from sase.sdd.plan_display import (
    COLOR_PLAN_SUMMARY,
    PlanDisplay,
    load_plan_display,
    render_plan_document,
)

_SUMMARY_WIDTH = 76
_SUMMARY_MAX_UTF8_BYTES = 30 * 1024
_GOAL_MAX_LINES = 6
_UNKNOWN_EPIC_ID = "?"

_HEADER_STYLE = "bold #D75FFF"
_GOAL_STYLE = "dim #D7D7FF"
_SECTION_STYLE = "bold #87D7FF"
_MUTED_STYLE = "dim #A8A8A8"


class _MissingEpicError(KeyError):
    """Identify a missing top-level epic without catching later read errors."""


class _PlanReferenceError(ValueError):
    """Report why every already-available plan candidate was unusable."""


@dataclass(frozen=True)
class _EpicSnapshot:
    epic: Issue
    phases: tuple[Issue, ...]
    child_epics: tuple[Issue, ...]


@dataclass(frozen=True)
class _DocumentBlock:
    lines: tuple[Text, ...]
    omission_kind: str | None = None


def main() -> int:
    """Print the epic summary selected by clan identity and authored plan env.

    Plan and bead lookup are intentionally best-effort: agent launch must still
    get a useful clan identity when either source is missing, stale, or unreadable.
    """
    epic_id = os.environ.get("SASE_CLAN_NAME", "").strip()
    plan_ref = os.environ.get("SASE_EPIC_PLAN_REF", "").strip()
    plan_error: Exception | None = None
    if plan_ref:
        try:
            plan = _load_plan_reference(plan_ref)
            rendered = _render_plan_summary(epic_id, plan)
        except Exception as exc:
            plan_error = exc
        else:
            print(rendered)
            return 0

    try:
        snapshot = _load_epic_with_refresh(epic_id)
    except Exception:
        print(
            f"Unable to load epic clan summary for "
            f"{epic_id or _UNKNOWN_EPIC_ID!r}; using fallback.",
            file=sys.stderr,
        )
        if plan_error is not None:
            print(
                f"Plan reference {plan_ref!r} was also unavailable: {plan_error}",
                file=sys.stderr,
            )
        traceback.print_exc(file=sys.stderr)
        print(_fallback_summary(epic_id))
        return 0

    print(
        _render_epic_summary(
            snapshot.epic,
            snapshot.phases,
            snapshot.child_epics,
        )
    )
    return 0


def _load_plan_reference(plan_ref: str) -> PlanDisplay:
    failures: list[str] = []
    snapshot = _configured_plan_snapshot()
    for candidate in _plan_reference_candidates(plan_ref):
        summary = load_plan_display(candidate, display_path=plan_ref)
        if summary.validation_ok:
            return summary
        candidate_label = (
            "epic plan snapshot" if candidate == snapshot else str(candidate)
        )
        failures.append(f"{candidate_label}: {_plan_availability_detail(summary)}")

    detail = "; ".join(failures) or "no plan candidates were available"
    raise _PlanReferenceError(detail)


def _plan_reference_candidates(plan_ref: str) -> Iterable[Path]:
    seen: set[Path] = set()

    def candidate(path: Path) -> Path | None:
        resolved = path.expanduser().resolve(strict=False)
        if resolved in seen:
            return None
        seen.add(resolved)
        return resolved

    expanded = Path(plan_ref).expanduser()
    if expanded.is_absolute():
        resolved = candidate(expanded)
        if resolved is not None:
            yield resolved
    else:
        current = candidate(Path.cwd() / expanded)
        if current is not None:
            yield current

        primary = _resolve_primary_checkout()
        if primary is not None:
            primary_candidate = candidate(primary / expanded)
            if primary_candidate is not None:
                yield primary_candidate

    snapshot = _configured_plan_snapshot()
    if snapshot is not None:
        snapshot_candidate = candidate(snapshot)
        if snapshot_candidate is not None:
            yield snapshot_candidate


def _configured_plan_snapshot() -> Path | None:
    snapshot_ref = os.environ.get("SASE_EPIC_PLAN_SNAPSHOT", "").strip()
    if not snapshot_ref:
        return None
    try:
        snapshot = Path(snapshot_ref).expanduser()
        if not snapshot.is_absolute():
            return None
        return snapshot.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_primary_checkout() -> Path | None:
    """Discover the primary checkout without materializing or refreshing it."""
    from sase.bead.workspace import resolve_primary_workspace

    return resolve_primary_workspace()


def _plan_availability_detail(summary: PlanDisplay) -> str:
    if not summary.exists:
        return "plan file does not exist"
    if not summary.readable:
        return "plan file is not readable UTF-8"
    if not summary.frontmatter_readable:
        return "plan frontmatter is unreadable"
    return "; ".join(summary.validation_diagnostics) or "plan validation failed"


def _render_plan_summary(epic_id: str, summary: PlanDisplay) -> str:
    document = render_plan_document(summary, width=_SUMMARY_WIDTH)
    intro = (
        _plan_header_line(epic_id),
        *document.intro_lines[1:],
    )
    return _fit_plan_document(intro, document.phase_blocks)


def _plan_header_line(epic_id: str) -> Text:
    return shorten_text(
        Text(f"◆ EPIC {epic_id or _UNKNOWN_EPIC_ID}", style=_HEADER_STYLE),
        width=_SUMMARY_WIDTH,
    )


def _fit_plan_document(
    intro: tuple[Text, ...],
    phase_blocks: tuple[tuple[Text, ...], ...],
) -> str:
    intro_markup = serialize_lines(intro)
    block_markup = [serialize_lines(block) for block in phase_blocks]
    full = "\n".join([intro_markup, *block_markup])
    if len(full.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES:
        return full

    total_blocks = len(block_markup)
    for included in range(total_blocks - 1, -1, -1):
        omitted = total_blocks - included
        omission = _plan_omission_line(omitted).markup
        candidate = "\n".join([intro_markup, *block_markup[:included], omission])
        if len(candidate.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES:
            return candidate

    raise ValueError("plan leading fields exceed the summary byte budget")


def _plan_omission_line(omitted: int) -> Text:
    suffix = "" if omitted == 1 else "s"
    return Text(
        f"… {omitted} phase block{suffix} omitted to fit summary size",
        style=COLOR_PLAN_SUMMARY,
    )


def _load_epic_with_refresh(epic_id: str) -> _EpicSnapshot:
    try:
        return _load_epic(epic_id)
    except _MissingEpicError:
        if bead_refresh_mode() == "off":
            raise
        refresh_current_bead_store()
        return _load_epic(epic_id)


def _load_epic(epic_id: str) -> _EpicSnapshot:
    if not epic_id:
        raise ValueError("SASE_CLAN_NAME is empty")

    with get_read_view() as project:
        try:
            epic = project.show(epic_id)
        except KeyError as exc:
            raise _MissingEpicError(epic_id) from exc
        if epic.issue_type is not IssueType.PLAN or epic.tier is not BeadTier.EPIC:
            raise ValueError(f"Bead {epic_id!r} is not an epic plan")
        children = project.get_epic_children(epic.id)
        phases = _ordered_children(
            child for child in children if child.issue_type is IssueType.PHASE
        )
        child_epics = _ordered_children(
            child
            for child in children
            if child.issue_type is IssueType.PLAN and child.tier is BeadTier.EPIC
        )
    return _EpicSnapshot(epic, phases, child_epics)


def _ordered_children(children: Iterable[Issue]) -> tuple[Issue, ...]:
    return tuple(sorted(children, key=lambda child: (child.created_at, child.id)))


def _render_epic_summary(
    epic: Issue,
    phases: tuple[Issue, ...],
    child_epics: tuple[Issue, ...] = (),
) -> str:
    intro = [_header_line(epic)]
    goal = render_markdown_lines(epic.description, width=_SUMMARY_WIDTH).cap(
        _GOAL_MAX_LINES,
        width=_SUMMARY_WIDTH,
    )
    intro.extend(goal.styled(_GOAL_STYLE).lines)
    if goal.lines:
        intro.append(Text())

    closed = sum(phase.status is Status.CLOSED for phase in phases)
    intro.append(
        shorten_text(
            Text(
                f"PHASES · {closed}/{len(phases)} done at launch",
                style=_SECTION_STYLE,
            ),
            width=_SUMMARY_WIDTH,
        )
    )

    blocks = [
        _DocumentBlock(_phase_lines(index, phase), omission_kind="phase")
        for index, phase in enumerate(phases, start=1)
    ]
    for index, child in enumerate(child_epics):
        child_lines: list[Text] = []
        if index == 0:
            child_lines.extend(
                (
                    Text(),
                    Text(
                        f"CHILD EPICS · {len(child_epics)}",
                        style=_SECTION_STYLE,
                    ),
                )
            )
        child_lines.append(_child_epic_line(child))
        blocks.append(_DocumentBlock(tuple(child_lines), omission_kind="child_epic"))

    if epic.design.strip():
        plan = shorten_text(
            Text.assemble(("Plan:", "bold dim"), " ", epic.design.strip()),
            width=_SUMMARY_WIDTH,
        )
        plan.stylize(_MUTED_STYLE, 0, len(plan))
        blocks.append(_DocumentBlock((Text(), plan), omission_kind="plan"))

    return _fit_document(tuple(intro), tuple(blocks))


def _header_line(epic: Issue) -> Text:
    return shorten_text(
        Text(f"◆ EPIC {epic.id} · {epic.title}", style=_HEADER_STYLE),
        width=_SUMMARY_WIDTH,
    )


def _phase_lines(index: int, phase: Issue) -> tuple[Text, ...]:
    size = phase.size or PhaseSize.SMALL
    chip = phase_size_chip(size)
    left_width = max(_SUMMARY_WIDTH - visible_width(chip) - 1, 1)

    left = Text()
    left.append(status_icon(phase.status), style=_status_style(phase.status))
    left.append(f" {index}. ", style=_SECTION_STYLE)
    left.append(phase.title)
    left = shorten_text(left, width=left_width)

    row = left.copy()
    row.append(" " * max(_SUMMARY_WIDTH - visible_width(left) - visible_width(chip), 1))
    row.append_text(chip)
    lines = [row]

    if phase.description.strip():
        description = render_markdown_lines(
            phase.description,
            width=_SUMMARY_WIDTH - 4,
        ).cap(1, width=_SUMMARY_WIDTH - 4)
        if description.lines:
            detail = Text("  └ ", style=_MUTED_STYLE)
            detail.append_text(description.styled(_GOAL_STYLE).lines[0])
            lines.append(shorten_text(detail, width=_SUMMARY_WIDTH))
    return tuple(lines)


def _child_epic_line(child: Issue) -> Text:
    line = Text()
    line.append(status_icon(child.status), style=_status_style(child.status))
    line.append(" ")
    line.append(child.id, style="bold #D75FFF")
    line.append(" · ")
    line.append(child.title)
    return shorten_text(line, width=_SUMMARY_WIDTH)


def _fit_document(
    intro: tuple[Text, ...],
    blocks: tuple[_DocumentBlock, ...],
) -> str:
    intro_markup = serialize_lines(intro)
    block_markup = [serialize_lines(block.lines) for block in blocks]
    full_parts = [intro_markup, *block_markup]
    if _joined_utf8_size(full_parts) <= _SUMMARY_MAX_UTF8_BYTES:
        return "\n".join(full_parts)

    remaining = Counter(
        block.omission_kind for block in blocks if block.omission_kind is not None
    )
    prefix_bytes = len(intro_markup.encode("utf-8"))
    best_count = -1
    best_omission = ""
    for included in range(len(blocks) + 1):
        omission = _omission_line(remaining).markup
        candidate_size = prefix_bytes + 1 + len(omission.encode("utf-8"))
        if candidate_size <= _SUMMARY_MAX_UTF8_BYTES:
            best_count = included
            best_omission = omission
        if included == len(blocks):
            break
        prefix_bytes += 1 + len(block_markup[included].encode("utf-8"))
        kind = blocks[included].omission_kind
        if kind is not None:
            remaining[kind] -= 1

    if best_count < 0:  # The bounded intro is useful even in pathological cases.
        return intro_markup
    return "\n".join([intro_markup, *block_markup[:best_count], best_omission])


def _omission_line(remaining: Counter[str]) -> Text:
    labels: list[str] = []
    phase_count = remaining["phase"]
    child_count = remaining["child_epic"]
    if phase_count:
        labels.append(f"{phase_count} phase entr{'y' if phase_count == 1 else 'ies'}")
    if child_count:
        labels.append(
            f"{child_count} child epic entr{'y' if child_count == 1 else 'ies'}"
        )
    if remaining["plan"]:
        labels.append("plan reference")
    detail = _join_labels(labels) or "trailing content"
    return shorten_text(
        Text(f"… {detail} omitted to fit summary size", style=_MUTED_STYLE),
        width=_SUMMARY_WIDTH,
    )


def _join_labels(labels: list[str]) -> str:
    if len(labels) < 2:
        return "".join(labels)
    if len(labels) == 2:
        return " and ".join(labels)
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _joined_utf8_size(parts: list[str]) -> int:
    return sum(len(part.encode("utf-8")) for part in parts) + max(len(parts) - 1, 0)


def _status_style(status: Status) -> str:
    return bead_status_presentation(status).rich_style


def _fallback_summary(epic_id: str) -> str:
    return f"[bold]EPIC {escape(epic_id or _UNKNOWN_EPIC_ID)}[/]"


if __name__ == "__main__":  # pragma: no cover - console-script convenience
    raise SystemExit(main())
