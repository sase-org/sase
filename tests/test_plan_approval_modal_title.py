"""Tests for PlanApprovalModal title and branch-driven controls."""

from textual.app import App
from textual.binding import Binding

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
    markup = _provider_badge_markup("agy", "Gemini 3.5 Flash (High)")
    assert "AGY" in markup
    assert "Gemini 3.5 Flash (High)" in markup
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


def test_title_markup_without_badge_matches_legacy_form() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = None
    modal._model = None
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "20260422_143012_my_feature.md" in title
    assert "CLAUDE" not in title


def test_title_markup_with_badge_includes_provider_and_filename() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = "claude"
    modal._model = "opus"
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "CLAUDE" in title
    assert "opus" in title
    assert "20260422_143012_my_feature.md" in title


def test_modal_constructor_accepts_provider_model_and_authored_tier() -> None:
    modal = PlanApprovalModal(
        "/tmp/plan.md",
        llm_provider="agy",
        model="Gemini 3.5 Flash (High)",
        default_choice="epic",
    )
    assert modal._llm_provider == "agy"
    assert modal._model == "Gemini 3.5 Flash (High)"
    assert modal._default_choice == "epic"
    assert modal._gate.branches == (("approve",), ("reject",), ("feedback",))


def test_bindings_use_shared_branch_actions_and_drop_presets() -> None:
    actions = {
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in PlanApprovalModal.BINDINGS
    }
    assert {
        "next_control",
        "previous_control",
        "toggle_option",
        "activate_control",
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
        controls.toggle_option(0, 0)
        modal.action_submit_branch()
        await pilot.pause()

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].selected_option_ids == ("commit",)
    assert results[0].commit_plan is True
    assert results[0].run_coder is False
