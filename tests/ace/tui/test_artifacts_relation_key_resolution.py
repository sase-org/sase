"""Key resolution for `.` and `X` across ACE tabs."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui._artifact_tab_actions import keymap_actions_by_key
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.keymaps import load_keymap_registry


class _KeyResolutionApp:
    class _Screen:
        _blocks_global_config_center_open = False

    def __init__(
        self,
        *,
        tab: str,
        pane_key: str = "patches",
    ) -> None:
        self.screen = self._Screen()
        self.focused = None
        self._screen_stack = ()
        self.current_tab = tab
        self.current_artifacts_pane_key = pane_key
        self.current_artifacts_subtab = pane_key
        self.active_artifacts_contract = (
            compile_builtin_contract(pane_key, label=pane_key, icon="x", accent="#0")
            if tab == "artifacts"
            else None
        )

    def _prompt_input_active(self) -> bool:
        return False


def _available_for_key(app: object, key: str) -> tuple[str, ...]:
    registry = load_keymap_registry({})
    owners = keymap_actions_by_key(registry.app).get(key, ())
    return tuple(
        owner
        for owner in owners
        if check_app_action(app, owner, (), lambda _action, _params: True) is not False
    )


def test_full_stop_resolves_to_one_action_per_tab() -> None:
    artifacts = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    beads = _KeyResolutionApp(tab="artifacts", pane_key="beads")
    agents = _KeyResolutionApp(tab="agents")
    axe = _KeyResolutionApp(tab="axe")

    assert _available_for_key(artifacts, "full_stop") == ("toggle_relation_panel",)
    assert _available_for_key(beads, "full_stop") == ("toggle_relation_panel",)
    assert _available_for_key(agents, "full_stop") == ("toggle_hide_reverted",)
    assert _available_for_key(axe, "full_stop") == ("toggle_hide_reverted",)


def test_capital_x_resolves_to_one_action_per_tab() -> None:
    patches = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    beads = _KeyResolutionApp(tab="artifacts", pane_key="beads")
    agents = _KeyResolutionApp(tab="agents")
    axe = _KeyResolutionApp(tab="axe")

    assert _available_for_key(patches, "X") == ("patches_toggle_reverted",)
    assert _available_for_key(beads, "X") == ()
    assert _available_for_key(agents, "X") == ("open_agent_cleanup_panel",)
    assert _available_for_key(axe, "X") == ("open_agent_cleanup_panel",)


def test_toggle_hide_reverted_is_unavailable_on_artifacts() -> None:
    app = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    assert (
        check_app_action(app, "toggle_hide_reverted", (), lambda _a, _p: True) is False
    )


def test_open_agent_cleanup_panel_is_unavailable_off_agents_and_axe() -> None:
    app = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    assert (
        check_app_action(app, "open_agent_cleanup_panel", (), lambda _a, _p: True)
        is False
    )


def test_patches_toggle_reverted_is_patches_only() -> None:
    patches = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    beads = _KeyResolutionApp(tab="artifacts", pane_key="beads")
    agents = _KeyResolutionApp(tab="agents")

    assert (
        check_app_action(patches, "patches_toggle_reverted", (), lambda _a, _p: True)
        is not False
    )
    assert (
        check_app_action(beads, "patches_toggle_reverted", (), lambda _a, _p: True)
        is False
    )
    assert (
        check_app_action(agents, "patches_toggle_reverted", (), lambda _a, _p: True)
        is False
    )


def test_artifacts_paging_chords_resolve_only_on_artifacts() -> None:
    artifacts = _KeyResolutionApp(tab="artifacts", pane_key="beads")
    patches = _KeyResolutionApp(tab="artifacts", pane_key="patches")
    agents = _KeyResolutionApp(tab="agents")

    assert _available_for_key(artifacts, "ctrl+j") == ("artifacts_load_more",)
    assert _available_for_key(artifacts, "ctrl+k") == ("artifacts_unload",)
    assert _available_for_key(patches, "ctrl+j") == ("artifacts_load_more",)
    assert _available_for_key(patches, "ctrl+k") == ("artifacts_unload",)
    assert _available_for_key(agents, "ctrl+j") == ("next_agent_metadata_section",)
    assert _available_for_key(agents, "ctrl+k") == ("prev_agent_metadata_section",)


def test_toggle_relation_panel_is_artifacts_only() -> None:
    artifacts = _KeyResolutionApp(tab="artifacts", pane_key="files")
    agents = SimpleNamespace(
        screen=_KeyResolutionApp._Screen(),
        focused=None,
        _screen_stack=(),
        current_tab="agents",
        current_artifacts_pane_key="patches",
        current_artifacts_subtab="patches",
        active_artifacts_contract=None,
        _prompt_input_active=lambda: False,
    )

    assert (
        check_app_action(artifacts, "toggle_relation_panel", (), lambda _a, _p: True)
        is not False
    )
    assert (
        check_app_action(agents, "toggle_relation_panel", (), lambda _a, _p: True)
        is False
    )
