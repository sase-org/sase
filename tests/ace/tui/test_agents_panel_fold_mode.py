"""Agents-tab metadata fold dispatch and footer tests."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.navigation._fold import FoldNavigationMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import (
    FoldLevel,
    SectionFoldStateManager,
    cycle_forward,
)
from sase.ace.tui.models.fold_scale import (
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
)
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


class _FoldApp(FoldNavigationMixin):
    def __init__(
        self,
        *,
        tab: str = "agents",
        clan: bool = True,
        family: bool = False,
        panel_focused: bool = False,
        has_agent: bool = True,
        neighbor_count: int = 0,
    ) -> None:
        self.current_tab = tab
        self.current_artifacts_subtab = "prs"
        self._fold_mode_active = False
        self._keymap_registry = load_keymap_registry({})
        self.panel_fold_level = FoldLevel.COLLAPSED
        self._panel_fold_overrides = SectionFoldStateManager()
        self.commits_collapsed = FoldLevel.COLLAPSED
        self.hooks_collapsed = FoldLevel.COLLAPSED
        self.mentors_collapsed = FoldLevel.COLLAPSED
        self.timestamps_collapsed = FoldLevel.COLLAPSED
        self.deltas_collapsed = FoldLevel.COLLAPSED
        self.section_id: str | None = "errors"
        self.selected_agent = (
            SimpleNamespace(
                is_clan_container=clan,
                is_family_container_row=family,
                is_family_root_entry=family,
                is_workflow_child=False,
                is_hidden_step=False,
                is_family_member_child=False,
                presented_agent_name="fold-test",
                presented_identity_name="fold-test",
            )
            if has_agent
            else None
        )
        self.refresh_count = 0
        self.notifications: list[str] = []
        self.panel_focused = panel_focused
        self.neighbor_count = neighbor_count

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def _current_agent_metadata_section_id(self) -> str | None:
        return self.section_id

    def _get_selected_agent(self) -> object | None:
        return self.selected_agent

    def _selected_agent_neighbor_count(self, _agent: object) -> int:
        return self.neighbor_count

    def _resolve_focused_collapsed_panel(self) -> object | None:
        return object() if self.panel_focused else None

    def notify(self, message: str) -> None:
        self.notifications.append(message)


def _press(app: _FoldApp, key: str) -> None:
    app._fold_mode_active = True
    assert app._handle_fold_key(key) is True
    assert app._fold_mode_active is False


def test_agents_panel_level_cycles_forward_and_toggles_extremes() -> None:
    app = _FoldApp()
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.EXPANDED
    assert app._panel_fold_overrides.snapshot() == {}

    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.COLLAPSED

    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.COLLAPSED


def test_family_panel_level_cycles_within_two_level_scale() -> None:
    app = _FoldApp(clan=False, family=True)

    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.EXPANDED
    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.EXPANDED


def test_whole_panel_focus_cycles_within_four_level_tribe_scale() -> None:
    app = _FoldApp(panel_focused=True)

    for expected in (
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
        FoldLevel.EXHAUSTIVE,
        FoldLevel.COLLAPSED,
    ):
        _press(app, "z")
        assert app.panel_fold_level is expected

    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.EXHAUSTIVE

    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.COLLAPSED


@pytest.mark.parametrize(
    ("app", "level", "expected"),
    [
        (
            _FoldApp(clan=False, family=True),
            FoldLevel.COLLAPSED,
            FoldLevel.FULLY_EXPANDED,
        ),
        (
            _FoldApp(clan=False, family=True),
            FoldLevel.EXPANDED,
            FoldLevel.FULLY_EXPANDED,
        ),
        (
            _FoldApp(clan=False, family=True),
            FoldLevel.FULLY_EXPANDED,
            FoldLevel.EXPANDED,
        ),
        (_FoldApp(clan=False, family=True), FoldLevel.EXHAUSTIVE, FoldLevel.EXPANDED),
        (_FoldApp(), FoldLevel.COLLAPSED, FoldLevel.FULLY_EXPANDED),
        (_FoldApp(), FoldLevel.EXPANDED, FoldLevel.FULLY_EXPANDED),
        (_FoldApp(), FoldLevel.FULLY_EXPANDED, FoldLevel.COLLAPSED),
        (_FoldApp(), FoldLevel.EXHAUSTIVE, FoldLevel.COLLAPSED),
        (_FoldApp(panel_focused=True), FoldLevel.COLLAPSED, FoldLevel.EXHAUSTIVE),
        (_FoldApp(panel_focused=True), FoldLevel.EXPANDED, FoldLevel.EXHAUSTIVE),
        (
            _FoldApp(panel_focused=True),
            FoldLevel.FULLY_EXPANDED,
            FoldLevel.EXHAUSTIVE,
        ),
        (_FoldApp(panel_focused=True), FoldLevel.EXHAUSTIVE, FoldLevel.COLLAPSED),
    ],
)
def test_agents_toggle_all_uses_active_scale_extremes(
    app: _FoldApp,
    level: FoldLevel,
    expected: FoldLevel,
) -> None:
    app.panel_fold_level = level
    app._panel_fold_overrides.set("errors", FoldLevel.EXPANDED)
    changespec_folds = (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    )

    _press(app, "Z")

    assert app.panel_fold_level is expected
    assert app._panel_fold_overrides.snapshot() == {}
    assert app.refresh_count == 1
    assert (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    ) == changespec_folds


@pytest.mark.parametrize(
    ("app", "key", "expected"),
    [
        (_FoldApp(clan=False, family=True), "1", FoldLevel.EXPANDED),
        (_FoldApp(clan=False, family=True), "2", FoldLevel.FULLY_EXPANDED),
        (_FoldApp(), "1", FoldLevel.COLLAPSED),
        (_FoldApp(), "2", FoldLevel.EXPANDED),
        (_FoldApp(), "3", FoldLevel.FULLY_EXPANDED),
        (_FoldApp(clan=False), "3", FoldLevel.FULLY_EXPANDED),
        (_FoldApp(panel_focused=True), "4", FoldLevel.EXHAUSTIVE),
    ],
)
def test_agents_direct_levels_select_exact_active_scale_position(
    app: _FoldApp,
    key: str,
    expected: FoldLevel,
) -> None:
    app.panel_fold_level = FoldLevel.EXHAUSTIVE

    _press(app, key)

    assert app.panel_fold_level is expected


def test_valid_direct_panel_level_clears_overrides_and_notifies_regular_scope() -> None:
    app = _FoldApp(clan=False)
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, "2")

    assert app.panel_fold_level is FoldLevel.EXPANDED
    assert app._panel_fold_overrides.snapshot() == {}
    assert app.notifications == [
        "Fold levels shape clan, family, and neighbor summaries"
    ]


def test_direct_dispatch_uses_configured_agent_and_changespec_subkeys() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {
                            "set_level_2": "w",
                            "agents": {"set_level_4": "x"},
                        }
                    }
                }
            }
        }
    )
    tribe = _FoldApp(panel_focused=True)
    tribe._keymap_registry = registry
    changespec = _FoldApp(tab="changespecs")
    changespec._keymap_registry = registry

    _press(tribe, "x")
    _press(changespec, "w")

    assert tribe.panel_fold_level is FoldLevel.EXHAUSTIVE
    assert changespec.commits_collapsed is FoldLevel.EXPANDED
    assert changespec.deltas_collapsed is FoldLevel.EXPANDED


def test_invalid_family_direct_level_preserves_state_and_overrides() -> None:
    app = _FoldApp(clan=False, family=True)
    app.panel_fold_level = FoldLevel.EXPANDED
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, "3")

    assert app.panel_fold_level is FoldLevel.EXPANDED
    assert app._panel_fold_overrides.snapshot() == {"errors": FoldLevel.FULLY_EXPANDED}
    assert app.notifications == []


def test_agents_fold_context_without_selection_is_a_noop() -> None:
    app = _FoldApp(has_agent=False)
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, "1")

    assert app.panel_fold_level is FoldLevel.COLLAPSED
    assert app._panel_fold_overrides.snapshot() == {"errors": FoldLevel.FULLY_EXPANDED}


def test_agents_section_cycle_and_toggle_use_effective_panel_level() -> None:
    app = _FoldApp()

    _press(app, "a")
    assert app._panel_fold_overrides.get_override("errors") is FoldLevel.EXPANDED

    _press(app, "A")
    assert app._panel_fold_overrides.get_override("errors") is FoldLevel.COLLAPSED
    _press(app, "A")
    assert app._panel_fold_overrides.get_override("errors") is (
        FoldLevel.FULLY_EXPANDED
    )


def test_family_section_cycle_and_toggle_use_family_scale() -> None:
    app = _FoldApp(clan=False, family=True)

    _press(app, "a")
    assert app._panel_fold_overrides.get_override("errors") is (
        FoldLevel.FULLY_EXPANDED
    )
    _press(app, "A")
    assert app._panel_fold_overrides.get_override("errors") is FoldLevel.EXPANDED


def test_agents_section_fold_noops_without_a_current_cached_section() -> None:
    app = _FoldApp()
    app.section_id = None

    _press(app, "a")

    assert app._panel_fold_overrides.snapshot() == {}
    assert app.refresh_count == 1


def test_agents_fold_does_not_mutate_changespec_fold_state() -> None:
    app = _FoldApp()

    _press(app, "z")

    assert app.commits_collapsed is FoldLevel.COLLAPSED
    assert app.hooks_collapsed is FoldLevel.COLLAPSED


def test_changespec_fold_dispatch_remains_unchanged() -> None:
    app = _FoldApp(tab="changespecs")

    _press(app, "c")

    assert app.commits_collapsed is FoldLevel.EXPANDED
    assert app.panel_fold_level is FoldLevel.COLLAPSED


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("1", FoldLevel.COLLAPSED),
        ("2", FoldLevel.EXPANDED),
        ("3", FoldLevel.FULLY_EXPANDED),
    ],
)
def test_changespec_direct_level_sets_every_section_exactly(
    key: str,
    expected: FoldLevel,
) -> None:
    app = _FoldApp(tab="changespecs")
    app.commits_collapsed = FoldLevel.EXPANDED
    app.hooks_collapsed = FoldLevel.FULLY_EXPANDED
    app.mentors_collapsed = FoldLevel.COLLAPSED
    app.timestamps_collapsed = FoldLevel.EXPANDED
    app.deltas_collapsed = FoldLevel.FULLY_EXPANDED

    _press(app, key)

    assert (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    ) == (expected,) * 5
    assert app.panel_fold_level is FoldLevel.COLLAPSED


def test_changespec_invalid_level_and_non_pr_context_preserve_all_state() -> None:
    app = _FoldApp(tab="changespecs")
    before = (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    )

    _press(app, "4")
    assert (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    ) == before

    app.current_artifacts_subtab = "commits"
    _press(app, "2")
    assert (
        app.commits_collapsed,
        app.hooks_collapsed,
        app.mentors_collapsed,
        app.timestamps_collapsed,
        app.deltas_collapsed,
    ) == before


def test_exhaustive_panel_state_does_not_enter_changespec_cyclers() -> None:
    app = _FoldApp(panel_focused=True)
    _press(app, "z")
    _press(app, "z")
    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.EXHAUSTIVE

    app.current_tab = "changespecs"
    _press(app, "c")

    assert app.commits_collapsed is FoldLevel.EXPANDED
    assert app.panel_fold_level is FoldLevel.EXHAUSTIVE


def test_regular_agent_fold_change_shows_scope_toast_but_containers_do_not() -> None:
    regular = _FoldApp(clan=False)
    clan = _FoldApp(clan=True)
    family = _FoldApp(clan=False, family=True)

    _press(regular, "Z")
    _press(clan, "Z")
    _press(family, "Z")

    assert regular.notifications == [
        "Fold levels shape clan, family, and neighbor summaries"
    ]
    assert clan.notifications == []
    assert family.notifications == []


def test_regular_agent_fold_change_stays_silent_when_neighbors_are_foldable() -> None:
    app = _FoldApp(clan=False, neighbor_count=2)

    _press(app, "Z")

    assert app.notifications == []


def test_non_lane_agent_fold_change_stays_silent() -> None:
    app = _FoldApp(clan=False)
    app.selected_agent.is_workflow_child = True

    _press(app, "Z")

    assert app.notifications == []


def test_agents_fold_footer_uses_nested_agent_submap() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(
            current_tab="agents",
            fold_scale=CLAN_FOLD_SCALE,
        )

    assert update.call_args.args == (
        [
            ("1", "level 1"),
            ("2", "level 2"),
            ("3", "level 3"),
            ("z", "level forward"),
            ("Z", "toggle all"),
            ("a", "section forward"),
            ("A", "toggle section"),
        ],
    )
    assert update.call_args.kwargs == {"mode_label": "FOLD"}


@pytest.mark.parametrize(
    ("scale", "direct_keys"),
    [
        (FAMILY_FOLD_SCALE, ["1", "2"]),
        (CLAN_FOLD_SCALE, ["1", "2", "3"]),
        (TRIBE_FOLD_SCALE, ["1", "2", "3", "4"]),
    ],
)
def test_agents_fold_footer_direct_hints_match_active_scale(
    scale: tuple[FoldLevel, ...],
    direct_keys: list[str],
) -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(current_tab="agents", fold_scale=scale)

    bindings = update.call_args.args[0]
    assert [key for key, _label in bindings[: len(scale)]] == direct_keys


def test_fold_footer_uses_configured_direct_subkeys_in_each_context() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {
                            "set_level_2": "w",
                            "agents": {"set_level_3": "e"},
                        }
                    }
                }
            }
        }
    )
    footer = KeybindingFooter()
    footer.set_keymap_registry(registry)

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(
            current_tab="agents",
            fold_scale=CLAN_FOLD_SCALE,
        )
    assert update.call_args.args[0][:3] == [
        ("1", "level 1"),
        ("2", "level 2"),
        ("e", "level 3"),
    ]

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(current_tab="changespecs")
    assert update.call_args.args[0][:3] == [
        ("1", "level 1"),
        ("w", "level 2"),
        ("3", "level 3"),
    ]


def _mounted_clan_agents(tmp_path: Path) -> list[Agent]:
    artifacts = tmp_path / "phase-artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "#review mounted clan segment\n",
        encoding="utf-8",
    )
    (artifacts / "01_prompt.md").write_text(
        "Exercise every fold chord.\n",
        encoding="utf-8",
    )
    response = artifacts / "response.md"
    response.write_text("Mounted clan reply.\n", encoding="utf-8")
    generation = "20260718120000"
    phase = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="mounted-phase",
        project_file="/tmp/mounted.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        stop_time=datetime(2026, 7, 18, 12, 3, 0),
        raw_suffix="20260718120000-phase",
        agent_name="sase-mounted.phase",
        agent_clan="sase-mounted",
        agent_clan_generation=generation,
        clan_tribe="epic",
        artifacts_dir=str(artifacts),
        response_path=str(response),
        error_message="Mounted representative failure",
        output_variables={"report": "fold exercise complete"},
        model="gpt-5",
    )
    land = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="mounted-land",
        project_file="/tmp/mounted.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 18, 12, 3, 0),
        raw_suffix="20260718120300-land",
        agent_name="sase-mounted.land",
        agent_clan="sase-mounted",
        agent_clan_generation=generation,
        clan_tribe="epic",
        model="gpt-5",
    )
    return sort_and_reorder([phase, land], [])


@pytest.mark.asyncio
async def test_mounted_clan_fold_chords_zoom_and_changespec_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_mounted_clan_agents(tmp_path))

    async with AcePage(
        query='"mounted"',
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        changespec_folds = (
            page.app.commits_collapsed,
            page.app.hooks_collapsed,
            page.app.mentors_collapsed,
            page.app.timestamps_collapsed,
            page.app.deltas_collapsed,
        )
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        assert selected.is_clan_container
        assert selected.clan_tribes == ("epic",)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        cached = get_cached_clan_section_snapshot(panel, selected)
        assert cached is not None and cached.disk is not None
        assert len(cached.disk.replies) == 1
        assert len(cached.disk.prompts) == 2

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await page.press("z", "Z")
        assert page.app.panel_fold_level is FoldLevel.FULLY_EXPANDED
        await page.press("z", "Z")
        assert page.app.panel_fold_level is FoldLevel.COLLAPSED

        await wait_for_visual_idle(page)
        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "members"

        await page.press("z", "a")
        assert page.app._panel_fold_overrides.get_override("members") is (
            FoldLevel.EXPANDED
        )
        await wait_for_visual_idle(page)
        assert panel.active_section_identity == "members"

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "member:sase-mounted.phase"

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "member:sase-mounted.land"

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "errors"
        await page.press("z", "A")
        assert page.app._panel_fold_overrides.get_override("errors") is (
            FoldLevel.FULLY_EXPANDED
        )
        assert (
            page.app.commits_collapsed,
            page.app.hooks_collapsed,
            page.app.mentors_collapsed,
            page.app.timestamps_collapsed,
            page.app.deltas_collapsed,
        ) == changespec_folds

        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await page.press("z")
        await page.expect_no_modal()

        await page.press("tab")
        await page.expect_state("tab", "changespecs")
        await page.press("z", "c")
        assert page.app.commits_collapsed is cycle_forward(changespec_folds[0])
