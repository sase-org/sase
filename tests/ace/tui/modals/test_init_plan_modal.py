"""Render and interaction tests for :class:`InitPlanModal`."""

from __future__ import annotations

from textual.widgets import Button

from sase.ace.testing import AcePage
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.modals.init_plan_modal import InitPlanDecision, InitPlanModal
from sase.ace.tui.modals.init_plan_modal_rendering import (
    init_plan_confirm_label,
    init_plan_renderable,
    init_plan_title,
)
from sase.ace.tui.modals.projects_pane_init import InitScope
from tests.ace.tui._plugins_browser_pane_helpers import _render

from .projects_pane_init_test_helpers import (
    action_row,
    check_payload,
    planner_row,
    project_plan,
)


def _single_update_payload():
    return check_payload(
        project_plan(
            "sase",
            display_name="sase",
            status="needs_attention",
            planners=(
                planner_row("config", label="Config", summary="Current"),
                planner_row(
                    "memory",
                    label="Memory",
                    summary="1 update",
                    has_changes=True,
                    actions=(
                        action_row(
                            "sase/task_types.json",
                            operation="update",
                            added=96,
                            removed=0,
                            diff_lines=(
                                "--- sase/task_types.json",
                                "+++ sase/task_types.json",
                                "@@ -1,0 +1,1 @@",
                                "+new line",
                            ),
                        ),
                    ),
                ),
                planner_row("repo", label="Repos", summary="Current"),
                planner_row("skills", label="Skills", summary="Current"),
            ),
        )
    )


def _mixed_all_payload():
    return check_payload(
        project_plan(
            "alpha",
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    summary="1 update",
                    has_changes=True,
                    actions=(action_row(operation="update", added=1),),
                ),
            ),
        ),
        project_plan("beta"),
        project_plan("gamma"),
        project_plan(
            "gone",
            display_name="Gone",
            status="failed",
            unavailable_reason="primary workspace is unavailable: /gone",
            planners=(),
        ),
        status="blocked",
    )


def _danger_payload():
    return check_payload(
        project_plan(
            "sase",
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    summary="1 overwrite",
                    has_changes=True,
                    actions=(
                        action_row(
                            "AGENTS.md",
                            operation="overwrite",
                            added=2,
                            removed=2,
                        ),
                    ),
                ),
            ),
        )
    )


def _tty_blocked_payload():
    return check_payload(
        project_plan(
            "sase",
            status="failed",
            planners=(
                planner_row(
                    "config",
                    summary="choose a machine identity",
                    has_changes=True,
                    runnable=False,
                    requires_tty=True,
                    blockers=["owner identity requires a TTY"],
                    actions=(action_row(operation="create"),),
                ),
            ),
        ),
        status="blocked",
    )


def test_single_project_update_render_and_button() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = _single_update_payload()
    modal = InitPlanModal(scope, payload)
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))

    assert "This can write files and may commit" in rendered
    assert "The memory step may commit and push" in rendered
    assert "sase init -p sase --yes" in rendered
    assert "MEMORY" in rendered
    assert "1 update" in rendered
    assert "+96 −0" in rendered
    assert "sase/task_types.json" in rendered
    assert "+new line" not in rendered
    assert "confirm re-plans fresh" in rendered
    assert init_plan_title(scope, payload) == "Initialize sase"
    assert init_plan_confirm_label(scope, payload) == "Initialize sase (y)"
    assert modal._kind is ConfirmKind.NEUTRAL


def test_mixed_all_projects_aggregate_and_current_summary() -> None:
    scope = InitScope.everything()
    payload = _mixed_all_payload()
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))

    assert "4 enabled" in rendered
    assert "1 need attention" in rendered
    assert "2 current" in rendered
    assert "1 unavailable" in rendered
    assert "canonical `sase init --all` inventory" in rendered
    assert "✓ Current  beta, gamma" in rendered
    assert "primary workspace is unavailable: /gone" in rendered
    assert init_plan_confirm_label(scope, payload) == (
        "Initialize 1 runnable project (y)"
    )


def test_danger_payload_uses_danger_kind() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = _danger_payload()
    modal = InitPlanModal(scope, payload)

    assert modal._kind is ConfirmKind.DANGER
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))
    assert "overwrite" in rendered.lower() or "AGENTS.md" in rendered


def test_tty_blocked_payload_annotates_blocker_and_disables_primary() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = _tty_blocked_payload()
    modal = InitPlanModal(scope, payload)
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))

    assert "owner identity requires a TTY" in rendered
    assert "(needs a terminal)" in rendered
    assert init_plan_confirm_label(scope, payload) == "Nothing runnable"
    assert modal._runnable == 0
    assert modal._kind is ConfirmKind.NEUTRAL


async def test_diff_toggle_shows_and_hides_unified_diff() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = _single_update_payload()
    async with AcePage() as page:
        modal = InitPlanModal(scope, payload)
        page.app.push_screen(modal)
        await page.expect_modal("InitPlanModal")
        await page.wait_for(lambda _s: len(modal.query("#init-plan-container")) > 0)

        hidden = _render(modal._preview_renderable())
        assert "+new line" not in hidden
        assert "d diff" in modal.query_one("#init-plan-container").border_subtitle

        await page.press("d")
        shown = _render(modal._preview_renderable())
        assert "+new line" in shown
        assert "d hide diffs" in modal.query_one("#init-plan-container").border_subtitle

        await page.press("d")
        hidden_again = _render(modal._preview_renderable())
        assert "+new line" not in hidden_again


async def test_nothing_runnable_confirm_is_noop() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = _tty_blocked_payload()
    results: list[InitPlanDecision | None] = []
    async with AcePage() as page:
        modal = InitPlanModal(scope, payload)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("InitPlanModal")
        await page.wait_for(lambda _s: len(modal.query("#init-plan-confirm")) > 0)

        confirm = modal.query_one("#init-plan-confirm", Button)
        assert confirm.disabled
        assert "Nothing runnable" in str(confirm.label)
        modal.action_confirm()
        await page.pause()
        assert results == []
        assert page.app.screen is modal
