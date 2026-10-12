"""Plan decision rail layout: widths, narrow dock, and compact verdict."""

from __future__ import annotations

from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_compact_verdict_stays_inside_rail_with_stylesheet",
    "test_decision_rail_widths_and_narrow_dock",
    "test_generic_gate_rail_stays_42_with_stylesheet",
]


async def test_compact_verdict_stays_inside_rail_with_stylesheet(tmp_path) -> None:
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import Vertical as _V
    from textual.containers import VerticalScroll as _VS

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "rail_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    for choice in ("tale", "epic"):
        for with_decisions in (True, False):
            defs = plan_decision_definitions(tmp_path) if with_decisions else []
            for width, height in ((120, 40), (90, 40)):
                modal = _Modal(
                    str(plan),
                    default_choice=choice,  # type: ignore[arg-type]
                    plan_content="# Plan\n",
                    decision_definitions=list(defs),
                    review_revision=3,
                    request_id=f"req-rail-{choice}-{with_decisions}-{width}",
                )
                async with _StyledApp().run_test(size=(width, height)) as pilot:
                    pilot.app.push_screen(modal)
                    await pilot.pause()
                    await pilot.pause()
                    # Decision rails are a plain Vertical (pinned cards);
                    # decision-free rails keep the scrolling container.
                    rail = modal.query_one(
                        ".gate-review-actions", _V if with_decisions else _VS
                    )
                    content = rail.content_region
                    for btn in modal.query("#plan-verdict GateControlButton"):
                        assert content.contains_region(btn.region), (
                            choice,
                            with_decisions,
                            width,
                            btn.id,
                            btn.region,
                            content,
                        )
                    line2 = modal.query_one("#plan-verdict-line2")
                    line2_labels = " ".join(
                        str(b.label) for b in line2.query("GateControlButton")
                    )
                    if choice == "tale":
                        line1 = modal.query_one("#plan-verdict-line1")
                        labels1 = " ".join(
                            str(b.label) for b in line1.query("GateControlButton")
                        )
                        assert "Launch coder" in labels1
                        assert "Commit plan" in labels1
                        assert "1 ✅ Tale" in line2_labels
                        assert "2 ❌ Reject" in line2_labels
                        assert "3 💬 Feedback" in line2_labels
                    else:
                        assert not modal.query("#plan-verdict-line1")
                        assert "1 ✅ Epic" in line2_labels
                        assert "Commit plan" not in " ".join(
                            str(b.label) for b in modal.query("GateControlButton")
                        )
                    if with_decisions:
                        header = modal.query_one("#plan-decisions-header")
                        verdict = modal.query_one("#plan-verdict")
                        assert content.contains_region(header.region)
                        assert not header.region.overlaps(verdict.region)
                    if width == 120:
                        # The min-width keeps decisions at 50 here; empty
                        # decision rails retain the 44-cell compact Verdict.
                        assert rail.region.width == (50 if with_decisions else 44), (
                            choice,
                            with_decisions,
                            rail.region,
                        )
                    pilot.app.pop_screen()
                    await pilot.pause()


async def test_decision_rail_widths_and_narrow_dock(tmp_path) -> None:
    """Responsive widths follow 40%/50/84 and narrow decisions dock at 62%."""
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import Vertical as _V

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "responsive_rail.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    definitions = plan_decision_definitions(tmp_path)
    for width, height, expected in (
        (120, 40, 50),
        (160, 48, 61),
        (200, 56, 77),
        (262, 72, 84),
    ):
        modal = _Modal(
            str(plan),
            default_choice="tale",
            plan_content="# Plan\n",
            decision_definitions=list(definitions),
            request_id=f"req-responsive-{width}",
        )
        async with _StyledApp().run_test(size=(width, height)) as pilot:
            pilot.app.push_screen(modal)
            await pilot.pause()
            await pilot.pause()
            rail = modal.query_one(
                ".gate-review-body > .gate-review-actions--decisions", _V
            )
            assert abs(rail.region.width - expected) <= 1, (
                width,
                expected,
                rail.region,
            )
            pilot.app.pop_screen()
            await pilot.pause()

    modal = _Modal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=list(definitions),
        request_id="req-responsive-narrow",
    )
    async with _StyledApp().run_test(size=(90, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        body = modal.query_one(".gate-review-body")
        rail = modal.query_one(
            ".gate-review-body > .gate-review-actions--decisions", _V
        )
        assert rail.region.width >= body.content_region.width - 1, (
            rail.region,
            body.content_region,
        )
        assert (
            abs(rail.region.height - round(body.content_region.height * 0.62)) <= 2
        ), (
            rail.region,
            body.content_region,
        )
        pilot.app.pop_screen()
        await pilot.pause()


async def test_generic_gate_rail_stays_42_with_stylesheet(tmp_path) -> None:
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import VerticalScroll as _VS

    from sase.ace.tui.modals.custom_gate_modal import (
        CustomGateModal as _CustomModal,
        CustomGateModalData as _CustomData,
    )
    from sase.ace.tui.modals.plan_approval_gate_data import (
        default_plan_gate_data as _plan_gate,
    )

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    data = _CustomData(
        request_id="req-generic-rail-1",
        title="Generic gate",
        sender="agent",
        icon="❓",
        notes=("note",),
        attachments=(),
        preview_name="Preview",
        preview_text="# Preview\n",
        gate=_plan_gate("tale"),
    )
    modal = _CustomModal(data)
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        rail = modal.query_one(".gate-review-body > .gate-review-actions", _VS)
        assert rail.region.width == 42, rail.region
        pilot.app.pop_screen()
        await pilot.pause()
