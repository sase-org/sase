"""Tests for PlanApprovalModal workbench and branch-driven controls."""

from textual.app import App
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from sase.ace.tui.modals.gate_branch_controls import GateBranchControls
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalModal,
    PlanApprovalResult,
    _provider_badge_markup,
)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def test_badge_markup_empty_when_no_provider_or_model() -> None:
    assert _provider_badge_markup(None, None) == ""


def test_badge_markup_claude_contains_provider_and_model() -> None:
    markup = _provider_badge_markup("claude", "opus")
    assert "CLAUDE" in markup
    assert "opus" in markup
    assert "#D97757" in markup


def test_badge_markup_codex_uses_lime_theme() -> None:
    markup = _provider_badge_markup("codex", "o3")
    assert "CODEX" in markup
    assert "o3" in markup
    assert "#10A37F" in markup


def test_badge_markup_agy_uses_antigravity_indigo() -> None:
    markup = _provider_badge_markup("agy", "gemini-3.6-flash-high")
    assert "AGY" in markup
    assert "gemini-3.6-flash-high" in markup
    assert "#6E5DE7" in markup


def test_badge_markup_unknown_provider_falls_back_to_plain_label() -> None:
    markup = _provider_badge_markup("mystery", "x1")
    assert "MYSTERY" in markup
    assert "x1" in markup
    assert "#AF87D7" in markup


def test_badge_markup_infers_claude_from_model_name() -> None:
    markup = _provider_badge_markup(None, "opus")
    assert "CLAUDE" in markup
    assert "opus" in markup


def test_title_markup_without_badge_omits_document_name() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = None
    modal._model = None
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "20260422_143012_my_feature.md" not in title
    assert "CLAUDE" not in title


def test_title_markup_with_badge_omits_document_name() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = "claude"
    modal._model = "opus"
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "CLAUDE" in title
    assert "opus" in title
    assert "20260422_143012_my_feature.md" not in title


def test_modal_constructor_accepts_provider_model_and_authored_tier() -> None:
    modal = PlanApprovalModal(
        "/tmp/plan.md",
        llm_provider="agy",
        model="gemini-3.6-flash-high",
        default_choice="epic",
    )
    assert modal._llm_provider == "agy"
    assert modal._model == "gemini-3.6-flash-high"
    assert modal._default_choice == "epic"
    assert modal._gate.branches == (("approve",), ("reject",), ("feedback",))
    assert modal._gate.options[0].label == "Epic"


def test_modal_constructor_copy_path_falls_back_to_reviewed_plan() -> None:
    modal = PlanApprovalModal("/tmp/reviewed-plan.md")

    assert modal._copy_plan_path == "/tmp/reviewed-plan.md"


def test_bindings_swap_path_and_full_contents_shortcuts() -> None:
    assert ("y", "copy_plan_path", "Copy path") in PlanApprovalModal.BINDINGS
    assert ("Y", "copy_plan", "Copy all contents") in PlanApprovalModal.BINDINGS


def test_footer_names_path_and_full_contents_shortcuts() -> None:
    footer = PlanApprovalModal("/tmp/plan.md")._footer_text().plain

    assert "y=Copy path" in footer
    assert "Y=Copy all contents" in footer


def test_bindings_use_shared_branch_actions_and_drop_presets() -> None:
    actions = {
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in PlanApprovalModal.BINDINGS
    }
    assert {
        "next_control",
        "previous_control",
        "toggle_option",
        "submit_primary",
        "submit_branch",
    } <= actions
    assert {"approve", "tale", "epic", "reject", "feedback"}.isdisjoint(actions)


def test_programmatic_approve_and_tale_project_selected_options() -> None:
    modal = PlanApprovalModal("/tmp/plan.md")
    captured: list[PlanApprovalResult] = []
    modal.dismiss = captured.append  # type: ignore[assignment]

    modal.action_approve()
    modal.action_tale()

    assert captured[0].selected_option_ids == ("approve",)
    assert captured[0].commit_plan is False
    assert captured[0].run_coder is True
    assert captured[1].selected_option_ids == ("approve", "commit")
    assert captured[1].commit_plan is True
    assert captured[1].run_coder is True


def test_action_custom_uses_coder_options_path() -> None:
    modal = PlanApprovalModal("/tmp/plan.md", default_choice="epic")
    called: list[object] = []

    def fake_push_approve_options(**kwargs: object) -> None:
        called.append(kwargs["choice"])

    modal._push_approve_options = fake_push_approve_options  # type: ignore[method-assign]
    modal.action_custom()

    assert called == ["epic"]


