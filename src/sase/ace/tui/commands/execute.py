"""Dispatch palette selections back to existing app actions / mode handlers.

Phase 3 of the command palette plan. The catalog produces a
:class:`CommandExecutor` descriptor for every command; this module is
the single place that turns one of those descriptors into the
corresponding side-effect on a running :class:`AceApp`.

Strategy (per the plan):

- ``app_action``: call ``app.action_<name>()`` directly. This matches
  Textual's action naming convention.
- ``saved_query``: call the existing ``action_load_saved_query_<digit>``
  method on the app.
- Built-in mode keys (``fold``/``copy``/``leader``/``bang``): set the
  matching ``_<mode>_mode_active`` flag and call the existing
  ``_handle_<mode>_key(subkey)`` so we reuse the production dispatch
  path. This avoids reimplementing per-subkey behaviour and stays
  honest about side effects (toasts, footer refresh, etc.).
- ``custom_mode_key``: identical pattern — flip
  ``_custom_mode_active`` to the mode name, then call
  ``_handle_custom_mode_key(subkey)``.

The palette modal is dismissed before this function runs, so any
action that pushes a modal or suspends the app interacts with a
clean screen stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.commands.types import CommandSpec

if TYPE_CHECKING:
    from sase.ace.tui.app import AceApp


def execute_command(app: AceApp, spec: CommandSpec) -> None:  # type: ignore[no-untyped-def]
    """Run ``spec`` on the live ``app`` via existing dispatch paths."""
    executor = spec.executor
    kind = executor.kind

    if kind == "app_action":
        assert executor.action is not None
        action_name = f"action_{executor.action}"
        method = getattr(app, action_name, None)
        if method is None:
            app.notify(  # type: ignore[attr-defined]
                f"Command '{spec.id}' has no app action '{executor.action}'",
                severity="error",
            )
            return
        method()
        return

    if kind == "saved_query":
        assert executor.digit is not None
        action_name = f"action_load_saved_query_{executor.digit}"
        method = getattr(app, action_name, None)
        if method is None:
            return
        method()
        return

    if kind == "fold_mode_key":
        assert executor.subkey is not None
        app._fold_mode_active = True  # type: ignore[attr-defined]
        app._handle_fold_key(executor.subkey)  # type: ignore[attr-defined]
        return

    if kind == "copy_mode_key":
        assert executor.subkey is not None
        app._copy_mode_active = True  # type: ignore[attr-defined]
        app._handle_copy_key(executor.subkey)  # type: ignore[attr-defined]
        return

    if kind == "leader_mode_key":
        assert executor.subkey is not None
        app._leader_mode_active = True  # type: ignore[attr-defined]
        app._handle_leader_key(executor.subkey)  # type: ignore[attr-defined]
        return

    if kind == "bang_mode_key":
        assert executor.subkey is not None
        app._bang_mode_active = True  # type: ignore[attr-defined]
        app._handle_bang_key(executor.subkey)  # type: ignore[attr-defined]
        return

    if kind == "custom_mode_key":
        assert executor.subkey is not None
        assert executor.mode_name is not None
        app._custom_mode_active = executor.mode_name  # type: ignore[attr-defined]
        app._handle_custom_mode_key(executor.subkey)  # type: ignore[attr-defined]
        return

    app.notify(  # type: ignore[attr-defined]
        f"Unknown executor kind: {kind}",
        severity="error",
    )


__all__ = ["execute_command"]
