"""Stop, catalog-run, OpenToolRun, Procs marker, and palette (sase-1bt.11)."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._tool_run_actions import (
    ToolRunActionsMixin,
    launch_catalog_tool,
    request_tool_run_stop,
)
from sase.ace.tui.commands.availability import is_command_available
from sase.ace.tui.commands.catalog import build_command_catalog, get_command_by_id
from sase.ace.tui.commands.types import CommandContext
from sase.ace.tui.keymaps import (
    ToolRunsPaneKeymaps,
    build_tool_runs_bindings,
    load_keymap_registry,
)
from sase.ace.tui.keymaps.defaults import load_builtin_tool_runs_defaults
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.tool_runs.stop import (
    resolve_stoppable_ancestor,
    stop_confirm_copy,
)
from sase.feature_flags import override_flags


def _run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "6c3d5107" + "0" * 24,
        "tool_name": "check",
        "label": "check",
        "state": "running",
        "launch_mode": "foreground",
        "agent": "0t9--code",
        "owner_kind": None,
        "owner_id": None,
        "parent_run_id": None,
        "project": "sase",
    }
    base.update(overrides)
    return base


# --- stop confirm copy ------------------------------------------------------


def test_stop_copy_inline_agent_run() -> None:
    """Inline runs warn about exit 143 with the agent kept running."""

    title, message = stop_confirm_copy(_run())
    assert title == "Stop Tool Run"
    assert message == (
        "Stop \u2692 check (run 6c3d5107)? The agent's `sase tool run` "
        "exits 143 and it will see a failed check. The agent keeps running."
    )


def test_stop_copy_monitor_owned_run() -> None:
    """Monitor-owned runs warn the follow-up will not launch."""

    title, message = stop_confirm_copy(
        _run(launch_mode="handoff", owner_kind="monitor", owner_id="mon-1")
    )
    assert title == "Stop Tool Run"
    assert message == (
        "Stop \u2692 check owned by monitor `mon-1`? "
        "The monitor stops and its follow-up agent will not launch."
    )


def test_stop_copy_proc_owned_run() -> None:
    """Proc-owned hand-offs warn the proc is killed."""

    title, message = stop_confirm_copy(
        _run(launch_mode="handoff", owner_kind="proc", owner_id="proc-9")
    )
    assert title == "Stop Tool Run"
    assert message == (
        "Stop \u2692 check? Its hand-off proc is killed, "
        "and the run settles as stopped."
    )


def test_stop_copy_nested_run_names_parent() -> None:
    """Nested runs resolve to the outermost stoppable ancestor."""

    parent = _run(run_id="a" * 32, label="check")
    child = _run(run_id="b" * 32, parent_run_id="a" * 32)
    title, message = stop_confirm_copy(child, parent)
    assert title == "Stop Tool Run"
    assert message == ("This run belongs to run `aaaaaaaa`; stopping it stops both.")


def test_resolve_stoppable_ancestor_chain_and_cycle() -> None:
    """Ancestor resolution follows parents, stops on revisit or gaps."""

    runs = {
        "c": _run(run_id="c", parent_run_id="b"),
        "b": _run(run_id="b", parent_run_id="a"),
        "a": _run(run_id="a"),
    }
    assert (
        resolve_stoppable_ancestor(runs["c"], runs.get)["run_id"] == "a"  # type: ignore[arg-type]
    )
    assert resolve_stoppable_ancestor(runs["a"], runs.get)["run_id"] == "a"  # type: ignore[arg-type]
    assert (
        resolve_stoppable_ancestor(_run(run_id="x"), lambda _rid: None)["run_id"] == "x"
    )
    loop = _run(run_id="l", parent_run_id="l")
    assert resolve_stoppable_ancestor(loop, lambda _rid: loop)["run_id"] == "l"


# --- stop request flow ------------------------------------------------------


class _StubApp(ToolRunActionsMixin):
    def __init__(self) -> None:
        self.pushed: list[tuple[Any, Any]] = []
        self.notifies: list[tuple[str, Any]] = []
        self.durable: list[dict[str, Any]] = []
        self.session_workers: list[dict[str, Any]] = []
        self.current_tab = "agents"

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))

    def notify(self, message: str, severity: Any = None) -> None:
        self.notifies.append((message, severity))

    def _submit_durable_proc(self, argv: Any, **kwargs: Any) -> None:
        self.durable.append({"argv": list(argv), **kwargs})

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> None:
        self.session_workers.append({"args": args, "kwargs": kwargs})


def _confirm_modal(app: _StubApp) -> ConfirmActionModal:
    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert isinstance(modal, ConfirmActionModal)
    return modal


def test_stop_flow_confirms_danger_with_cancel_focused(
    monkeypatch: Any,
) -> None:
    """The stop confirm is DANGER with Cancel focused and per-owner copy."""

    from sase.ace.tui.actions.agents import _tool_run_actions as actions

    run = _run(launch_mode="handoff", owner_kind="monitor", owner_id="mon-1")
    monkeypatch.setattr(actions, "_load_run_dict", lambda _rid: run)
    app = _StubApp()
    request_tool_run_stop(app, run)
    modal = _confirm_modal(app)
    assert modal._kind is ConfirmKind.DANGER
    assert modal._default == "cancel"
    assert modal._confirm_label == "Stop"
    assert modal._cancel_label == "Keep running"
    assert "mon-1" in modal._message


def test_stop_flow_submits_durable_proc_not_session_worker(
    monkeypatch: Any,
) -> None:
    """Confirming stop submits ``sase tool stop RUN -j`` as a durable proc."""

    from sase.ace.tui.actions.agents import _tool_run_actions as actions

    run = _run()
    monkeypatch.setattr(actions, "_load_run_dict", lambda _rid: run)
    app = _StubApp()
    request_tool_run_stop(app, run)
    _modal, callback = app.pushed[0]
    assert callable(callback)
    callback(True)
    assert len(app.durable) == 1
    assert app.session_workers == []
    submitted = app.durable[0]
    assert submitted["argv"] == ["sase", "tool", "stop", run["run_id"], "-j"]
    assert submitted["operation"] == "tool.stop"
    assert submitted["concurrency_keys"] == (f"tool-stop:{run['run_id']}",)
    from sase.ace.tui.actions._durable_ops import durable_fingerprint

    assert submitted["request_fingerprint"] == durable_fingerprint(
        "tool.stop", run["run_id"]
    )


def test_stop_flow_cancel_submits_nothing(monkeypatch: Any) -> None:
    """Dismissing the confirm submits nothing."""

    from sase.ace.tui.actions.agents import _tool_run_actions as actions

    run = _run()
    monkeypatch.setattr(actions, "_load_run_dict", lambda _rid: run)
    app = _StubApp()
    request_tool_run_stop(app, run)
    _modal, callback = app.pushed[0]
    callback(False)
    assert app.durable == []
    assert app.session_workers == []


def test_stop_flow_settled_run_toasts(monkeypatch: Any) -> None:
    """A settled run never reaches the confirm; it toasts instead."""

    from sase.ace.tui.actions.agents import _tool_run_actions as actions

    run = _run(state="succeeded")
    monkeypatch.setattr(actions, "_load_run_dict", lambda _rid: run)
    app = _StubApp()
    request_tool_run_stop(app, run)
    assert app.pushed == []
    assert app.durable == []
    assert any("already settled" in message for message, _ in app.notifies)


# --- catalog run ------------------------------------------------------------


def test_catalog_launch_refusal_returns_typed_error(monkeypatch: Any) -> None:
    """A refused hand-off returns an error instead of raising."""

    import sase.tool.handoff_launch as launcher

    monkeypatch.setattr(launcher, "execute_handoff", lambda _request, **_kw: 2)
    outcome = launch_catalog_tool(object(), tool_name="check", root="/tmp")
    assert outcome["ok"] is None
    assert isinstance(outcome["error"], str) and outcome["error"]


def test_catalog_launch_never_uses_durable_proc(monkeypatch: Any) -> None:
    """The catalog path refuses cleanly without touching the durable queue."""

    import sase.tool.handoff_launch as launcher

    seen: dict[str, Any] = {}

    def _refuse(request: Any, **kwargs: Any) -> int:
        seen["kwargs"] = kwargs
        print("sase tool run -H cannot be used inside monitor m1", file=sys.stderr)
        return 2

    monkeypatch.setattr(launcher, "execute_handoff", _refuse)
    app = _StubApp()
    outcome = launch_catalog_tool(app, tool_name="check", root="/tmp")
    assert outcome["ok"] is None
    assert "monitor m1" in str(outcome["error"])
    assert app.durable == []


def test_catalog_launch_passes_root_explicitly(monkeypatch: Any) -> None:
    """The worker hands the primary root to the launcher, not the TUI cwd."""

    import sase.tool.handoff_launch as launcher

    seen: dict[str, Any] = {}

    def _ok(request: Any, **kwargs: Any) -> int:
        seen["kwargs"] = kwargs
        print("sase tool run " + "f" * 32)
        return 0

    monkeypatch.setattr(launcher, "execute_handoff", _ok)
    outcome = launch_catalog_tool(object(), tool_name="check", root="/repo")
    assert outcome == {"ok": "f" * 32}
    assert str(seen["kwargs"].get("cwd")) == "/repo"


# --- OpenToolRun dispatch ---------------------------------------------------


def _notification(run_id: str | None) -> Any:
    from sase.notifications import Notification

    return Notification(
        id="n-open-tool-run",
        timestamp="2026-09-18T12:00:00+00:00",
        sender="tool-run",
        action="OpenToolRun",
        action_data={"run_id": run_id} if run_id else {},
    )


def test_open_tool_run_missing_run_id_warns() -> None:
    """A notification without a run id warns instead of navigating."""

    from sase.ace.tui.actions.agents._notification_handlers import handle_open_tool_run

    app = _StubApp()
    assert handle_open_tool_run(app, _notification(None)) is False
    assert any("No tool run" in message for message, _ in app.notifies)


def test_open_tool_run_without_node_opens_pane(monkeypatch: Any) -> None:
    """No visible node routes to Admin Center Tools focused on the run."""

    from sase.ace.tui.actions.agents import _notification_handlers as handlers

    monkeypatch.setattr(
        handlers, "_resolve_visible_tool_run_node", lambda _app, _rid: None
    )
    opened: list[tuple[Any, Any]] = []

    class _PaneApp(_StubApp):
        def _open_config_center(self, tab: Any, **kwargs: Any) -> None:
            opened.append((tab, kwargs))

    app = _PaneApp()
    assert handlers.handle_open_tool_run(app, _notification("r" * 32)) is True
    assert opened == [("tools", {"tool_run_focus_target": "r" * 32})]


def test_open_tool_run_with_node_jumps(monkeypatch: Any) -> None:
    """A visible node is selected instead of opening the pane."""

    from sase.ace.tui.actions.agents import _notification_handlers as handlers

    sentinel = object()
    monkeypatch.setattr(
        handlers, "_resolve_visible_tool_run_node", lambda _app, _rid: sentinel
    )
    jumped: list[Any] = []
    shown: list[Any] = []
    from sase.ace.tui.actions.agents import _notification_navigation as navigation

    monkeypatch.setattr(
        navigation,
        "jump_to_loaded_agent",
        lambda _app, _target: jumped.append(_target) or True,
    )
    monkeypatch.setattr(
        handlers, "_show_tools_deck_best_effort", lambda _app: shown.append(True)
    )

    class _JumpApp(_StubApp):
        def _open_config_center(
            self, tab: Any, **kwargs: Any
        ) -> None:  # pragma: no cover
            raise AssertionError("pane must not open when the node is visible")

    app = _JumpApp()
    assert handlers.handle_open_tool_run(app, _notification("r" * 32)) is True
    assert jumped == [sentinel]
    assert shown == [True]


# --- Procs marker -----------------------------------------------------------


def _observed_proc(**overrides: Any) -> Any:
    from sase.ace.tui._proc_observer_models import ObservedProc

    base: dict[str, Any] = {
        "proc_id": "proc-1",
        "proc_type": "tool",
        "cl_name": "check",
        "project_file": "sase",
        "status": "running",
        "message": "",
        "started_at": datetime(2026, 9, 28, 12, 0, 0),
        "display_name": "tool:check",
        "tags": ("tool-run", "tool-run:" + "a" * 32),
    }
    base.update(overrides)
    return ObservedProc(**base)


def test_procs_marker_decoded_from_tags_only() -> None:
    """The ⚒ marker decodes the run id from tags and the name from the label."""

    from sase.ace.tui.modals.procs_pane_render import (
        tool_run_id_for_task,
        _tool_run_label_for_task,
    )

    assert tool_run_id_for_task(_observed_proc()) == "a" * 32
    assert _tool_run_label_for_task(_observed_proc()) == "check"
    assert tool_run_id_for_task(_observed_proc(tags=("tool-run",))) is None
    assert tool_run_id_for_task(_observed_proc(tags=())) is None
    assert _tool_run_label_for_task(_observed_proc(display_name="other")) is None


def test_procs_marker_row_gated_by_flag() -> None:
    """Flag on shows ⚒ check; flag off renders exactly as before."""

    from sase.ace.tui.modals.procs_pane_render import task_row_label

    with override_flags(ace_tool_runs=True):
        assert "⚒ check" in task_row_label(_observed_proc()).plain
    with override_flags(ace_tool_runs=False):
        assert "⚒" not in task_row_label(_observed_proc()).plain


# --- palette ----------------------------------------------------------------


def _catalog() -> Any:
    return build_command_catalog(load_keymap_registry({}))


def test_palette_has_four_tool_run_commands() -> None:
    """The palette gains show/stop/pane/catalog entries with app actions."""

    catalog = _catalog()
    specs = {spec.id: spec for spec in catalog if spec.id.startswith("tool_runs.")}
    assert set(specs) == {
        "tool_runs.show",
        "tool_runs.stop",
        "tool_runs.open_pane",
        "tool_runs.run_tool",
    }
    assert specs["tool_runs.show"].executor.action == "show_tool_runs_card"
    assert specs["tool_runs.stop"].executor.action == "stop_live_tool_run"
    assert specs["tool_runs.open_pane"].executor.action == "open_tool_runs_panel"
    assert specs["tool_runs.run_tool"].executor.action == "open_tool_runs_catalog"
    assert get_command_by_id(catalog, "tool_runs.stop") is specs["tool_runs.stop"]


def test_palette_tool_run_availability() -> None:
    """Show needs runs, stop needs a live run, and flag off hides all four."""

    ids = (
        "tool_runs.show",
        "tool_runs.stop",
        "tool_runs.open_pane",
        "tool_runs.run_tool",
    )
    specs = {spec.id: spec for spec in _catalog() if spec.id in ids}
    live = CommandContext(
        tab="agents",
        selected_node_has_tool_runs=True,
        selected_node_has_live_tool_run=True,
    )
    settled = CommandContext(tab="agents", selected_node_has_tool_runs=True)
    bare = CommandContext(tab="agents")
    with override_flags(ace_tool_runs=True):
        assert is_command_available(specs["tool_runs.show"], live) is True
        assert is_command_available(specs["tool_runs.stop"], live) is True
        assert is_command_available(specs["tool_runs.show"], settled) is True
        assert is_command_available(specs["tool_runs.stop"], settled) is False
        assert is_command_available(specs["tool_runs.show"], bare) is False
        assert is_command_available(specs["tool_runs.stop"], bare) is False
        assert is_command_available(specs["tool_runs.open_pane"], bare) is True
        assert is_command_available(specs["tool_runs.run_tool"], bare) is True
    with override_flags(ace_tool_runs=False):
        for spec_id in ids:
            assert is_command_available(specs[spec_id], live) is False


# --- keymaps ----------------------------------------------------------------


def test_tool_runs_keymaps_gain_stop_and_run() -> None:
    """The Tools pane binds s (stop) and r (run) through the shared meta."""

    defaults = load_builtin_tool_runs_defaults()
    assert defaults["stop_run"] == "s"
    assert defaults["run_tool"] == "r"
    keymaps = ToolRunsPaneKeymaps()
    assert keymaps.stop_run == "s"
    assert keymaps.run_tool == "r"
    actions = {binding.action for binding in build_tool_runs_bindings(keymaps)}
    assert "stop_run" in actions
    assert "run_tool" in actions
