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
    danger_payload,
    mixed_all_payload,
    single_update_payload,
    tty_blocked_payload,
)


def test_single_project_update_render_and_button() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = single_update_payload()
    modal = InitPlanModal(scope, payload)
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))

    assert "This can write files and may commit" in rendered
    assert "The memory step may commit and push" in rendered
    assert "sase init -p sase --yes" in rendered
    assert "MEMORY" in rendered
    assert "1 update" in rendered
    assert "+96 −0" in rendered
    assert "sase/task_types.json" in rendered
    assert '"bug"' not in rendered
    assert "confirm re-plans fresh" in rendered
    assert init_plan_title(scope, payload) == "Initialize sase"
    assert init_plan_confirm_label(scope, payload) == "Initialize sase (y)"
    assert modal._kind is ConfirmKind.NEUTRAL


def test_mixed_all_projects_aggregate_and_current_summary() -> None:
    scope = InitScope.everything()
    payload = mixed_all_payload()
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
    payload = danger_payload()
    modal = InitPlanModal(scope, payload)

    assert modal._kind is ConfirmKind.DANGER
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))
    assert "overwrite" in rendered.lower() or "AGENTS.md" in rendered


def test_tty_blocked_payload_annotates_blocker_and_disables_primary() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = tty_blocked_payload()
    modal = InitPlanModal(scope, payload)
    rendered = _render(init_plan_renderable(scope, payload, show_diffs=False))

    assert "owner identity requires a TTY" in rendered
    assert "(needs a terminal)" in rendered
    assert init_plan_confirm_label(scope, payload) == "Nothing runnable"
    assert modal._runnable == 0
    assert modal._kind is ConfirmKind.NEUTRAL
    assert modal._show_terminal is True


def test_terminal_button_absent_without_tty_blockers() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = single_update_payload()
    modal = InitPlanModal(scope, payload)

    assert modal._show_terminal is False


async def test_terminal_button_shown_and_dismisses_with_terminal_decision() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = tty_blocked_payload()
    results: list[InitPlanDecision | None] = []
    async with AcePage() as page:
        modal = InitPlanModal(scope, payload)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("InitPlanModal")
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)

        terminal_button = modal.query_one("#init-plan-terminal", Button)
        assert "Run in terminal" in str(terminal_button.label)
        assert "t run in terminal" in (
            modal.query_one("#init-plan-container").border_subtitle
        )

        await page.press("t")
        await page.pause()
        assert results == [InitPlanDecision(action="terminal")]


async def test_terminal_key_is_noop_without_tty_blockers() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = single_update_payload()
    results: list[InitPlanDecision | None] = []
    async with AcePage() as page:
        modal = InitPlanModal(scope, payload)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("InitPlanModal")
        await page.wait_for(lambda _s: len(modal.query("#init-plan-confirm")) > 0)
        assert len(modal.query("#init-plan-terminal")) == 0

        await page.press("t")
        await page.pause()
        assert results == []
        assert page.app.screen is modal


async def test_diff_toggle_shows_and_hides_unified_diff() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = single_update_payload()
    async with AcePage() as page:
        modal = InitPlanModal(scope, payload)
        page.app.push_screen(modal)
        await page.expect_modal("InitPlanModal")
        await page.wait_for(lambda _s: len(modal.query("#init-plan-container")) > 0)

        hidden = _render(modal._preview_renderable())
        assert '"bug"' not in hidden
        assert "d diff" in modal.query_one("#init-plan-container").border_subtitle

        await page.press("d")
        shown = _render(modal._preview_renderable())
        assert '"bug"' in shown
        assert "d hide diffs" in modal.query_one("#init-plan-container").border_subtitle

        await page.press("d")
        hidden_again = _render(modal._preview_renderable())
        assert '"bug"' not in hidden_again


async def test_nothing_runnable_confirm_is_noop() -> None:
    scope = InitScope.for_projects(("sase",), ("sase",))
    payload = tty_blocked_payload()
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
