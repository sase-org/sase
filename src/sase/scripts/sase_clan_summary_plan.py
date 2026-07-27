"""Render any valid authored plan as a launch-safe Rich clan summary."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import sys

from rich.markup import escape
from rich.text import Text

from sase.scripts._rich_summary import serialize_lines
from sase.sdd.plan_display import (
    COLOR_PLAN_SUMMARY,
    PlanDisplay,
    load_plan_display,
    render_plan_document,
    render_plan_lines,
)
from sase.sdd.plan_refs import (
    resolve_plan_reference,
    workspace_context_for_plan_resolution,
)

PLAN_SUMMARY_WIDTH = 76
PLAN_SUMMARY_MAX_UTF8_BYTES = 30 * 1024
_UNKNOWN_PLAN_REF = "?"


def main(argv: Sequence[str] | None = None) -> int:
    """Print a PLAN-lane summary selected by argv or ``SASE_EPIC_PLAN_REF``."""
    args = list(sys.argv[1:] if argv is None else argv)
    plan_ref = args[0] if args else os.environ.get("SASE_EPIC_PLAN_REF", "")
    plan_ref = plan_ref.strip()
    try:
        if not plan_ref:
            raise ValueError("no plan reference was supplied")
        plan_path = _resolve_plan_reference(plan_ref)
        summary = load_plan_display(
            plan_path,
            display_path=plan_ref,
        )
        if not summary.validation_ok:
            detail = "; ".join(summary.validation_diagnostics)
            raise ValueError(detail or _availability_detail(summary))
        rendered = _render_plan_summary(summary)
    except Exception as exc:
        print(
            f"Unable to load plan clan summary for "
            f"{plan_ref or _UNKNOWN_PLAN_REF!r}: {exc}; using fallback.",
            file=sys.stderr,
        )
        print(_fallback_summary(plan_ref))
        return 0

    print(rendered)
    return 0


def _resolve_plan_reference(plan_ref: str) -> Path:
    workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
    resolution = resolve_plan_reference(
        plan_ref,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )
    if resolution.resolved_path is not None:
        return resolution.resolved_path

    legacy_path = Path(plan_ref).expanduser()
    fallback = (
        legacy_path if legacy_path.is_absolute() else Path.cwd() / legacy_path
    ).resolve(strict=False)
    if fallback.is_file():
        return fallback
    if resolution.status == "ambiguous":
        raise ValueError(f"plan reference is ambiguous: {plan_ref!r}")
    raise ValueError(f"plan reference could not be resolved: {plan_ref!r}")


def _render_plan_summary(summary: PlanDisplay) -> str:
    full = serialize_lines(render_plan_lines(summary, width=PLAN_SUMMARY_WIDTH))
    if len(full.encode("utf-8")) <= PLAN_SUMMARY_MAX_UTF8_BYTES:
        return full

    document = render_plan_document(summary, width=PLAN_SUMMARY_WIDTH)
    intro_markup = serialize_lines(document.intro_lines)
    block_markup = [serialize_lines(block) for block in document.phase_blocks]
    total_blocks = len(block_markup)
    for included in range(total_blocks, -1, -1):
        omitted = total_blocks - included
        omission = _omission_line(omitted).markup
        candidate = _join_markup(
            intro_markup,
            [*block_markup[:included], omission],
        )
        if len(candidate.encode("utf-8")) <= PLAN_SUMMARY_MAX_UTF8_BYTES:
            return candidate

    raise ValueError("plan leading fields exceed the summary byte budget")


def _join_markup(intro: str, blocks: list[str]) -> str:
    return "\n".join([intro, *blocks])


def _omission_line(omitted: int) -> Text:
    suffix = "" if omitted == 1 else "s"
    return Text(
        f"… {omitted} phase block{suffix} omitted to fit summary size",
        style=COLOR_PLAN_SUMMARY,
    )


def _availability_detail(summary: PlanDisplay) -> str:
    if not summary.exists:
        return "plan file does not exist"
    if not summary.readable:
        return "plan file is not readable UTF-8"
    if not summary.frontmatter_readable:
        return "plan frontmatter is unreadable"
    return "plan validation failed"


def _fallback_summary(plan_ref: str) -> str:
    return f"[bold]PLAN {escape(plan_ref or _UNKNOWN_PLAN_REF)}[/]"


if __name__ == "__main__":  # pragma: no cover - console-script convenience
    raise SystemExit(main())


__all__ = [
    "PLAN_SUMMARY_MAX_UTF8_BYTES",
    "PLAN_SUMMARY_WIDTH",
    "main",
]
