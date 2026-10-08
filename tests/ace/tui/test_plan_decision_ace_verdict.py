"""Plan verdict rendering: compact verdict, freeze banner, feedback bar, and labels."""

from __future__ import annotations

from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_compact_verdict_three_lines_with_without_and_epic",
    "test_feedback_bar_shows_carries_readonly",
    "test_freeze_banner_visible_and_submit_blocked",
    "test_plan_short_labels_and_generic_unchanged",
    "test_scroll_uses_cached_fold_map",
    "test_settled_labels_truthful",
]


async def test_compact_verdict_three_lines_with_without_and_epic(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    # With decisions (tale).
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=3,
        request_id="req-verdict-tale",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert modal.query_one("#plan-verdict")
        assert modal.query_one("#plan-verdict-line1")
        assert modal.query_one("#plan-verdict-line2")
        summary = modal.query_one("#plan-verdict-summary")
        rendered = summary.render()
        summary_text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "→" in summary_text
        # Short labels on line 1 with full-label tooltips.
        line1 = modal.query_one("#plan-verdict-line1")
        labels = [b.label for b in line1.query("GateControlButton")]
        assert any("Launch coder" in str(label) for label in labels)
        assert any("Commit plan" in str(label) for label in labels)
        tooltips = [
            getattr(b, "tooltip", "") or "" for b in line1.query("GateControlButton")
        ]
        assert any("Launch coder agent" in str(tip) for tip in tooltips)
        assert any(
            "Commit plan file to the plans sidecar" in str(tip) for tip in tooltips
        )
        # Line 2 numbered branches.
        line2 = modal.query_one("#plan-verdict-line2")
        line2_labels = " ".join(str(b.label) for b in line2.query("GateControlButton"))
        assert "1 ✅ Tale" in line2_labels
        assert "2 ❌ Reject" in line2_labels
        assert "3 💬 Feedback" in line2_labels
        pilot.app.pop_screen()
        await pilot.pause()

    # Without decisions: third line still present with verdict sentence.
    bare = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[],
        review_revision=1,
        request_id="req-verdict-bare",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(bare)
        await pilot.pause()
        assert bare.query_one("#plan-verdict")
        summary = bare.query_one("#plan-verdict-summary")
        rendered = summary.render()
        text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "→ coder + commit" in text
        pilot.app.pop_screen()
        await pilot.pause()

    # Epic: Epic label, no commit toggle.
    epic = PlanApprovalModal(
        str(plan),
        default_choice="epic",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=3,
        request_id="req-verdict-epic",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(epic)
        await pilot.pause()
        assert epic.query_one("#plan-verdict")
        line2 = epic.query_one("#plan-verdict-line2")
        line2_labels = " ".join(str(b.label) for b in line2.query("GateControlButton"))
        assert "1 ✅ Epic" in line2_labels
        assert "Commit plan" not in " ".join(
            str(b.label) for b in epic.query("GateControlButton")
        )
        pilot.app.pop_screen()
        await pilot.pause()


def test_plan_short_labels_and_generic_unchanged() -> None:
    from sase.ace.tui.modals.gate_branch_layout import plan_toggle_label, toggle_label
    from sase.notification_gates.models import GateOption

    def _opt(option_id: str, label: str) -> GateOption:
        return GateOption.from_mapping(
            {
                "id": option_id,
                "label": label,
                "command": {"argv": [f"commands/{option_id}"]},
            },
            0,
        )

    approve = _opt("approve", "Launch coder agent")
    commit = _opt("commit", "Commit plan file to the plans sidecar")
    assert "Launch coder" in plan_toggle_label(approve, True)
    assert "Launch coder agent" not in plan_toggle_label(approve, True)
    assert "Commit plan" in plan_toggle_label(commit, False)
    # Generic gates keep full labels.
    generic = _opt("deploy", "Deploy it")
    assert "Deploy it" in toggle_label(generic, True)
    assert "Deploy it" in plan_toggle_label(generic, True)


async def test_scroll_uses_cached_fold_map(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals import plan_approval_modal_view as view
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan grouping\n", encoding="utf-8")
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan grouping\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=1,
        request_id="req-scroll-cache",
    )
    calls = {"n": 0}
    orig = view.fold_plan_decisions_content

    def _counting(content: str):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return orig(content)

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        import unittest.mock as mock

        with mock.patch.object(
            view, "fold_plan_decisions_content", side_effect=_counting
        ) as _patched:
            before = calls["n"]
            # Focused decision scroll must use the cached fold map, not re-parse.
            modal._scroll_to_focused_decision()
            await pilot.pause()
            assert calls["n"] == before


async def test_freeze_banner_visible_and_submit_blocked(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals._plan_approval_modal_state import DECISIONS_FROZEN_MESSAGE
    from sase.ace.tui.modals.gate_action_runner import GateEditOutcome
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    from sase.ace.tui.modals.gate_action_controls import GateActionsData
    from sase.notification_gates.model_operations import GateOperation

    actions = GateActionsData(
        operations=(
            GateOperation.from_mapping(
                {
                    "id": "edit-plan",
                    "kind": "edit_file",
                    "label": "Edit plan",
                    "target": "plan.md",
                    "edit_target": "origin",
                },
                0,
            ),
        ),
    )
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=5,
        request_id="req-freeze-1",
        actions=actions,
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        outcome = GateEditOutcome(
            accepted=False,
            message=DECISIONS_FROZEN_MESSAGE,
            draft=True,
            draft_path=str(plan),
        )
        modal._apply_edit_outcome("edit-plan", outcome)
        await pilot.pause()
        from sase.ace.tui.modals.gate_branch_controls import GateBranchControls

        branch = modal.query_one(GateBranchControls)
        assert (
            branch._submission_block == "Accept or discard your draft before submitting"
        )
        banner = modal.query_one("#gate-draft-banner")
        assert "hidden" not in banner.classes
        # Submit stays blocked: resolving a branch notifies the block.
        notes: list[str] = []
        orig_notify = branch.notify

        def _capture(msg: object, *a: object, **k: object) -> None:  # type: ignore[no-untyped-def]
            notes.append(str(msg))
            return None

        branch.notify = _capture  # type: ignore[assignment]
        try:
            branch._resolve_branch(1)
        finally:
            branch.notify = orig_notify  # type: ignore[assignment]
        assert any("Accept or discard" in note for note in notes)
        # Accepted outcome with draft=False clears the banner + block.
        cleared = GateEditOutcome(
            accepted=True,
            message="Edit accepted",
            draft=False,
            draft_path=None,
        )
        modal._apply_edit_outcome("edit-plan", cleared)
        await pilot.pause()
        assert "hidden" in modal.query_one("#gate-draft-banner").classes
        assert branch._submission_block is None
        cleared_notes: list[str] = []
        branch.notify = lambda msg, *a, **k: cleared_notes.append(str(msg))  # type: ignore[assignment]
        try:
            branch._resolve_branch(1)
        finally:
            branch.notify = orig_notify  # type: ignore[assignment]
        assert not any("Accept or discard" in note for note in cleared_notes)


async def test_feedback_bar_shows_carries_readonly(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.widgets import PromptInputBar

    class _BarApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self):  # type: ignore[no-untyped-def]
            from textual.app import ComposeResult

            yield PromptInputBar(mode="feedback", id="prompt-input-bar")

    from sase.ace.tui.actions.agents._types import PlanFeedbackContext

    app = _BarApp()
    async with app.run_test(size=(120, 20)) as pilot:
        from pathlib import Path

        app._plan_feedback_context = PlanFeedbackContext(  # type: ignore[attr-defined]
            notification_id="n1",
            response_path=Path("/tmp/response.json"),
            agent_identity=None,
            plan_file="/tmp/plan.md",
            notification=None,
            carries=("Carries: grouping → mode",),
            decision_inputs=None,
            review_revision=3,
        )
        # Remount the bar so it reads the context set above.
        try:
            await pilot.app.query_one("#prompt-input-bar").remove()
        except Exception:
            pass
        await pilot.app.mount(PromptInputBar(mode="feedback", id="prompt-input-bar"))
        await pilot.pause()
        carries = pilot.app.query_one("#prompt-feedback-carries")
        rendered = carries.render()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "Carries: grouping → mode" in plain
        # Read-only: carries widget is a Static, not an editable text area.
        from textual.widgets import Static

        assert isinstance(carries, Static)


def test_settled_labels_truthful(tmp_path) -> None:
    from sase.ace.tui.actions.agents._notification_plan_gate import (
        _settled_text_for_bundle,
    )
    import types

    def _bundle(selected: tuple[str, ...], source: str = "cli"):  # type: ignore[no-untyped-def]
        payload = {
            "selected_option_ids": list(selected),
            "source": source,
            "option_inputs": {},
        }
        terminal = types.SimpleNamespace(status="ok")
        return payload, terminal

    import unittest.mock as mock

    definitions = plan_decision_definitions(tmp_path)
    fake_bundle = types.SimpleNamespace(
        root="/tmp",
        request="/tmp/req",
        response="/tmp/res",
        cancellation="/tmp/c",
        legacy=False,
    )
    with mock.patch(
        "sase.notification_gates.debug_artifacts.terminal_artifact"
    ) as term:
        term.return_value = (
            _bundle(("approve", "commit"))[1],
            {
                "selected_option_ids": ["approve", "commit"],
                "source": "cli",
                "option_inputs": {},
            },
            "response",
        )
        text = _settled_text_for_bundle(fake_bundle, definitions, "tale")
        assert text.startswith("Approved via CLI")
        term.return_value = (
            types.SimpleNamespace(status="ok"),
            {
                "selected_option_ids": ["reject"],
                "source": "telegram",
                "option_inputs": {},
            },
            "response",
        )
        assert (
            _settled_text_for_bundle(fake_bundle, definitions, "tale")
            == "Rejected via Telegram"
        )
        term.return_value = (
            types.SimpleNamespace(status="ok"),
            {"selected_option_ids": ["feedback"], "source": "tui", "option_inputs": {}},
            "response",
        )
        assert (
            _settled_text_for_bundle(fake_bundle, definitions, "tale")
            == "Feedback via ACE"
        )
