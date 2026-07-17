"""Tests for PlanApprovalModal title rendering with provider/model badge."""

from textual.app import App

from sase.ace.tui.modals.custom_gate_modal import GateExtrasSelectionList
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalModal,
    PlanApprovalResult,
    _provider_badge_markup,
)
from sase.notification_gates.models import GateChoice, GateExtra


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _approval_extras() -> tuple[GateExtra, ...]:
    choice = GateChoice.from_mapping(
        {
            "id": "approve",
            "label": "Approve",
            "command": {"argv": ["commands/approve"]},
            "extras": [
                {
                    "id": "commit_plan",
                    "label": "Commit plan file to the plans sidecar",
                    "default_selected": True,
                    "command": {"argv": ["commands/commit_plan"]},
                },
                {
                    "id": "run_coder",
                    "label": "Run coder follow-up",
                    "default_selected": True,
                    "command": {"argv": ["commands/run_coder"]},
                },
            ],
        },
        0,
    )
    return choice.extras


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
    assert "CODEX" not in title
    assert "AGY" not in title


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


def test_modal_constructor_accepts_keyword_only_provider_and_model() -> None:
    modal = PlanApprovalModal(
        "/tmp/plan.md", llm_provider="agy", model="Gemini 3.5 Flash (High)"
    )
    assert modal._llm_provider == "agy"
    assert modal._model == "Gemini 3.5 Flash (High)"


def test_modal_constructor_defaults_provider_and_model_to_none() -> None:
    modal = PlanApprovalModal("/tmp/plan.md")
    assert modal._llm_provider is None
    assert modal._model is None
    assert modal._default_choice == "approve"


def test_modal_constructor_accepts_authored_tier_default() -> None:
    modal = PlanApprovalModal("/tmp/plan.md", default_choice="epic")

    assert modal._default_choice == "epic"


def test_bindings_include_g_scroll_to_top() -> None:
    assert ("g", "scroll_to_top", "Top") in PlanApprovalModal.BINDINGS


def test_bindings_include_capital_g_scroll_to_bottom() -> None:
    assert ("G", "scroll_to_bottom", "Bottom") in PlanApprovalModal.BINDINGS


def test_bindings_show_approve_for_approve_action() -> None:
    assert ("a", "approve", "Approve") in PlanApprovalModal.BINDINGS
    assert ("a", "approve", "Tale") not in PlanApprovalModal.BINDINGS


def test_bindings_include_tale_action() -> None:
    assert ("t", "tale", "Tale") in PlanApprovalModal.BINDINGS


def test_bindings_include_custom_action_instead_of_options() -> None:
    assert ("c", "custom", "Custom") in PlanApprovalModal.BINDINGS
    assert ("A", "approve_options", "Options") not in PlanApprovalModal.BINDINGS


def test_action_approve_returns_pure_approve_choice() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    captured: list[PlanApprovalResult] = []

    def fake_dismiss(value: PlanApprovalResult) -> None:
        captured.append(value)

    modal.dismiss = fake_dismiss  # type: ignore[assignment]
    modal.action_approve()

    assert len(captured) == 1
    result = captured[0]
    assert result.action == "approve"
    assert result.choice == "approve"
    assert result.commit_plan is False
    assert result.run_coder is True


def test_action_tale_returns_tale_choice_with_commit() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    captured: list[PlanApprovalResult] = []

    def fake_dismiss(value: PlanApprovalResult) -> None:
        captured.append(value)

    modal.dismiss = fake_dismiss  # type: ignore[assignment]
    modal.action_tale()

    assert len(captured) == 1
    result = captured[0]
    assert result.action == "approve"
    assert result.choice == "tale"
    assert result.commit_plan is True
    assert result.run_coder is True


def test_action_approve_default_uses_authored_tier() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._default_choice = "epic"
    captured: list[PlanApprovalResult] = []
    modal.dismiss = captured.append  # type: ignore[assignment]

    modal.action_approve_default()

    assert captured[0].choice == "epic"
    assert captured[0].action == "epic"


def test_action_custom_uses_custom_modal_path() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._default_choice = "epic"
    called: list[object] = []

    def fake_push_approve_options(**kwargs: object) -> None:
        called.append(kwargs["choice"])

    modal._push_approve_options = fake_push_approve_options  # type: ignore[method-assign]
    modal.action_custom()

    assert called == ["epic"]


def test_remodeled_single_key_presets_submit_primary_approve() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._approval_extras = _approval_extras()
    modal._allowed_choices = frozenset(("approve", "tale"))
    captured: list[PlanApprovalResult] = []
    modal.dismiss = captured.append  # type: ignore[assignment]

    modal.action_approve()
    modal.action_tale()

    assert captured == [
        PlanApprovalResult(
            action="approve",
            commit_plan=False,
            run_coder=True,
            choice="approve",
        ),
        PlanApprovalResult(
            action="approve",
            commit_plan=True,
            run_coder=True,
            choice="approve",
        ),
    ]


async def test_remodeled_default_submits_current_checkbox_selection(tmp_path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        allowed_choices=("approve", "tale"),
        approval_extras=_approval_extras(),
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        extras = modal.query_one("#plan-approval-extras", GateExtrasSelectionList)
        assert extras.selected_extra_ids == ("commit_plan", "run_coder")
        extras.apply_selection(("commit_plan",))
        modal.action_approve_default()
        await pilot.pause()

    assert results == [
        PlanApprovalResult(
            action="approve",
            commit_plan=True,
            run_coder=False,
            choice="approve",
        )
    ]
