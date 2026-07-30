"""Tests for dispatching command-palette selections."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.ace.tui.commands import (
    CommandExecutor,
    CommandSpec,
    build_command_catalog,
    execute_command,
)
from sase.ace.tui.keymaps import load_keymap_registry


def _spec(
    spec_id: str,
    executor: CommandExecutor,
    *,
    label: str = "label",
    key_display: str = "x",
    key_sequence: tuple[str, ...] = ("x",),
    aliases: tuple[str, ...] = (),
) -> CommandSpec:
    return CommandSpec(
        id=spec_id,
        label=label,
        key_sequence=key_sequence,
        key_display=key_display,
        category="Misc",
        tabs=("changespecs", "agents", "axe"),
        executor=executor,
        aliases=aliases,
    )


def test_execute_app_action_calls_method() -> None:
    app = MagicMock()
    spec = _spec("app.refresh", CommandExecutor(kind="app_action", action="refresh"))
    execute_command(app, spec)
    app.action_refresh.assert_called_once_with()


def test_execute_wait_command_dispatches_shared_add_tag_action() -> None:
    app = MagicMock()
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["app.add_tag"])

    app.action_add_tag.assert_called_once_with()


def test_execute_unknown_app_action_notifies() -> None:
    app = SimpleNamespace(notify=MagicMock())
    spec = _spec(
        "app.bogus", CommandExecutor(kind="app_action", action="does_not_exist")
    )
    execute_command(app, spec)  # type: ignore[arg-type]
    app.notify.assert_called_once()
    args, kwargs = app.notify.call_args
    assert "no app action" in args[0]
    assert kwargs.get("severity") == "error"


def test_execute_saved_query_dispatches_to_digit_action() -> None:
    app = MagicMock()
    spec = _spec("saved_query.3", CommandExecutor(kind="saved_query", digit=3))
    execute_command(app, spec)
    app.action_load_saved_query_3.assert_called_once_with()


def test_execute_fold_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "fold.cycle_commits",
        CommandExecutor(kind="fold_mode_key", subkey="c"),
        key_display="zc",
        key_sequence=("z", "c"),
    )
    execute_command(app, spec)
    assert app._fold_mode_active is True
    app._handle_fold_key.assert_called_once_with("c")


def test_execute_copy_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "copy.changespecs.name",
        CommandExecutor(kind="copy_mode_key", subkey="n", copy_tab="changespecs"),
        key_display="%n",
        key_sequence=("percent_sign", "n"),
    )
    execute_command(app, spec)
    assert app._copy_mode_active is True
    app._handle_copy_key.assert_called_once_with("n")
    app.push_screen.assert_not_called()


def test_execute_leader_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "leader.agent_run_log",
        CommandExecutor(kind="leader_mode_key", subkey="A"),
        key_display=",A",
        key_sequence=("comma", "A"),
    )
    execute_command(app, spec)
    assert app._leader_mode_active is True
    app._handle_leader_key.assert_called_once_with("A")


def test_execute_leader_repeat_last_dispatches_configured_subkeys() -> None:
    app = MagicMock()
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["leader.models_panel"])
    execute_command(app, catalog["leader.repeat_last"])

    assert app._leader_mode_active is True
    assert app._handle_leader_key.call_args_list == [
        (("m",),),
        (("comma",),),
    ]


def test_execute_projects_command_uses_app_action() -> None:
    app = MagicMock()
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["projects"])

    app.action_open_projects_panel.assert_called_once_with()
    app._handle_leader_key.assert_not_called()


def test_execute_logs_command_uses_app_action() -> None:
    app = MagicMock()
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["logs"])

    app.action_open_log_panel.assert_called_once_with()
    app._handle_leader_key.assert_not_called()


def test_execute_tasks_command_uses_app_action() -> None:
    app = MagicMock()
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["tasks"])

    app.action_open_tasks_panel.assert_called_once_with()
    app._handle_leader_key.assert_not_called()


def test_execute_bang_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "bang.toggle_axe",
        CommandExecutor(kind="bang_mode_key", subkey="x"),
        key_display="!x",
        key_sequence=("exclamation_mark", "x"),
    )
    execute_command(app, spec)
    assert app._bang_mode_active is True
    app._handle_bang_key.assert_called_once_with("x")


def test_execute_custom_mode_sets_mode_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "custom.deploy.prod",
        CommandExecutor(
            kind="custom_mode_key",
            subkey="p",
            mode_name="deploy",
            command_id="prod",
        ),
    )
    execute_command(app, spec)
    assert app._custom_mode_active == "deploy"
    app._handle_custom_mode_key.assert_called_once_with("p")
