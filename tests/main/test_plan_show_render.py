"""Tests for :mod:`sase.main.plan_show_render`."""

from __future__ import annotations

import io

from rich.console import Console

from sase.main.plan_search_render import render as render_search
from sase.main.plan_show_render import (
    print_ambiguity,
    print_miss,
    render_compact,
    render_full,
)
from sase.phase_size_presentation import PHASE_SIZE_DEFAULT_MARKER
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.plan_show.model import (
    PlanShowAmbiguity,
    PlanShowAmbiguityCandidate,
    PlanShowMiss,
    PlanShowPhase,
    PlanShowPlan,
    PlanShowProposal,
    PlanShowRecord,
    PlanShowTarget,
    PlanShowValidation,
)


def _console(color: str, *, width: int = 100) -> tuple[Console, io.StringIO]:
    stream = io.StringIO()
    kwargs: dict[str, object] = {
        "file": stream,
        "width": width,
        "markup": False,
        "emoji": False,
        "highlight": False,
    }
    if color == "always":
        kwargs.update(force_terminal=True, no_color=False, color_system="256")
    else:
        kwargs.update(no_color=True)
    return Console(**kwargs), stream  # type: ignore[arg-type]


def _plan(**overrides: object) -> PlanShowPlan:
    defaults: dict[str, object] = {
        "reference": "plans:202608/a.md",
        "path": "/abs/repo/plans/202608/a.md",
        "relpath": "202608/a.md",
        "source": "repo",
        "exists": True,
        "tier": "tale",
        "status": "wip",
        "title": "A flexible plan",
        "goal": "Deliver the feature end to end.",
        "created_at": "2026-08-06 15:48:40",
        "frontmatter": {"size": "small"},
        "body": "# Heading\n\nSome body text.\n",
        "validation": PlanShowValidation(ok=True, diagnostics=()),
        "provenance": (),
        "phases": (),
        "waves": None,
    }
    defaults.update(overrides)
    return PlanShowPlan(**defaults)  # type: ignore[arg-type]


def _record(**overrides: object) -> PlanShowRecord:
    plan = overrides.pop("plan", None) or _plan()
    target = overrides.pop("target", None) or PlanShowTarget(
        raw="a", kind="path", status="exact"
    )
    proposal = overrides.pop("proposal", None)
    bead = overrides.pop("bead", None)
    assert not overrides
    return PlanShowRecord(target=target, plan=plan, proposal=proposal, bead=bead)  # type: ignore[arg-type]


def _render(
    record: PlanShowRecord, *, color: str = "never", wrap: int | None = None
) -> str:
    console, stream = _console(color)
    render_full(record, console=console, wrap=wrap)
    return stream.getvalue()


def test_full_render_covers_a_tale_in_documented_section_order() -> None:
    record = _record(
        plan=_plan(
            provenance=(),
        )
    )

    rendered = _render(record)

    assert rendered.index("A flexible plan") < rendered.index("PROPERTIES")
    assert "reference" in rendered
    assert "plans:202608/a.md" in rendered
    assert "size" in rendered
    assert "small" in rendered
    assert "tale" in rendered
    assert "wip" in rendered
    assert "PROPOSAL" not in rendered
    assert "PROVENANCE" not in rendered
    assert "DIAGNOSTICS" not in rendered
    assert "PHASES" not in rendered
    assert "BODY" in rendered
    assert "Some body text." in rendered
    assert "sase plan validate" in rendered


def test_full_render_marks_legacy_tale_size_as_defaulted() -> None:
    record = _record(plan=_plan(frontmatter={}))

    rendered = _render(record)

    assert "size" in rendered
    assert "medium" in rendered
    assert PHASE_SIZE_DEFAULT_MARKER in rendered


def test_full_render_marks_legacy_over_sized_tale_size_as_defaulted() -> None:
    record = _record(plan=_plan(frontmatter={"size": "large"}))

    rendered = _render(record)

    assert "size" in rendered
    assert "medium" in rendered
    assert "large" not in rendered
    assert PHASE_SIZE_DEFAULT_MARKER in rendered


def test_full_render_does_not_fabricate_size_for_invalid_sizeless_tale() -> None:
    record = _record(
        plan=_plan(
            frontmatter={},
            validation=PlanShowValidation(ok=False, diagnostics=("bad tale",)),
        )
    )

    rendered = _render(record)

    assert "size" in rendered
    assert "unavailable" in rendered
    assert PHASE_SIZE_DEFAULT_MARKER not in rendered


def test_full_render_covers_an_epic_with_phases_and_waves() -> None:
    phase = PlanShowPhase(
        id="implementation",
        title="Implement the change",
        depends_on=(),
        size="small",
        model=None,
        description="Ship it.",
    )
    record = _record(
        plan=_plan(
            tier="epic",
            phases=(phase,),
            waves=(("implementation",),),
        )
    )

    rendered = _render(record)

    assert "PHASES" in rendered
    assert "1 phase" in rendered
    assert "1 wave" in rendered
    assert "Implement the change" in rendered
    assert "implementation" in rendered
    assert "Ship it." in rendered


