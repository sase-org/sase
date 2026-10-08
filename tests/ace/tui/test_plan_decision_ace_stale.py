"""Stale review reloads and the render-path plan section."""

from __future__ import annotations

from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_plan_section_render_path_no_stat_no_validate",
    "test_stale_review_reloads_revision_keeping_values",
]


async def test_stale_review_reloads_revision_keeping_values(tmp_path) -> None:
    from sase.ace.tui.actions.agents._notification_plan_gate import _handle_stale_review
    from sase.notifications import Notification
    import types

    from sase.ace.tui.modals._plan_approval_modal_state import esc_drafts

    # Closed modal: stash filtered values and push a fresh modal.
    plan_file = tmp_path / "stale_plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="stale-1",
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(plan_file)],
        action="PlanApproval",
        action_data={"request_id": "stale-1"},
    )
    result = types.SimpleNamespace(
        option_inputs={"approve": {"decision_grouping": "mode"}},
    )
    import unittest.mock as mock

    old_defs = plan_decision_definitions(tmp_path)
    grouping_def = next(d for d in old_defs if d.get("id") == "grouping")
    new_choice_def = {
        "id": "new_choice",
        "kind": "choice",
        "ask": "New choice?",
        "choices": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
        "default": "a",
        "effective_default": "a",
    }
    new_defs = [dict(grouping_def), dict(new_choice_def)]
    from sase.ace.tui.modals.plan_approval_gate_data import default_plan_gate_data

    reloaded = types.SimpleNamespace(
        plan_file=str(plan_file),
        plan_content="# New plan\nNew body marker\n",
        default_choice="tale",
        gate=default_plan_gate_data("tale"),
        actions=None,
        decision_definitions=new_defs,
        review_revision=9,
        request_id="stale-1",
        settled_text=None,
    )
    pushed: list[object] = []

    def _push(screen: object, *a: object, **k: object) -> None:
        pushed.append(screen)

    app = types.SimpleNamespace(
        notify=lambda *a, **k: None,
        push_screen=_push,
        screen=None,
        screen_stack=[],
    )
    esc_drafts.pop("stale-1", None)
    with (
        mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate.load_neutral_plan_modal_data",
            return_value=reloaded,
        ),
        mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate._refresh_notifications",
            return_value=None,
        ),
    ):
        assert _handle_stale_review(app, notification, result) is True
    assert esc_drafts.get("stale-1", {}).get("grouping") == "mode"
    assert "tui_note" not in esc_drafts.get("stale-1", {})
    assert "new_choice" not in esc_drafts.get("stale-1", {})
    assert len(pushed) == 1
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    modal_pushed = pushed[0]
    assert isinstance(modal_pushed, PlanApprovalModal)
    assert modal_pushed._review_revision == 9  # type: ignore[attr-defined]
    assert modal_pushed._decision_draft.value_for("grouping") == "mode"  # type: ignore[attr-defined]
    assert "tui_note" not in modal_pushed._decision_draft.values()  # type: ignore[attr-defined]
    assert modal_pushed._decision_draft.value_for("new_choice") == "a"  # type: ignore[attr-defined]

    # Open modal: rebuild in place, no second push, document refreshed.
    from textual.app import App as _App

    class _OpenApp(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    open_plan = tmp_path / "open_plan.md"
    open_plan.write_text("# Old\nOld body\n", encoding="utf-8")
    open_id = "stale-open-1"
    open_notification = Notification(
        id=open_id,
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(open_plan)],
        action="PlanApproval",
        action_data={"request_id": open_id},
    )
    open_result = types.SimpleNamespace(
        option_inputs={"approve": {"decision_grouping": "mode"}},
    )
    open_reloaded = types.SimpleNamespace(
        plan_file=str(open_plan),
        plan_content="# Reloaded\nReloaded body marker\n",
        default_choice="tale",
        gate=default_plan_gate_data("tale"),
        actions=None,
        decision_definitions=new_defs,
        review_revision=11,
        request_id=open_id,
        settled_text=None,
    )
    esc_drafts.pop(open_id, None)
    live_modal = PlanApprovalModal(
        str(open_plan),
        default_choice="tale",
        plan_content="# Old\nOld body\n",
        decision_definitions=old_defs,
        review_revision=5,
        request_id=open_id,
    )
    async with _OpenApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(live_modal)
        await pilot.pause()
        await pilot.pause()
        pushes: list[object] = []
        orig_push = pilot.app.push_screen

        def _capture_push(screen: object, *a: object, **k: object) -> object:
            pushes.append(screen)
            return orig_push(screen, *a, **k)

        with (
            mock.patch.object(pilot.app, "push_screen", _capture_push),
            mock.patch(
                "sase.ace.tui.actions.agents._notification_plan_gate.load_neutral_plan_modal_data",
                return_value=open_reloaded,
            ),
            mock.patch(
                "sase.ace.tui.actions.agents._notification_plan_gate._refresh_notifications",
                return_value=None,
            ),
        ):
            assert (
                _handle_stale_review(pilot.app, open_notification, open_result) is True
            )
        await pilot.pause()
        await pilot.pause()
        assert pushes == []
        assert pilot.app.screen is live_modal
        assert live_modal._review_revision == 11  # type: ignore[attr-defined]
        from sase.ace.tui.modals.plan_decision_rows import PlanDecisionRows

        rows = live_modal.query_one("#plan-decision-rows", PlanDecisionRows)
        assert [r.get("id") for r in rows._rows] == ["grouping", "new_choice"]
        assert set(rows._by_id.keys()) == {"grouping", "new_choice"}
        from textual.widgets import Static as _Static

        content = live_modal.query_one("#plan-approval-content", _Static)
        rendered = content.render()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        # New body text is what the pane shows; fold/spans recomputed.
        assert "Reloaded body marker" in plain or "Reloaded" in live_modal._folded_text  # type: ignore[attr-defined]
        assert live_modal._folded_text is not None  # type: ignore[attr-defined]
        assert live_modal._callout_spans is not None  # type: ignore[attr-defined]
        assert esc_drafts.get(open_id, {}).get("grouping") == "mode"


def test_plan_section_render_path_no_stat_no_validate(monkeypatch, tmp_path) -> None:
    import sase.ace.tui.widgets.prompt_panel._agent_plan_section as section

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    from sase.ace.tui.models._agent_associated_plan_summary import (
        _ASSOCIATED_PLAN_SHEET_CACHE,
    )

    _ASSOCIATED_PLAN_SHEET_CACHE[str(plan)] = ({"rows": []}, "reviewer", "tui")
    summary = type("S", (), {"actual_path": str(plan)})()
    monkeypatch.setattr(
        "os.stat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stat on render path")),
    )
    import sase.sdd.plan_validate as validate_mod

    monkeypatch.setattr(
        validate_mod,
        "validate_plan",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("validate on render path")
        ),
    )
    sheet, by, via = section._load_plan_sheet(summary)  # type: ignore[arg-type]
    assert sheet == {"rows": []}
    assert by == "reviewer"
    # Miss returns no sheet without touching disk.
    missing = type("S", (), {"actual_path": str(tmp_path / "missing.md")})()
    assert section._load_plan_sheet(missing)[0] is None  # type: ignore[arg-type]
