"""Card-block ( / ) keys: defaults, gating, footer, palette, help and search."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui._artifact_tab_actions import keymap_actions_by_key
from sase.ace.tui.actions.agents._deck_search_host import deck_structural_exit_keys
from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.commands._availability_agents import agents_available
from sase.ace.tui.commands.context import extract_command_context
from sase.ace.tui.commands.types import CommandContext, CommandSpec
from sase.ace.tui.keymaps import (
    build_app_bindings,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import agents_bindings
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.models.agent import Agent, AgentType
from tests._keymaps_helpers import default_app_keymaps


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
    )


def _gating_app(
    *,
    tab: str = "agents",
    navigable: bool = False,
    prompt: bool = False,
    pane: str = "patches",
):
    panel = SimpleNamespace(card_blocks_navigable=navigable)
    area = SimpleNamespace(focused_panel=lambda: panel)
    detail = SimpleNamespace(deck_area=area)

    class _App:
        current_tab = tab
        current_artifacts_pane_key = pane
        _screen_stack = ("home",)

        def _prompt_input_active(self) -> bool:
            return prompt

        def query_one(self, *args, **kwargs):
            return detail

    return _App()


def test_card_block_default_keys() -> None:
    reg = load_keymap_registry({})
    assert reg.app.prev_card_block == "left_parenthesis"
    assert reg.app.next_card_block == "right_parenthesis"


def test_card_block_bindings_share_paren_keys_with_files_versions_in_order() -> None:
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["prev_card_block"].key == "left_parenthesis"
    assert by_action["next_card_block"].key == "right_parenthesis"
    assert [b.action for b in bindings if b.key == "right_parenthesis"] == [
        "files_next_version",
        "next_card_block",
    ]
    assert [b.action for b in bindings if b.key == "left_parenthesis"] == [
        "files_prev_version",
        "prev_card_block",
    ]
    fallback = {b.action: b for b in DEFAULT_BINDINGS}
    assert fallback["prev_card_block"].key == "left_parenthesis"
    assert fallback["next_card_block"].key == "right_parenthesis"


def test_card_block_custom_key_sharing_files_version_key_is_accepted() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "prev_card_block": "f11",
                    "files_prev_version": "f11",
                    "next_card_block": "f12",
                    "files_next_version": "f12",
                }
            }
        }
    )
    assert reg.app.prev_card_block == "f11"
    assert reg.app.files_prev_version == "f11"
    assert reg.app.next_card_block == "f12"
    assert reg.app.files_next_version == "f12"


def test_legacy_bracket_card_block_override_warns_and_is_honored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An explicit [ / ] card-block binding keeps working with a warning."""
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "app": {
                        "prev_card_block": "left_square_bracket",
                        "next_card_block": "right_square_bracket",
                    }
                }
            }
        )
    assert reg.app.prev_card_block == "left_square_bracket"
    assert reg.app.next_card_block == "right_square_bracket"
    assert "Card-block stepping moved from [ / ] to ( / )" in caplog.text
    assert "left_parenthesis" in caplog.text


