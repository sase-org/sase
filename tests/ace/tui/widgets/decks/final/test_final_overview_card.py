"""Overview-card coverage for the ⊛ FINAL deck (epic sase-1b2, bead sase-1b2.15).

Renderer unit tests per state and width (120/80/60 columns), plus the
secrecy rule: no config values reach the card.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.decks.final.document import (
    FINAL_OVERVIEW_CARD_ID,
    build_final_deck_document,
)
from sase.ace.tui.widgets.decks.final.overview_card import (
    OVERVIEW_FOOTER,
    _format_overview_duration,
    render_overview_lines,
)


def _attempt(n: int, status: str, seconds: float | None = 120.0) -> SimpleNamespace:
    return SimpleNamespace(attempt=n, status=status, duration_seconds=seconds)


def _run_instance(
    instance_id: str, status: str, *, seconds: float | None = 120.0, **extra: object
) -> SimpleNamespace:
    payload = {
        "instance_id": instance_id,
        "status": status,
        "after": [],
        "waiting_on": None,
        "blocked_by": None,
        "attempts": [_attempt(1, status, seconds)] if seconds is not None else [],
    }
    payload.update(extra)
    return SimpleNamespace(**payload)


def _run(
    label: str,
    disposition: str,
    *,
    cycles: int = 1,
    instances: list | None = None,
    declarations: list | None = None,
    drift: list | None = None,
    diagnostics: list | None = None,
    reason: str | None = None,
    plan_digest: str | None = None,
    result_status: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=label,
        number=0,
        label=label,
        kind="agent",
        disposition=disposition,
        cycles=cycles,
        earlier_segments=0,
        reactivated=False,
        declarations=declarations or [],
        drift=drift or [],
        diagnostics=diagnostics or [],
        instances=instances or [],
        reason=reason,
        plan_digest=plan_digest,
        result_status=result_status,
        recovery_turn=None,
    )


def _node(
    instances: list | None = None,
    runs: list | None = None,
    *,
    status: str = "failed",
    glyph: str = "✗",
    unselected: list | None = None,
    trouble: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        glyph=glyph,
        run_level_trouble=trouble,
        instances=instances or [],
        unselected=unselected or [],
        runs=runs or [],
        attention_instance_id=None,
    )


def _planFailed() -> SimpleNamespace:
    return _node(
        instances=[
            SimpleNamespace(
                instance_id="commit",
                selection_reason="default",
                status="success",
                provider_ref="builtin@commit",
                after=[],
                appearances=[],
            ),
            SimpleNamespace(
                instance_id="check",
                selection_reason="%final:check",
                status="failed",
                provider_ref="builtin@command",
                after=["commit"],
                appearances=[],
            ),
            SimpleNamespace(
                instance_id="tasks",
                selection_reason="default",
                status="not_run",
                provider_ref="builtin@tasks",
                after=[],
                appearances=[],
            ),
        ],
        unselected=[
            SimpleNamespace(
                instance_id="lint",
                reason="%final:!lint",
                provider_ref="builtin@command",
            )
        ],
        runs=[
            _run(
                "--code",
                "ran",
                plan_digest="84a91c2d99",
                result_status="failed",
                instances=[
                    _run_instance("commit", "success", seconds=124.0),
                    _run_instance("check", "failed", seconds=220.0),
                    _run_instance("tasks", "not_run", seconds=None, blocked_by="check"),
                ],
                declarations=[
                    SimpleNamespace(
                        status="rejected",
                        t=1727440258.0,
                        code="commit_bead_action_invalid",
                        first_line="bead_action is required when a bead is assigned",
                        payload_count=None,
                    ),
                    SimpleNamespace(
                        status="accepted",
                        t=1727440265.0,
                        code=None,
                        first_line=None,
                        payload_count=2,
                    ),
                ],
            )
        ],
    )


def _plain(lines: list) -> list[str]:
    return [line.plain for line in lines]


# -- Durations -----------------------------------------------------------


def test_format_overview_duration_matches_mockup() -> None:
    assert _format_overview_duration(362.0) == "6m02s"
    assert _format_overview_duration(124.0) == "2m04s"
    assert _format_overview_duration(220.0) == "3m40s"
    assert _format_overview_duration(12.3) == "12.3s"


# -- Header and plan rows -----------------------------------------------


def test_header_shows_selection_status_and_plan_digest() -> None:
    lines = _plain(render_overview_lines(_planFailed()))
    assert lines[0].startswith("OVERVIEW")
    assert "3 selected" in lines[0]
    assert "✗" in lines[0] and "failed" in lines[0]
    assert "plan 84a91c2d" in lines[0]
    assert "5m44s" in lines[0]


def test_plan_rows_show_reasons_after_and_blockers() -> None:
    text = "\n".join(_plain(render_overview_lines(_planFailed())))
    assert "✓ commit" in text
    assert "builtin@commit" in text
    assert "✗ check" in text
    assert "%final:check · after commit" in text
    assert "not run (blocked by check)" in text


def test_unselected_rows_are_dimmed() -> None:
    lines = render_overview_lines(_planFailed())
    lint = next(line for line in lines if "lint" in line.plain)
    assert "configured · not selected (%final:!lint)" in lint.plain
    assert "dim" in str(lint.style)


# -- Declaration timeline ------------------------------------------------


def test_declaration_timeline_renders_status_code_and_payloads() -> None:
    text = "\n".join(_plain(render_overview_lines(_planFailed())))
    assert "DECLARATION" in text
    assert "✗ rejected" in text
    assert "commit_bead_action_invalid" in text
    assert "bead_action is required" in text
    assert "✓ accepted" in text
    assert "2 payloads" in text


# -- Controller, drift, diagnostics --------------------------------------


def test_controller_hidden_for_single_cycle() -> None:
    text = "\n".join(_plain(render_overview_lines(_planFailed())))
    assert "CONTROLLER" not in text


def test_controller_shown_above_one_cycle() -> None:
    node = _planFailed()
    node.runs[0].cycles = 2
    lines = _plain(render_overview_lines(node))
    text = "\n".join(lines)
    assert "CONTROLLER" in text
    assert "2 cycles" in text
    assert "2 cycles" in lines[0]


def test_drift_and_run_diagnostics_render() -> None:
    node = _planFailed()
    node.runs[0].drift = [
        SimpleNamespace(
            message="config drifted since this plan was sealed: check.max_attempts 2 → 3",
            instance_id="check",
            code="drift",
        )
    ]
    node.runs[0].diagnostics = [
        SimpleNamespace(code="command_failed", message="exit 1", severity="error")
    ]
    text = "\n".join(_plain(render_overview_lines(node)))
    assert "⚠ config drifted" in text
    assert "command_failed exit 1" in text


# -- Runs ledger ----------------------------------------------------------


def test_runs_ledger_hidden_for_lone_ran_run() -> None:
    lines = render_overview_lines(_planFailed())
    assert not any(line.plain.startswith("RUNS") for line in lines)


def test_runs_ledger_lists_every_run() -> None:
    node = _planFailed()
    node.runs.append(
        _run("--plan", "skipped", reason="skipped · handoff:plan", instances=[])
    )
    lines = render_overview_lines(node)
    ledger = next(line for line in lines if line.plain.startswith("RUNS"))
    assert "--plan ○ skipped · plan handoff" in ledger.plain
    assert "--code ✗ failed" in ledger.plain
    calm = "\n".join(_plain(lines))
    assert "its successor lands the work" in calm


def test_skipped_single_run_shows_ledger_and_calm_line() -> None:
    node = _node(
        instances=[],
        runs=[_run("--plan", "skipped", reason="skipped · handoff:plan")],
        status="skipped",
        glyph="○",
    )
    lines = render_overview_lines(node)
    assert any(line.plain.startswith("RUNS") for line in lines)
    assert "its successor lands the work" in "\n".join(_plain(lines))


def test_not_reached_and_unavailable_runs_show_calmly() -> None:
    node = _node(
        instances=[],
        runs=[_run("--code", "not_reached")],
        status="interrupted",
        glyph="!",
    )
    text = "\n".join(_plain(render_overview_lines(node)))
    assert "– not reached" in text
    node2 = _node(
        instances=[],
        runs=[
            _run(
                "--code",
                "unavailable",
                reason="finalizer_plan.json too large",
            )
        ],
        status="unavailable",
        glyph="⚠",
    )
    text2 = "\n".join(_plain(render_overview_lines(node2)))
    assert "⚠ unavailable · finalizer_plan.json too large" in text2


# -- Footer ---------------------------------------------------------------


def test_footer_points_at_cli() -> None:
    lines = render_overview_lines(_planFailed())
    assert lines[-1].plain == OVERVIEW_FOOTER
    assert "sase final status" in lines[-1].plain


# -- Width tiers ------------------------------------------------------------


@pytest.mark.parametrize("width", [120, 80, 60])
def test_every_line_fits_width_tiers(width: int) -> None:
    node = _planFailed()
    node.runs[0].cycles = 3
    node.runs[0].reactivated = True
    node.runs[0].drift = [
        SimpleNamespace(
            message="config drifted since this plan was sealed: " + "x" * 200,
            instance_id=None,
            code=None,
        )
    ]
    node.runs.append(_run("--plan", "skipped", reason="skipped · handoff:plan"))
    for line in render_overview_lines(node, width=width):
        assert len(line.plain) <= width, line.plain


# -- Secrecy -----------------------------------------------------------------


def test_no_config_values_reach_the_card() -> None:
    """Payload summaries and argv never render on the Overview card."""
    secret = "super-secret-token-abc123"
    node = _planFailed()
    run_instance = node.runs[0].instances[0]
    run_instance.payload_summary = {"token": secret}
    run_instance.operations = [
        SimpleNamespace(
            op="command",
            argv=["--token", secret],
            label="check",
            kind="subprocess",
            returncode=1,
            duration_seconds=3.0,
            timed_out=False,
            logs=[],
            steps=[],
        )
    ]
    text = "\n".join(_plain(render_overview_lines(node)))
    assert secret not in text


# -- Document wiring ------------------------------------------------------------


def test_document_overview_card_uses_renderer() -> None:
    document = build_final_deck_document(_planFailed(), subject="agent:1", digest="s")
    overview = document.card(FINAL_OVERVIEW_CARD_ID)
    assert overview is not None
    assert overview.title == "Overview"
    body = "\n".join(part.plain for part in overview.preamble if hasattr(part, "plain"))
    assert "OVERVIEW" in body
    assert "sase final status" in body
