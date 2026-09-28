"""ToolRun stop and catalog-run flows for the TUI (§3.11, sase-1bt.11).

Shared by the Admin Center Tools pane (Runs ``s``, Catalog ``r``) and the
command palette ("Stop live tool run", "Run project tool…"). Stopping runs
as a durable proc (``sase tool stop RUN -j`` with a typed ``tool.stop``
result); catalog runs hand off ``sase tool run -H <tool>`` in-process from
a session worker, never through the durable-proc or ``:`` proc paths.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

_RUN_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")


def _load_run_dict(run_id: str) -> dict[str, Any] | None:
    """Return the ledger dict for *run_id*, or None when unreadable."""

    try:
        from sase.core.tool_run import tool_run_show

        envelope = tool_run_show(run_id)
    except Exception:
        return None
    run = envelope.get("run")
    return dict(run) if isinstance(run, dict) else None


def _coerce_run(run: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return *run* as a plain dict (glance/brief dataclasses included)."""

    if isinstance(run, dict):
        return dict(run)
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(run) and not isinstance(run, type):
            return dict(asdict(run))
    except Exception:
        pass
    try:
        return dict(vars(run))
    except Exception:
        return {}


def _resolve_stop_target(run: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Return the outermost stoppable ancestor of *run* (itself if none)."""

    from sase.ace.tui.tool_runs.stop import resolve_stoppable_ancestor

    base = _coerce_run(run)
    return dict(
        resolve_stoppable_ancestor(base, _load_run_dict) or base,
    )


def request_tool_run_stop(app: Any, run: Mapping[str, Any] | Any) -> None:
    """Confirm and submit a durable ``sase tool stop`` for *run*.

    The confirm copy depends on the owner (inline agent, monitor-owned,
    proc-owned hand-off, or nested run resolved to its outermost
    stoppable ancestor). The confirm is DANGER with Cancel focused.
    """

    from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
    from sase.ace.tui.modals.confirm_dialog import ConfirmKind
    from sase.ace.tui.tool_runs.stop import (
        is_live_run,
        stop_confirm_copy,
    )

    base = _coerce_run(run)
    run_id = str(base.get("run_id") or "").strip()
    if not run_id:
        app.notify("No tool run to stop", severity="warning")
        return
    full = _load_run_dict(run_id) or base
    if not is_live_run(full):
        app.notify(
            f"Tool run {run_id[:8]} already settled; nothing to stop",
            severity="warning",
        )
        return
    ancestor = _resolve_stop_target(full)
    title, message = stop_confirm_copy(full, ancestor)
    target_id = str(ancestor.get("run_id") or run_id)

    def _on_answer(confirmed: bool | None) -> None:
        if confirmed:
            _submit_tool_run_stop(app, target_id, ancestor)

    app.push_screen(
        ConfirmActionModal(
            title,
            message,
            kind=ConfirmKind.DANGER,
            confirm_label="Stop",
            cancel_label="Keep running",
            default="cancel",
        ),
        _on_answer,
    )


def _submit_tool_run_stop(app: Any, run_id: str, run: Mapping[str, Any]) -> None:
    """Submit ``sase tool stop RUN -j`` as a durable proc (never raises)."""

    from sase.ace.tui.actions._durable_ops import (
        durable_fingerprint,
        durable_request_payload,
        sase_argv,
    )
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.tool_runs.stop import (
        run_label,
        short_run_id,
        stop_concurrency_key,
        stop_submit_label,
    )
    from sase.ops.names import TOOL_STOP

    def _on_complete(completion: TrackedProcCompletion[dict[str, object]]) -> None:
        app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )

    submit = getattr(app, "_submit_durable_proc", None)
    if not callable(submit):
        app.notify("Could not stop: proc queue unavailable.", severity="error")
        return
    label = stop_submit_label(run)
    submit(
        sase_argv("tool", "stop", run_id, "-j"),
        operation=TOOL_STOP,
        request=durable_request_payload(
            run_id=run_id,
            tool_name=str(run.get("tool_name") or ""),
            label=run_label(run),
        ),
        request_fingerprint=durable_fingerprint(TOOL_STOP, run_id),
        concurrency_keys=(stop_concurrency_key(run_id),),
        label=label,
        display_name=label,
        proc_type="tool.stop",
        cl_name=short_run_id(run_id),
        project_file=str(run.get("project") or ""),
        duplicate_message=(
            f"A stop operation is already running for run {short_run_id(run_id)}"
        ),
        on_complete=_on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )


def confirm_catalog_tool_run(
    app: Any,
    *,
    tool_name: str,
    argv: tuple[str, ...],
    root: str,
    on_confirmed: Any,
) -> None:
    """Confirm a catalog ``r`` hand-off, showing argv and root (Run focused)."""

    from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal

    shown_argv = " ".join(str(part) for part in argv) or tool_name
    app.push_screen(
        ConfirmActionModal(
            "Run Project Tool",
            f"$ {shown_argv}\nroot: {root or 'unknown'}",
            subject=tool_name,
            confirm_label="Run",
            cancel_label="Cancel",
            default="confirm",
        ),
        on_confirmed,
    )


def launch_catalog_tool(app: Any, *, tool_name: str, root: str) -> dict[str, Any]:
    """Hand off ``sase tool run -H <tool>`` at *root* (session-worker body).

    Calls the hand-off launcher in-process with an explicit root; never
    mutates the TUI's cwd or env and never uses the durable-proc or ``:``
    proc paths. Returns ``{"ok": run_id}`` or ``{"ok": None, "error": msg}``.
    """

    from sase.tool.executor import ToolRunCliRequest
    from sase.tool.handoff_launch import execute_handoff

    request = ToolRunCliRequest(
        quiet=True,
        verbose=False,
        tail_lines=0,
        words=(tool_name,),
        hand_off=True,
    )
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = execute_handoff(request, cwd=Path(root) if root else None)
    except Exception as exc:  # noqa: BLE001 - refusal toasts, never raises.
        return {"ok": None, "error": str(exc)}
    if code != 0:
        message = err.getvalue().strip() or out.getvalue().strip()
        return {"ok": None, "error": message or f"hand-off refused (exit {code})"}
    match = _RUN_ID_RE.search(out.getvalue())
    if match is None:
        return {"ok": None, "error": "hand-off started but reported no run id"}
    return {"ok": match.group(0)}


def primary_checkout_root(project: str | None) -> str:
    """Return *project*'s primary checkout root, or "" when unknown."""

    if not project:
        return ""
    try:
        from sase.running_field import get_workspace_directory

        root = Path(get_workspace_directory(project, 1)).expanduser()
    except Exception:
        return ""
    return str(root) if root.is_dir() else ""


class ToolRunActionsMixin:
    """Palette entry points for the ToolRun actions (sase-1bt.11)."""

    def action_show_tool_runs_card(self) -> None:
        """Show Tools with the Runs card active in the focused panel."""

        if getattr(self, "current_tab", None) != "agents":
            return
        try:
            from ...widgets import AgentDetail
            from ...widgets.decks.spec import DeckId, active_deck_cycle
        except Exception:
            return
        try:
            cycle = active_deck_cycle()
            index = next(
                i
                for i, deck in enumerate(cycle)
                if deck is DeckId.TOOLS or str(getattr(deck, "value", deck)) == "tools"
            )
        except Exception:
            return
        show = getattr(self, "action_show_deck_at", None)
        if not callable(show):
            return
        try:
            show(index)
        except Exception:
            return

    def action_stop_live_tool_run(self) -> None:
        """Confirm and stop the selected node's live tool run."""

        if getattr(self, "current_tab", None) != "agents":
            return
        run = _selected_node_live_run(self)
        if run is None:
            self.notify(  # type: ignore[attr-defined]
                "No live tool run on the selected node", severity="warning"
            )
            return
        request_tool_run_stop(self, run)

    def on_tool_run_jump_requested(self, message: Any) -> None:
        """Reveal the clicked/hinted run's block on the selected node."""

        try:
            from sase.ace.tui.tool_runs.reveal import reveal_selected_node_run

            reveal_selected_node_run(self, str(getattr(message, "run_id", "") or ""))
        except Exception:
            pass
        try:
            stop = getattr(message, "stop", None)
            if callable(stop):
                stop()
        except Exception:
            pass

    def action_open_tool_runs_catalog(self) -> None:
        """Open the Admin Center Tools pane on the Catalog view."""

        try:
            from ...modals.config_center_session import AdminCenterSessionState
        except Exception:
            opener = getattr(self, "action_open_tool_runs_panel", None)
            if callable(opener):
                opener()
            return
        state = getattr(self, "_admin_center_session_state", None)
        if not isinstance(state, AdminCenterSessionState):
            state = AdminCenterSessionState()
            self._admin_center_session_state = state  # type: ignore[attr-defined]
        try:
            state.tools.active_view = "catalog"
        except Exception:
            pass
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("tools")
            return
        legacy = getattr(self, "action_open_tool_runs_panel", None)
        if callable(legacy):
            legacy()


def _selected_node_live_run(app: Any) -> Any | None:
    """Return the selected node's first live tool run, if any."""

    try:
        from sase.ace.tui.tool_runs import summaries
        from sase.ace.tui.tool_runs.snapshot import get_snapshot
    except Exception:
        return None
    try:
        agent = app._get_selected_agent()  # type: ignore[attr-defined]
    except Exception:
        return None
    if agent is None:
        return None
    try:
        selector = summaries.selector_for_agent(agent)
    except Exception:
        return None
    if selector is None:
        return None
    try:
        snapshot = get_snapshot()
        runs = summaries.node_live_runs(
            snapshot.runs if snapshot is not None else (), selector
        )
    except Exception:
        return None
    return runs[0] if runs else None


__all__ = [
    "ToolRunActionsMixin",
    "confirm_catalog_tool_run",
    "launch_catalog_tool",
    "primary_checkout_root",
    "request_tool_run_stop",
]