def test_legacy_bracket_card_block_override_does_not_revert(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The legacy share with the Artifacts sub-tab cycle keys is allowed."""
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {"keymaps": {"app": {"next_card_block": "right_square_bracket"}}}
        )
    assert reg.app.next_card_block == "right_square_bracket"
    assert reg.app.cycle_artifacts_subtab == "right_square_bracket"
    assert not any("Duplicate key" in r.message for r in caplog.records)


def test_card_block_gating_needs_agents_tab_and_navigable_panel() -> None:
    assert (
        check_app_action(
            _gating_app(navigable=True), "next_card_block", (), lambda _a, _p: None
        )
        is not False
    )
    assert (
        check_app_action(
            _gating_app(navigable=True), "prev_card_block", (), lambda _a, _p: None
        )
        is not False
    )
    assert (
        check_app_action(
            _gating_app(navigable=False), "next_card_block", (), lambda _a, _p: None
        )
        is False
    )
    assert (
        check_app_action(
            _gating_app(tab="artifacts", navigable=True),
            "next_card_block",
            (),
            lambda _a, _p: None,
        )
        is False
    )
    assert (
        check_app_action(
            _gating_app(navigable=True, prompt=True),
            "next_card_block",
            (),
            lambda _a, _p: None,
        )
        is False
    )


def test_bracket_keys_do_nothing_on_agents() -> None:
    reg = load_keymap_registry({})
    owners = keymap_actions_by_key(reg.app)
    assert set(owners["right_square_bracket"]) == {"cycle_artifacts_subtab"}
    assert set(owners["left_square_bracket"]) == {"cycle_artifacts_subtab_reverse"}

    agents = _gating_app(tab="agents", navigable=True)
    # Neither bracket owner reaches the Agents tab until tab-scope binds them.
    assert (
        check_app_action(agents, "cycle_artifacts_subtab", (), lambda _a, _p: None)
        is False
    )
    assert (
        check_app_action(
            agents, "cycle_artifacts_subtab_reverse", (), lambda _a, _p: None
        )
        is False
    )


def test_paren_keys_resolve_per_tab() -> None:
    reg = load_keymap_registry({})
    owners = keymap_actions_by_key(reg.app)
    assert set(owners["right_parenthesis"]) == {
        "files_next_version",
        "next_card_block",
    }
    assert set(owners["left_parenthesis"]) == {
        "files_prev_version",
        "prev_card_block",
    }

    files = _gating_app(tab="artifacts", navigable=False, pane="files")
    # Artifacts Files keeps the version owner; the card-block action is gated off.
    assert (
        check_app_action(files, "files_next_version", (), lambda _a, _p: None)
        is not False
    )
    assert check_app_action(files, "next_card_block", (), lambda _a, _p: None) is False
    patches = _gating_app(tab="artifacts", navigable=False, pane="patches")
    assert (
        check_app_action(patches, "next_card_block", (), lambda _a, _p: None) is False
    )


def test_card_block_handlers_step_focused_block() -> None:
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin

    assert hasattr(AgentPanelDetailMixin, "action_next_card_block")
    assert hasattr(AgentPanelDetailMixin, "action_prev_card_block")

    calls: list[int] = []

    class _Detail:
        def cycle_focused_card_block(self, direction: int) -> bool:
            calls.append(direction)
            return True

    class _Host(AgentPanelDetailMixin):
        current_tab = "agents"

        def query_one(self, *args, **kwargs):
            return _Detail()

    host = _Host()
    host.action_next_card_block()
    host.action_prev_card_block()
    assert calls == [1, -1]

    class _OtherTab(_Host):
        current_tab = "artifacts"

    _OtherTab().action_next_card_block()
    assert calls == [1, -1]


def test_card_block_footer_entry_is_conditional() -> None:
    footer = KeybindingFooter()
    agent = _agent()
    off = footer._compute_agent_bindings(agent)
    assert not any(label == "blocks" for _, label in off)
    on = footer._compute_agent_bindings(agent, card_blocks_navigable=True)
    assert ("(/)", "blocks") in on


def test_card_block_palette_availability_follows_context() -> None:
    def _spec(action: str) -> CommandSpec:
        return CommandSpec(
            id=f"app.{action}",
            label="x",
            key_sequence=("left_parenthesis",),
            key_display="(",
            category="Navigation",
            tabs=("agents",),
            executor=("app-action", action),
        )

    assert (
        agents_available(_spec("next_card_block"), CommandContext(tab="agents"))
        is False
    )
    assert (
        agents_available(
            _spec("next_card_block"),
            CommandContext(tab="agents", card_blocks_navigable=True),
        )
        is True
    )
    assert (
        agents_available(
            _spec("prev_card_block"),
            CommandContext(tab="agents", card_blocks_navigable=True),
        )
        is True
    )


def test_card_block_context_threads_focused_panel_predicate() -> None:
    panel = SimpleNamespace(card_blocks_navigable=True)
    area = SimpleNamespace(focused_panel=lambda: panel)
    detail = SimpleNamespace(deck_area=area, deck_layout=SimpleNamespace())
    app = SimpleNamespace(
        current_tab="agents",
        current_artifacts_pane_key="patches",
        _agents=[],
        current_idx=0,
        _marked_agents=set(),
        current_attempt_number=None,
        _panel_group=None,
        _agent_panels_grouped=False,
        _current_group_key=None,
        _agent_metadata_search=SimpleNamespace(is_active=False),
        _fleet_mode_available=lambda: False,
        _get_selected_agent=lambda: None,
        query_one=lambda *a, **k: detail,
        link_follow_available_for_selection=lambda: False,
        _axe_items=[],
        axe_running=False,
    )
    # Deck-layout lookup fails on the stub layout, so deck_split is False,
    # but the card-block predicate still threads through.
    ctx = extract_command_context(app)
    assert ctx.card_blocks_navigable is True


def test_card_block_help_row() -> None:
    reg = load_keymap_registry({})
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("( / )", "Older / newer card block") in pairs


def test_card_block_search_exit_keys() -> None:
    reg = load_keymap_registry({})
    app = SimpleNamespace(_keymap_registry=reg)
    keys = deck_structural_exit_keys(app)
    assert "left_parenthesis" in keys
    assert "right_parenthesis" in keys