async def test_group_submit_uses_current_branch_selection(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan), default_choice="tale")

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        controls = modal.query_one(GateBranchControls)
        assert controls.selected_option_ids(0) == ("approve", "commit")
        coder_label = str(modal.query_one("#gate-option-0-0", Button).label)
        assert "🚀" in coder_label
        assert "Launch coder agent" in coder_label
        assert not coder_label.startswith("1 ")
        assert "Commit plan file to the plans sidecar" in str(
            modal.query_one("#gate-option-0-1", Button).label
        )
        tale_label = str(modal.query_one("#gate-group-submit-0", Button).label)
        assert tale_label.startswith("1 ")
        assert "✅" in tale_label
        assert "Tale" in tale_label
        assert str(modal.query_one("#gate-singleton-1", Button).label).startswith("2 ")
        assert str(modal.query_one("#gate-singleton-2", Button).label).startswith("3 ")
        assert str(modal.query_one("#plan-approval-cancel", Button).label) == "Cancel"
        await pilot.press("space")
        await pilot.press("1")
        await pilot.pause()

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].selected_option_ids == ("commit",)
    assert results[0].commit_plan is True
    assert results[0].run_coder is False


async def test_plan_document_uses_two_pane_shell_and_border_title(tmp_path) -> None:
    plan = tmp_path / "review-plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    modal = PlanApprovalModal(str(plan), plan_content="# Preloaded\n")

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one(".gate-review-body")
        assert modal.query_one(".gate-review-actions")
        scroll = modal.query_one("#plan-approval-scroll", VerticalScroll)
        assert scroll.has_class("gate-review-document")
        assert scroll.border_title == "review-plan.md"
        assert (
            "review-plan.md"
            not in modal.query_one("#plan-approval-title", Static).render().plain
        )


async def test_copy_shortcuts_use_durable_path_and_all_preloaded_content(
    tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    reviewed_plan = tmp_path / "requests" / "plan.md"
    durable_plan = home / ".sase" / "plans" / "202607" / "durable-plan.md"
    content = "---\ntier: tale\n---\n# Complete plan\n\nFinal byte."
    copied: list[str] = []
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    modal = PlanApprovalModal(
        str(reviewed_plan),
        copy_plan_path=str(durable_plan),
        plan_content=content,
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("Y")
        await pilot.pause()

    assert copied == ["~/.sase/plans/202607/durable-plan.md", content]


async def test_breakpoint_classes_switch_between_narrow_and_wide(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    narrow = PlanApprovalModal(str(plan))
    async with _TestApp().run_test(size=(90, 40)) as pilot:
        pilot.app.push_screen(narrow)
        await pilot.pause()
        assert narrow.has_class("-gate-review-narrow")
        assert not narrow.has_class("-gate-review-wide")

    wide = PlanApprovalModal(str(plan))
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(wide)
        await pilot.pause()
        assert wide.has_class("-gate-review-wide")
        assert not wide.has_class("-gate-review-narrow")


async def test_plan_cancel_button_dismisses_without_result(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan))

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.click("#plan-approval-cancel")
        await pilot.pause()

    assert results == [None]


async def test_vertical_stack_navigation_cycles_every_control(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    modal = PlanApprovalModal(str(plan), default_choice="tale")

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        expected_ids = [
            "gate-option-0-0",
            "gate-option-0-1",
            "gate-group-submit-0",
            "gate-singleton-1",
            "gate-singleton-2",
        ]
        focused_ids: list[str | None] = []
        feedback_became_visible = False
        for _ in expected_ids:
            focused_ids.append(modal.focused.id if modal.focused is not None else None)
            if modal.focused is not None and modal.focused.id == "gate-singleton-2":
                feedback_became_visible = not modal.query_one(
                    "#gate-feedback-input"
                ).has_class("hidden")
            await pilot.press("j")
            await pilot.pause()

        assert focused_ids == expected_ids
        assert feedback_became_visible
        assert modal.focused is not None
        assert modal.focused.id == expected_ids[0]
        assert modal.query_one(".gate-review-actions").query_one("#gate-feedback-input")


async def test_enter_submits_untouched_tale_primary_without_toggling(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan), default_choice="tale")

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].selected_option_ids == ("approve", "commit")
    assert results[0].run_coder is True
    assert results[0].commit_plan is True


async def test_enter_submits_epic_primary(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan), default_choice="epic")

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].selected_option_ids == ("approve",)
    assert results[0].choice == "epic"


async def test_number_one_submits_epic_primary_branch(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan), default_choice="epic")

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("1")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].selected_option_ids == ("approve",)
    assert results[0].choice == "epic"


async def test_number_one_submits_tale_primary_branch(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(str(plan), default_choice="tale")

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("1")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].selected_option_ids == ("approve", "commit")
    assert results[0].choice == "tale"