def test_full_render_shows_phases_unavailable_for_broken_epic() -> None:
    record = _record(
        plan=_plan(
            tier="epic",
            phases=(),
            waves=None,
            validation=PlanShowValidation(ok=False, diagnostics=("bad phase",)),
        )
    )

    rendered = _render(record)

    assert "PHASES" in rendered
    assert "phases unavailable" in rendered
    assert "DIAGNOSTICS" in rendered
    assert "bad phase" in rendered
    assert "invalid" in rendered


def test_full_render_shows_proposal_section_when_resolved_via_proposal() -> None:
    record = _record(
        target=PlanShowTarget(raw=None, kind="proposal", status="exact"),
        proposal=PlanShowProposal(
            id="abcdef120001",
            id_prefix="abcdef12",
            agent="planner",
            project="sase",
            provider_model="claude",
            age="3m",
            response_dir="~/.sase/agent/x",
        ),
    )

    rendered = _render(record)

    assert rendered.index("PROPOSAL") < rendered.index("PROPERTIES")
    assert "abcdef12" in rendered
    assert "planner" in rendered
    assert "sase plan approve abcdef12" in rendered
    assert "sase plan reject abcdef12" in rendered


def test_full_render_shows_drifted_and_missing_markers() -> None:
    drifted = _record(
        target=PlanShowTarget(raw="plans:202607/a.md", kind="ref", status="drifted"),
        plan=_plan(relpath="202608/a.md"),
    )
    missing = _record(plan=_plan(exists=False))

    drifted_rendered = _render(drifted)
    missing_rendered = _render(missing)

    assert "drifted" in drifted_rendered
    assert "month drift" in drifted_rendered
    assert "missing" in missing_rendered


def test_color_never_has_no_ansi_and_always_does() -> None:
    record = _record()

    never_console, never_stream = _console("never")
    render_full(record, console=never_console, wrap=None)
    always_console, always_stream = _console("always")
    render_full(record, console=always_console, wrap=None)

    assert "\x1b" not in never_stream.getvalue()
    assert "\x1b" in always_stream.getvalue()


def test_wrap_narrows_diagnostics_prose() -> None:
    long_diagnostic = "x " * 80
    record = _record(
        plan=_plan(
            validation=PlanShowValidation(ok=False, diagnostics=(long_diagnostic,))
        )
    )

    narrow = _render(record, wrap=30)
    wide = _render(record, wrap=200)

    narrow_lines = [line for line in narrow.splitlines() if "x x" in line]
    wide_lines = [line for line in wide.splitlines() if "x x" in line]
    assert narrow_lines
    assert wide_lines
    assert max(len(line) for line in narrow_lines) < max(
        len(line) for line in wide_lines
    )


def test_compact_row_matches_plan_search_row_for_the_same_plan() -> None:
    record = _record()
    plan = Plan(
        source="repo",
        kind="tale",
        path=record.plan.path,
        relpath="plans/202608/a.md",
        name="a",
        title=record.plan.title or "",
        status=record.plan.status or "",
        created_at="2026-08-06T15:48:40",
        prompt_link="",
        summary="",
        body="",
        frontmatter={},
    )
    match = PlanSearchMatch(plan=plan, matched_fields=[], score=0.0)

    console, stream = _console("never")
    render_compact(record, console=console)
    compact_output = stream.getvalue()

    search_stream = io.StringIO()
    render_search(
        [match],
        query=None,
        fmt="compact",
        color="never",
        sort_label="recent",
        file=search_stream,
    )
    search_output = search_stream.getvalue()

    def _row(text: str) -> str:
        return next(line for line in text.splitlines() if "202608/a" in line)

    assert _row(compact_output).strip() == _row(search_output).strip()


def test_print_miss_uses_reason_when_present() -> None:
    stream = io.StringIO()
    print_miss(PlanShowMiss(target="", reason="no pending plan proposals"), file=stream)

    assert stream.getvalue().splitlines()[0] == "no pending plan proposals"


def test_print_miss_default_shape_with_suggestions() -> None:
    stream = io.StringIO()
    print_miss(
        PlanShowMiss(target="foo", suggestions=("plans:202608/a.md",)), file=stream
    )

    output = stream.getvalue()
    assert "unknown plan: foo" in output
    assert "suggestions:" in output
    assert "plans:202608/a.md" in output


def test_print_miss_omits_suggestions_block_when_empty() -> None:
    stream = io.StringIO()
    print_miss(PlanShowMiss(target="foo"), file=stream)

    assert "suggestions:" not in stream.getvalue()


def test_print_ambiguity_lists_every_candidate() -> None:
    stream = io.StringIO()
    ambiguity = PlanShowAmbiguity(
        target="a",
        candidates=(
            PlanShowAmbiguityCandidate(
                reference="plans:202607/a.md",
                tier="tale",
                created_at="2026-07-01",
                title="A",
            ),
            PlanShowAmbiguityCandidate(
                reference="plans:202608/a.md",
                tier="tale",
                created_at="2026-08-01",
                title="A2",
            ),
        ),
    )

    print_ambiguity(ambiguity, file=stream)

    output = stream.getvalue()
    assert "ambiguous plan: a — 2 plans match" in output
    assert "plans:202607/a.md" in output
    assert "plans:202608/a.md" in output
    assert "narrow with --target" in output
