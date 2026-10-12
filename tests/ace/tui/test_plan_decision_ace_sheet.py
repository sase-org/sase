"""Decision sheet (z), Esc-leaves-sheet, footer, and fold-prefix collision."""

from __future__ import annotations

from pathlib import Path as _Path

from rich.cells import cell_len
from rich.text import Text
from textual.app import App
from textual.binding import Binding

from sase.ace.tui.keymaps import GateModalKeymaps
from sase.ace.tui.modals.plan_approval_footer import plan_approval_footer_text
from sase.ace.tui.modals.plan_approval_gate_data import default_plan_gate_data
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.ace.tui.modals.plan_decision_rows import PlanDecisionRows
from tests.ace.tui.visual._ace_plan_decisions_png_fixtures import (
    SYNCTHING_PLAN,
    decision_gate_bundle,
)

_ROOT = _Path(__file__).resolve().parents[3]


class _StyledApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    ENABLE_COMMAND_PALETTE = False


class _FoldApp(_StyledApp):
    BINDINGS = [Binding("z", "start_fold_mode", "Fold")]

    def __init__(self) -> None:
        super().__init__()
        self._fold_mode_active = False

    def action_start_fold_mode(self) -> None:
        self._fold_mode_active = True


def _syncthing_modal(tmp_path, monkeypatch, *, request_id: str) -> PlanApprovalModal:
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="sheet-syncthing.md",
        content=SYNCTHING_PLAN,
    )
    return PlanApprovalModal(
        str(plan),
        default_choice="tale",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id=request_id,
    )


def test_footer_merges_choice_keys_and_conditions_on_focus() -> None:
    keys = GateModalKeymaps()
    gate = default_plan_gate_data("tale")
    empty = Text()
    focused = plan_approval_footer_text(
        gate,
        keys,
        empty,
        has_decisions=True,
        decision_focused=True,
    ).plain
    assert "h/l=Choice" in focused
    assert "Space=Cycle" in focused
    assert "r/R=Reset" in focused
    assert "z=Sheet" in focused
    assert "Next choice" not in focused
    assert "Prev choice" not in focused
    assert "Reset all" not in focused
    assert "Space=Toggle" not in focused

    unfocused = plan_approval_footer_text(
        gate,
        keys,
        empty,
        has_decisions=True,
        decision_focused=False,
    ).plain
    assert "Space=Toggle" in unfocused
    assert "h/l=Choice" not in unfocused
    assert "Space=Cycle" not in unfocused
    assert "r/R=Reset" not in unfocused
    assert "z=Sheet" in unfocused

    inside = plan_approval_footer_text(
        gate,
        keys,
        empty,
        has_decisions=True,
        decision_focused=True,
        sheet_open=True,
    ).plain
    assert "z=Back to plan" in inside
    assert "z=Sheet" not in inside

    none = plan_approval_footer_text(gate, keys, empty, has_decisions=False).plain
    assert "z=Sheet" not in none
    assert "Space=Toggle" in none
    assert cell_len(focused) <= 262


async def test_z_toggles_sheet_and_esc_leaves_then_cancels(
    tmp_path, monkeypatch
) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-z")
    results: list[object] = []
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.pause()
        assert not modal.has_class("-decision-sheet")
        rows = modal.query_one("#plan-decision-rows", PlanDecisionRows)
        assert not rows._sheet_mode
        await pilot.press("z")
        await pilot.pause()
        assert modal.has_class("-decision-sheet")
        assert rows._sheet_mode
        assert "z=Back to plan" in modal._footer_text().plain
        # Every card is expanded: a non-current ask is fully present.
        from sase.ace.tui.modals.plan_decision_rows import _DecisionCard

        other = modal.query_one("#plan-decision-1", _DecisionCard)
        other_text = "\n".join(other.rendered_lines())
        assert "stow-style" in other_text or "dotfile" in other_text.lower()
        await pilot.press("escape")
        await pilot.pause()
        assert modal.has_class("-decision-sheet") is False
        assert results == []
        await pilot.press("escape")
        await pilot.pause()
    assert results == [None]


async def test_q_leaves_sheet_like_escape(tmp_path, monkeypatch) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-q")
    results: list[object] = []
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()
        assert modal.has_class("-decision-sheet")
        await pilot.press("q")
        await pilot.pause()
        assert not modal.has_class("-decision-sheet")
        assert results == []


async def test_narrow_sheet_stays_docked_on_open(tmp_path, monkeypatch) -> None:
    """narrow_sheet = no: 90 columns and 4 decisions still open docked."""
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-narrow")
    async with _StyledApp().run_test(size=(90, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        assert len(modal._decision_definitions) >= 3
        assert not modal.has_class("-decision-sheet")
        await pilot.press("z")
        await pilot.pause()
        assert modal.has_class("-decision-sheet")


async def test_footer_refreshes_on_focus_without_sheet_recompute(
    tmp_path, monkeypatch
) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-footer")
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        focused_plain = modal._footer_text().plain
        assert "h/l=Choice" in focused_plain
        assert "Space=Cycle" in focused_plain
        sheet_calls: list[int] = []
        original = modal._decision_draft.sheet

        def _counting_sheet() -> dict:
            sheet_calls.append(1)
            return original()

        modal._decision_draft.sheet = _counting_sheet  # type: ignore[method-assign]
        await pilot.press("j")
        await pilot.pause()
        moved = modal._footer_text().plain
        # Focus left the first card (Actions or another card). Either way
        # the footer refreshed from the cached badge, not a new sheet().
        assert sheet_calls == []
        assert "z=Sheet" in moved


async def test_z_does_not_start_fold_mode(tmp_path, monkeypatch) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-fold")
    async with _FoldApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()
        assert modal.has_class("-decision-sheet")
        assert pilot.app._fold_mode_active is False


async def test_sheet_keeps_choice_keys_and_hides_plan_pane(
    tmp_path, monkeypatch
) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-keys")
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        assert modal._decision_draft.value_for("root") == "db"
        await pilot.press("z")
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert modal._decision_draft.value_for("root") == "legacy"
        scroll = modal.query_one("#plan-approval-scroll")
        assert not scroll.display


async def test_decisions_footer_fits_one_line_at_262(tmp_path, monkeypatch) -> None:
    modal = _syncthing_modal(tmp_path, monkeypatch, request_id="req-sheet-262")
    async with _StyledApp().run_test(size=(262, 72)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        plain = modal._footer_text().plain
        assert cell_len(plain) <= 262
        assert "z=Sheet" in plain
        assert "h/l=Choice" in plain
