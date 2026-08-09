"""Agents-tab metadata fold dispatch tests."""

import pytest

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui._agents_panel_fold_mode_helpers import _FoldApp, _press


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
    patch_folds = (
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
    ) == patch_folds


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
        "Fold levels shape clan, family, neighbor, and slow-call summaries"
    ]


def test_direct_dispatch_uses_configured_agent_and_patch_subkeys() -> None:
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
    patch = _FoldApp(tab="patches")
    patch._keymap_registry = registry

    _press(tribe, "x")
    _press(patch, "w")

    assert tribe.panel_fold_level is FoldLevel.EXHAUSTIVE
    assert patch.commits_collapsed is FoldLevel.EXPANDED
    assert patch.deltas_collapsed is FoldLevel.EXPANDED


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


@pytest.mark.parametrize(
    "section_id",
    ["agent-xprompt", "agent-prompt", "agent-reply"],
)
@pytest.mark.parametrize("key", ["a", "A"])
def test_family_conversation_sections_ignore_section_fold_commands(
    section_id: str,
    key: str,
) -> None:
    app = _FoldApp(clan=False, family=True)
    app.panel_fold_level = FoldLevel.EXPANDED
    app.section_id = section_id
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, key)

    assert app.panel_fold_level is FoldLevel.EXPANDED
    assert app._panel_fold_overrides.snapshot() == {"errors": FoldLevel.FULLY_EXPANDED}
    assert app.refresh_count == 1
    assert app.notifications == []


def test_agents_section_fold_noops_without_a_current_cached_section() -> None:
    app = _FoldApp()
    app.section_id = None

    _press(app, "a")

    assert app._panel_fold_overrides.snapshot() == {}
    assert app.refresh_count == 1


def test_agents_fold_does_not_mutate_patch_fold_state() -> None:
    app = _FoldApp()

    _press(app, "z")

    assert app.commits_collapsed is FoldLevel.COLLAPSED
    assert app.hooks_collapsed is FoldLevel.COLLAPSED


def test_patch_fold_dispatch_remains_unchanged() -> None:
    app = _FoldApp(tab="patches")

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
def test_patch_direct_level_sets_every_section_exactly(
    key: str,
    expected: FoldLevel,
) -> None:
    app = _FoldApp(tab="patches")
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


def test_patch_invalid_level_and_non_pr_context_preserve_all_state() -> None:
    app = _FoldApp(tab="patches")
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


def test_exhaustive_panel_state_does_not_enter_patch_cyclers() -> None:
    app = _FoldApp(panel_focused=True)
    _press(app, "z")
    _press(app, "z")
    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.EXHAUSTIVE

    app.current_tab = "patches"
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
        "Fold levels shape clan, family, neighbor, and slow-call summaries"
    ]
    assert clan.notifications == []
    assert family.notifications == []


def test_regular_agent_fold_change_stays_silent_when_neighbors_are_foldable() -> None:
    app = _FoldApp(clan=False, neighbor_count=2)

    _press(app, "Z")

    assert app.notifications == []


def test_regular_agent_fold_change_stays_silent_when_slow_calls_are_foldable() -> None:
    app = _FoldApp(clan=False, slow_tool_call_count=1)

    _press(app, "Z")

    assert app.notifications == []


def test_non_lane_agent_fold_change_stays_silent() -> None:
    app = _FoldApp(clan=False)
    app.selected_agent.is_workflow_child = True

    _press(app, "Z")

    assert app.notifications == []
