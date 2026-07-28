"""Behavioral coverage for the Artifacts rename and sub-tab scaffold."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.widgets import ContentSwitcher
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import (
    CHATS_ARTIFACT_ACTIONS,
    _ArtifactsProjectChoices,
)
from sase.ace.tui.commands import (
    build_command_catalog,
    execute_command,
    extract_command_context,
    is_command_available,
)
from sase.ace.tui.modals.inventory_project_picker import (
    InventoryProjectChoice,
    InventoryProjectPicker,
)
from sase.ace.tui.widgets import (
    ArtifactPlaceholderPane,
    ArtifactsChatsPane,
    ArtifactsPrsPane,
    CommitsPane,
)
from sase.ace.tui.widgets.artifacts import (
    ARTIFACTS_PANE_IDS,
    ARTIFACTS_SUBTAB_ORDER,
    ArtifactsView,
)
from sase.ace.tui.widgets.artifacts import ARTIFACTS_ACCENTS
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.vcs_log.models import VcsLogResult


@pytest.fixture(autouse=True)
def _stub_commits_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: VcsLogResult((), (), ()),
    )


async def test_subtab_keys_wrap_and_gate_hidden_pr_actions() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        view = page.query_one_widget("#changespecs-view", ArtifactsView)
        prs = page.query_one_widget("#artifacts-prs-pane", ArtifactsPrsPane)
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)

        assert view.current_subtab == "commits"
        assert prs.first_activation_count == 0
        assert prs.artifacts_active is False
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True

        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        assert switcher.current == ARTIFACTS_PANE_IDS["commits"]
        assert page.app.check_action("change_status", ()) is False
        assert page.app.check_action("next_changespec", ()) is False
        assert page.app.check_action("commits_refresh", ()) is True
        assert page.app.check_action("start_leader_mode", ()) is not False
        assert page.app.check_action("refresh_bugs", ()) is False
        assert page.app.check_action("plans_refresh", ()) is False
        assert page.app.check_action("chats_refresh", ()) is False
        footer = page.query_one_widget("#keybinding-content", Static)
        assert footer.content.plain == ""

        old_idx = page.app.current_idx
        await page.press("j")
        assert page.app.current_idx == old_idx

        await page.press("]")
        await page.expect_state("artifacts_subtab", "plans")
        assert commits.deactivation_count == 1

        await page.press("[")
        await page.expect_state("artifacts_subtab", "commits")
        assert commits.activation_count == 2

        await page.press("[")
        await page.expect_state("artifacts_subtab", "prs")
        assert page.app.check_action("commits_refresh", ()) is False
        assert prs.activation_count == 1
        assert commits.deactivation_count == 2
        assert page.app.focused is not None
        assert page.app.focused.id == "list-panel"

        await page.press("[")
        await page.expect_state("artifacts_subtab", "bugs")
        assert page.app.check_action("start_leader_mode", ()) is not False
        assert page.app.check_action("refresh_bugs", ()) is True

        await page.press("[")
        await page.expect_state("artifacts_subtab", "chats")
        assert page.app.check_action("chats_refresh", ()) is True
        chats = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        assert chats.first_activation_count == 1
        assert all(
            page.app.check_action(action, ()) is True
            for action in CHATS_ARTIFACT_ACTIONS
        )
        assert (
            page.query_one_widget("#chats-empty", Static).content
            == "No chat transcripts found."
        )
        await page.press("R")
        assert chats.refresh_request_count == 1


async def test_ctrl_space_dispatches_repeat_agent_from_every_subtab() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        calls: list[str] = []

        def record_repeat_agent() -> None:
            calls.append(page.app.current_artifacts_subtab)

        page.app.action_start_agent_from_changespec = record_repeat_agent  # type: ignore[method-assign]

        expected = ("commits", "plans", "chats", "bugs", "prs")
        for index, (key, subtab) in enumerate(
            zip(("1", "2", "3", "4", "5"), expected, strict=True),
            start=1,
        ):
            await page.press(key)
            await page.expect_state("artifacts_subtab", subtab)
            assert page.app.check_action("start_agent_from_changespec", ()) is True

            await page.press("ctrl+@")
            assert calls == list(expected[:index])


async def test_number_keys_jump_artifacts_without_entering_from_other_tabs() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        expected = ("commits", "plans", "chats", "bugs", "prs")

        for start_key in ("1", "2", "3", "4", "5"):
            await page.press(start_key)
            await page.expect_state("artifacts_subtab", expected[int(start_key) - 1])
            for key, subtab in zip(("1", "2", "3", "4", "5"), expected, strict=True):
                await page.press(key)
                await page.expect_state("artifacts_subtab", subtab)
                assert switcher.current == ARTIFACTS_PANE_IDS[subtab]

        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        remembered_subtab = page.app.current_artifacts_subtab
        for key in ("1", "2", "3", "4", "5", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "agents"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None

        await page.press("tab", "tab")
        await page.expect_state("tab", "axe")
        for key in ("1", "2", "3", "4", "5", "asterisk"):
            await page.press(key)
            await page.pause()
            assert page.app.current_tab == "axe"
            assert page.app.current_artifacts_subtab == remembered_subtab
            assert page.state["modal"] is None


async def test_click_message_and_reactivation_keep_lazy_pane_state() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        strip = page.query_one_widget("#artifacts-subtabs", PanelTabStrip)
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        assert (
            strip._build_content().plain
            == " 1 COMMITS  │  2 Plans  │  3 Chats  │  4 Bugs  │  5 PRs "
        )

        commits.set_class(True, "test-selection-state")

        strip.post_message(PanelTabStrip.TabClicked("bugs"))
        await page.expect_state("artifacts_subtab", "bugs")
        assert (
            strip._build_content().plain
            == " 1 Commits  │  2 Plans  │  3 Chats  │  4 BUGS  │  5 PRs "
        )
        strip.post_message(PanelTabStrip.TabClicked("commits"))
        await page.expect_state("artifacts_subtab", "commits")
        assert (
            strip._build_content().plain
            == " 1 COMMITS  │  2 Plans  │  3 Chats  │  4 Bugs  │  5 PRs "
        )

        assert commits.first_activation_count == 1
        assert commits.activation_count == 2
        assert commits.has_class("test-selection-state")


async def test_first_artifacts_entry_activates_default_without_hidden_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        commits_module,
        "run_vcs_log",
        lambda **_kwargs: calls.append("commits") or VcsLogResult((), (), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: calls.append("bugs"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda *_args, **_kwargs: calls.append("plans"),
    )

    async with AcePage(initial_tab="agents") as page:
        await page.pause()
        view = page.query_one_widget("#changespecs-view", ArtifactsView)
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        switcher = page.query_one_widget("#artifacts-content-switcher", ContentSwitcher)
        strip = page.query_one_widget("#artifacts-subtabs", PanelTabStrip)

        assert page.app.current_artifacts_subtab == "commits"
        assert view.current_subtab == "commits"
        assert switcher.current == ARTIFACTS_PANE_IDS["commits"]
        assert "1 COMMITS" in strip._build_content().plain
        assert commits.first_activation_count == 0
        assert commits.artifacts_active is False
        assert calls == []

        await page.press("tab")
        await page.expect_state("tab", "changespecs")
        await page.wait_for(lambda _state: calls == ["commits"])

        assert page.app.current_artifacts_subtab == "commits"
        assert view.current_subtab == "commits"
        assert switcher.current == ARTIFACTS_PANE_IDS["commits"]
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True
        assert page.app.check_action("commits_refresh", ()) is True
        assert page.app.check_action("change_status", ()) is False
        assert page.query_one_widget("#keybinding-content", Static).content.plain == ""


async def test_direct_artifacts_start_initializes_default_non_pr_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _ArtifactsProjectChoices((), (), {})
    inventory_calls = 0

    def collect() -> _ArtifactsProjectChoices:
        nonlocal inventory_calls
        inventory_calls += 1
        return result

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        collect,
    )

    async with AcePage(initial_tab="changespecs") as page:
        commits = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )

        assert page.app.current_artifacts_subtab == "commits"
        assert commits.first_activation_count == 1
        assert commits.artifacts_active is True
        assert inventory_calls == 1
        assert page.query_one_widget("#keybinding-content", Static).content.plain == ""


async def test_scope_inventory_is_lazy_and_picker_updates_all_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
            InventoryProjectChoice(
                project_key="beta",
                display_name="Beta",
                state="disabled",
            ),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha", "beta": "Beta"},
    )
    calls = 0

    def collect() -> _ArtifactsProjectChoices:
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        collect,
    )

    async with AcePage(initial_tab="agents") as page:
        await page.pause()
        assert calls == 0

        await page.press("tab")
        await page.wait_for(
            lambda _state: page.app._artifacts_project_choices is result
        )
        assert calls == 1
        assert page.app.artifacts_project_scope == "alpha"

        for pane in page.app.query(ArtifactPlaceholderPane):
            assert pane.project_scope == "alpha"
        commits = page.app.query_one(CommitsPane)
        assert commits.project_scope == "alpha"
        assert commits.filters.project == "alpha"
        assert page.app.query_one(ArtifactsChatsPane).project_scope == "alpha"

        retained_filters = replace(
            commits.filters,
            repos=("plans",),
            authors=("Ada",),
            limit=5,
            text=("fix",),
        )
        commits._commit_filter_values(retained_filters, close_session=False)
        commits.set_project_scope("beta")
        await page.wait_for(lambda _state: commits.filters.project == "beta")
        assert commits.filters == replace(retained_filters, project="beta")
        assert page.app.artifacts_project_scope == "alpha"

        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        picker = page.app.screen
        assert isinstance(picker, InventoryProjectPicker)
        assert picker.query_one("#inventory-project-picker-list").highlighted == 2
        picker.query_one("#inventory-project-picker-list").highlighted = 0
        picker.action_select_highlighted()
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app.artifacts_project_scope is None)
        assert page.app.artifacts_project_scope is None
        assert commits.filters == replace(retained_filters, project=None)


async def test_palette_has_direct_jump_for_every_artifacts_subtab() -> None:
    async with AcePage(initial_tab="agents") as page:
        catalog = build_command_catalog(page.app._keymap_registry)
        by_id = {spec.id: spec for spec in catalog}
        expected = {
            "artifacts.prs",
            "artifacts.commits",
            "artifacts.bugs",
            "artifacts.plans",
            "artifacts.chats",
        }
        assert expected <= by_id.keys()
        assert {f"app.{action}" for action in CHATS_ARTIFACT_ACTIONS} <= by_id.keys()
        assert [
            by_id[f"artifacts.{subtab}"].key_display
            for subtab in (
                "commits",
                "plans",
                "chats",
                "bugs",
                "prs",
            )
        ] == ["1", "2", "3", "4", "5"]

        execute_command(page.app, by_id["artifacts.bugs"])
        await page.expect_state("tab", "changespecs")
        await page.expect_state("artifacts_subtab", "bugs")

        context = extract_command_context(page.app)
        assert context.artifacts_subtab == "bugs"
        assert is_command_available(by_id["artifacts.prs"], context)
        assert not is_command_available(by_id["app.change_status"], context)
        assert not is_command_available(by_id["app.commits_refresh"], context)

        execute_command(page.app, by_id["artifacts.commits"])
        await page.expect_state("artifacts_subtab", "commits")
        context = extract_command_context(page.app)
        assert is_command_available(by_id["app.commits_refresh"], context)
        assert not is_command_available(by_id["app.refresh_bugs"], context)

        execute_command(page.app, by_id["artifacts.chats"])
        await page.expect_state("artifacts_subtab", "chats")
        context = extract_command_context(page.app)
        assert is_command_available(by_id["app.chats_refresh"], context)
        assert not is_command_available(by_id["app.plans_refresh"], context)


def test_subtab_strip_labels_and_accents_cover_all_panes() -> None:
    view = ArtifactsView(id="changespecs-view")
    # The mounted interaction tests cover rendering; this unit assertion keeps
    # the public pane-id map exhaustive for later feature phases.
    assert ARTIFACTS_SUBTAB_ORDER[:4] == ("commits", "plans", "chats", "bugs")
    assert ARTIFACTS_SUBTAB_ORDER == ("commits", "plans", "chats", "bugs", "prs")
    assert tuple(ARTIFACTS_PANE_IDS) == (
        "prs",
        "commits",
        "bugs",
        "plans",
        "chats",
    )
    assert ARTIFACTS_ACCENTS == {
        "prs": "#00D7AF",
        "commits": "#FFD700",
        "bugs": "#FF5F5F",
        "plans": "#AF87FF",
        "chats": "#5FAFFF",
    }
    assert view.current_subtab == "commits"
