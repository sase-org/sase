"""Decision cards: no-clip invariant and density rule."""

from __future__ import annotations

from sase.ace.tui.modals.plan_decision_rows import _decide_decision_density
from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_decision_cards_never_clip_with_stylesheet",
    "test_decision_density_pins_other_rows_and_caps_current_card",
]


def test_decision_density_pins_other_rows_and_caps_current_card() -> None:
    """The density rule uses two lines, one line, then a capped current slot."""
    two_lines = _decide_decision_density(12, 6, [2, 2], [1, 1])
    assert two_lines.preview_lines == 2
    assert two_lines.current_max_height is None
    assert not two_lines.show_more

    one_line = _decide_decision_density(9, 7, [2, 2], [1, 1])
    assert one_line.preview_lines == 1
    assert one_line.current_max_height is None
    assert not one_line.show_more

    pinned = _decide_decision_density(7, 10, [2, 2], [1, 1])
    assert pinned.preview_lines == 1
    assert pinned.current_max_height == 4
    assert pinned.show_more

    # At a tiny height there is no row to spare for the hint. The current
    # slot stays scrollable with a positive CSS cap instead of clipping to 0.
    tiny = _decide_decision_density(2, 10, [2, 2], [1, 1])
    assert tiny.preview_lines == 1
    assert tiny.current_max_height == 1
    assert not tiny.show_more


async def test_decision_cards_never_clip_with_stylesheet(tmp_path, monkeypatch) -> None:
    """No-clip pilot invariant: cards stay inside the list, never scroll sideways.

    Syncthing and max-copy fixtures at 90x40, 120x40, and 200x56, for every focus
    index: every card lies horizontally inside the list's content region and
    no list or slot shows a horizontal scrollbar. Verified against the prior
    Button implementation first: its focused row measured 103 cells wide in
    a 44-cell viewport (clipped by 59 cells), so this invariant fails there
    and passes with cards.
    """
    import json
    from pathlib import Path as _Path

    from textual.app import App as _App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal
    from sase.ace.tui.modals.plan_decision_rows import (
        _DecisionCard as _Card,
    )
    from sase.ace.tui.modals.plan_decision_rows import (
        PlanDecisionRows as _Rows,
    )
    from tests.ace.tui.visual._ace_plan_decisions_png_fixtures import (
        MAXCOPY_PLAN,
        MEMORY_QUOTE,
        SYNCTHING_PLAN,
    )

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    cases = []
    for name, content, verified in (
        ("syncthing", SYNCTHING_PLAN, False),
        ("maxcopy", MAXCOPY_PLAN, True),
    ):
        plan = tmp_path / f"noclip_{name}.md"
        plan.write_text(content, encoding="utf-8")
        if verified:
            artifacts = tmp_path / f"noclip_{name}_artifacts"
            artifacts.mkdir(exist_ok=True)
            (artifacts / "agent_meta.json").write_text(
                json.dumps({"prompt_origin": "typed"}), encoding="utf-8"
            )
            (artifacts / "submitted_prompt.md").write_text(
                f"Please do the work {MEMORY_QUOTE} thanks.\n", encoding="utf-8"
            )
            monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        else:
            monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        from sase.plan_gate import build_plan_approval_gate_spec

        spec = build_plan_approval_gate_spec(plan, "visual-session")
        definitions = [
            dict(item)
            for item in spec["payload"].get("decisions", [])
            if isinstance(item, dict)
        ]
        assert definitions
        cases.append((name, plan, definitions))
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    for name, plan, definitions in cases:
        for width, height in ((90, 40), (120, 40), (200, 56)):
            modal = _Modal(
                str(plan),
                default_choice="tale",
                plan_content=plan.read_text(encoding="utf-8"),
                decision_definitions=[dict(d) for d in definitions],
                review_revision=3,
                request_id=f"req-noclip-{name}-{width}",
            )
            async with _StyledApp().run_test(size=(width, height)) as pilot:
                pilot.app.push_screen(modal)
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()
                rows = modal.query_one("#plan-decision-rows", _Rows)
                slot_count = len(definitions)
                assert rows.focused_index == 0
                for focus in range(slot_count):
                    rows.set_focused_index(focus)
                    await pilot.pause()
                    await pilot.pause()
                    listing = modal.query_one("#plan-decision-rows", _Rows)
                    content = listing.content_region
                    assert not listing.show_horizontal_scrollbar, (name, width, focus)
                    for index in range(slot_count):
                        card = modal.query_one(f"#plan-decision-{index}", _Card)
                        region = card.region
                        assert content.x <= region.x, (
                            name,
                            width,
                            focus,
                            index,
                            region,
                            content,
                        )
                        assert region.right <= content.right, (
                            name,
                            width,
                            focus,
                            index,
                            region,
                            content,
                        )
                        slot = modal.query_one(f"#decision-slot-{index}")
                        assert not slot.show_horizontal_scrollbar, (
                            name,
                            width,
                            focus,
                            index,
                        )
                        if width == 90:
                            visible_rows = min(
                                slot.region.bottom, content.bottom
                            ) - max(slot.region.y, content.y)
                            assert visible_rows >= 1, (
                                name,
                                width,
                                focus,
                                index,
                                slot.region,
                                content,
                            )
                            if index == focus and slot.max_scroll_y > 0:
                                slot.scroll_end(animate=False)
                                await pilot.pause()
                                assert slot.scroll_y >= slot.max_scroll_y, (
                                    name,
                                    focus,
                                    slot.scroll_y,
                                    slot.max_scroll_y,
                                )
                        for line in card.rendered_lines():
                            from rich.cells import cell_len as _cell_len

                            assert _cell_len(line) <= card._card_width, (
                                name,
                                width,
                                focus,
                                index,
                                line,
                            )
                if name == "maxcopy" and width == 90:
                    await pilot.resize_terminal(262, 72)
                    await pilot.pause()
                    await pilot.pause()
                    resized_slot = modal.query_one("#decision-slot-0")
                    assert resized_slot.max_scroll_y == 0
                    assert modal.query_one("#decision-more-0").has_class("hidden")
                pilot.app.pop_screen()
                await pilot.pause()
