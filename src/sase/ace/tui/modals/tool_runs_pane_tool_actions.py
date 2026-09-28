"""Stop, log, catalog-run, and copy actions for the Tools pane (sase-1bt.11).

Read-only views stay in the sibling ``tool_runs_pane_*`` modules; the stop
and run hand-offs below delegate to phase ``tool-run-actions`` and never
settle runs inline.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from sase.tool.logs import ToolRunLogTail

    from .config_center_session import ToolRunsSessionState
else:
    _MixinBase = object


class ToolRunsPaneToolActionsMixin(_MixinBase):
    """Jump-to-agent, log, stop, catalog-run, and copy-id pane actions."""

    if TYPE_CHECKING:
        _catalog_entries: list[Any]
        _pending_run_id: str | None
        _run_rows: list[tuple[str, Any]]
        _scope_project: str | None
        _selected_run_id: str | None
        _session_state: ToolRunsSessionState
        _view: str

        def _detail_for(self, run_id: str | None) -> Any | None: ...

        def _request_reload(self, *, force: bool = False) -> None: ...

        def _selected_identity(self) -> str | None: ...

        def _set_view(self, view: str) -> None: ...

    def action_jump_to_agent(self) -> None:
        """Close the modal and reveal the selected run's Runs block."""

        from .config_center_modal import ConfigCenterModal

        if self._view == "failures":
            self.action_jump_to_failure_agent()
            return
        brief = next(
            (
                item
                for _, item in self._run_rows
                if str(getattr(item, "run_id", "") or "")
                == (self._selected_identity() or self._selected_run_id or "")
            ),
            None,
        )
        if brief is None:
            self.notify("No run selected", severity="warning")
            return
        run_id = str(getattr(brief, "run_id", "") or "")
        agent_name = str(getattr(brief, "agent", "") or "")
        owner_kind = getattr(brief, "owner_kind", None)
        owner_id = getattr(brief, "owner_id", None)
        if not run_id:
            self.notify("No run selected", severity="warning")
            return
        screen = self.screen
        if not isinstance(screen, ConfigCenterModal):
            return
        screen.action_close()
        app = self.app

        def _reveal() -> None:
            try:
                from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

                reveal_tool_run_block(
                    app,
                    run_id,
                    agent=agent_name or None,
                    owner_kind=str(owner_kind) if owner_kind else None,
                    owner_id=str(owner_id) if owner_id else None,
                )
            except Exception as exc:
                self.notify(f"Could not reveal agent: {exc}", severity="warning")

        app.call_after_refresh(_reveal)

    def action_jump_to_failure_agent(self) -> None:
        """Jump to the newest resolvable run in the selected failure group."""

        from .config_center_modal import ConfigCenterModal

        target = self._newest_resolvable_failure_run()
        if target is None:
            self.notify("No owning agent for the selected run", severity="warning")
            return
        run_id, agent_name, owner_kind, owner_id = target
        screen = self.screen
        if not isinstance(screen, ConfigCenterModal):
            return
        screen.action_close()
        app = self.app

        def _reveal() -> None:
            try:
                from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

                reveal_tool_run_block(
                    app,
                    run_id,
                    agent=agent_name or None,
                    owner_kind=owner_kind,
                    owner_id=owner_id,
                )
            except Exception as exc:
                self.notify(f"Could not reveal agent: {exc}", severity="warning")

        app.call_after_refresh(_reveal)

    def _newest_resolvable_failure_run(
        self,
    ) -> tuple[str, str, str | None, str | None] | None:
        """Return the newest failure run with owner facts, if any."""

        identity = None
        try:
            identity = self._selected_identity()
        except Exception:
            identity = None
        index = 0
        if identity and identity.startswith("failure-"):
            try:
                index = int(identity.split("-", 1)[1])
            except (ValueError, IndexError):
                index = 0
        try:
            groups = list(getattr(self, "_failure_groups", ()) or ())
        except Exception:
            return None
        if not 0 <= index < len(groups):
            return None
        group = groups[index]
        if not isinstance(group, dict):
            return None
        for entry in list(group.get("affected_runs", ()) or ()):
            if not isinstance(entry, dict):
                continue
            run_id = str(entry.get("run_id") or "")
            if not run_id:
                continue
            return (
                run_id,
                str(entry.get("agent") or ""),
                str(entry.get("owner_kind") or "") or None,
                str(entry.get("owner_id") or "") or None,
            )
        last_run_id = str(group.get("last_run_id") or "")
        if last_run_id:
            owners = group.get("newest_owners", [])
            owner_name = ""
            try:
                if isinstance(owners, list) and owners:
                    first = owners[0]
                    if isinstance(first, dict):
                        owner_name = str(first.get("agent") or first.get("name") or "")
                    else:
                        owner_name = str(first or "")
            except Exception:
                owner_name = ""
            return (last_run_id, owner_name, None, None)
        return None

    def action_open_log(self) -> None:
        """Open the selected run's retained log in the pager."""

        run_id = self._selected_identity() or self._selected_run_id
        if not run_id:
            self.notify("No run selected", severity="warning")
            return
        brief = next(
            (
                item
                for _, item in self._run_rows
                if str(getattr(item, "run_id", "")) == run_id
            ),
            None,
        )
        if brief is None:
            self.notify("No run selected", severity="warning")
            return
        detail_obj = self._detail_for(run_id)
        self.run_worker(
            self._open_log_async(run_id, brief, detail_obj),
            exclusive=True,
            group="tools-pane-log",
        )

    async def _open_log_async(self, run_id: str, brief: Any, detail_obj: Any) -> None:
        try:
            tail = await asyncio.to_thread(self._read_tail, brief, detail_obj)
        except Exception as exc:
            self.notify(f"Could not read log: {exc}", severity="error")
            return
        try:
            from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
        except Exception as exc:
            self.notify(f"Could not open pager: {exc}", severity="error")
            return
        try:
            body = "\n".join(
                str(line) for line in tuple(getattr(tail, "lines", ()) or ())
            )
            if not body:
                body = "no log recorded"
            document = PagerDocument(
                sections=(
                    PagerSection(
                        identity=f"tool-run-log-{run_id[:8]}",
                        title=f"⚒ run log {run_id[:8]}",
                        kind="text",
                        body=body,
                    ),
                ),
                title=f"⚒ run log {run_id[:8]}",
                origin=PagerOrigin.AGENT,
            )
        except Exception as exc:
            self.notify(f"Could not open pager: {exc}", severity="error")
            return
        try:
            viewer = self.app._view_files_with_pager_screen  # type: ignore[attr-defined]
        except Exception:
            self.notify("Pager is unavailable", severity="error")
            return
        try:
            viewer(document)
        except Exception as exc:
            self.notify(f"Could not open pager: {exc}", severity="error")

    @staticmethod
    def _read_tail(brief: Any, detail_obj: Any) -> ToolRunLogTail:
        from sase.tool.logs import ToolRunLogTail, tool_run_log_tail

        logs = getattr(detail_obj, "logs", None) if detail_obj is not None else None
        metadata = (
            logs.to_tail_metadata()
            if logs is not None and hasattr(logs, "to_tail_metadata")
            else {}
        )
        tail: ToolRunLogTail = tool_run_log_tail(
            str(getattr(brief, "run_id", "") or ""),
            metadata,
            getattr(brief, "owner_kind", None),
            getattr(brief, "owner_id", None),
            60,
            256 * 1024,
        )
        return tail

    def action_stop_run(self) -> None:
        """Confirm and stop the selected live run as a durable proc."""

        if self._view != "runs":
            self.notify("Switch to the Runs view to stop a run", severity="warning")
            return
        run_id = self._selected_identity() or self._selected_run_id
        if not run_id or run_id.startswith("failure-"):
            self.notify("No run selected", severity="warning")
            return
        brief = next(
            (
                item
                for _, item in self._run_rows
                if str(getattr(item, "run_id", "")) == run_id
            ),
            None,
        )
        if brief is None:
            self.notify("No run selected", severity="warning")
            return
        from sase.ace.tui.actions.agents._tool_run_actions import request_tool_run_stop

        try:
            request_tool_run_stop(self.app, brief)
        except Exception as exc:
            self.notify(f"Could not stop run: {exc}", severity="error")

    def action_run_tool(self) -> None:
        """Confirm and hand off the selected catalog tool (``-H`` worker)."""

        if self._view != "catalog":
            self.notify("Switch to the Catalog view to run a tool", severity="warning")
            return
        name = self._selected_identity()
        entry = next(
            (
                item
                for item in self._catalog_entries
                if str(getattr(item, "name", "")) == name
            ),
            None,
        )
        if entry is None and self._catalog_entries:
            entry = self._catalog_entries[0]
        if entry is None:
            self.notify("No tools in catalog", severity="warning")
            return
        tool_name = str(getattr(entry, "name", "") or "")
        definition = getattr(entry, "definition", {}) or {}
        argv = tuple(str(part) for part in (definition.get("argv", ()) or ()))
        from sase.ace.tui.actions.agents._tool_run_actions import (
            confirm_catalog_tool_run,
            launch_catalog_tool,
            primary_checkout_root,
        )

        root = primary_checkout_root(self._scope_project)

        def _on_answer(confirmed: bool | None) -> None:
            if confirmed:
                self._launch_catalog_tool(tool_name, root)

        try:
            confirm_catalog_tool_run(
                self.app,
                tool_name=tool_name,
                argv=argv,
                root=root,
                on_confirmed=_on_answer,
            )
        except Exception as exc:
            self.notify(f"Could not run tool: {exc}", severity="error")

    def _launch_catalog_tool(self, tool_name: str, root: str) -> None:
        """Hand off one catalog tool from a session worker (never durable)."""

        from sase.ace.tui.actions.agents._tool_run_actions import launch_catalog_tool
        from sase.ace.tui.actions.proc_actions import TrackedProcCompletion

        submit = getattr(self.app, "_submit_session_worker", None)
        if not callable(submit):
            self.notify("Could not run: worker queue unavailable.", severity="error")
            return

        def _body() -> Any:
            from sase.ace.tui.actions._proc_action_types import TrackedProcResult

            outcome = launch_catalog_tool(self.app, tool_name=tool_name, root=root)
            if outcome.get("ok"):
                return TrackedProcResult(
                    success=True,
                    message=f"Tool {tool_name} handed off as run {outcome['ok'][:8]}",
                    payload=outcome,
                )
            return TrackedProcResult(
                success=False,
                message=str(outcome.get("error") or "hand-off refused"),
                payload=outcome,
            )

        def _on_complete(completion: TrackedProcCompletion[Any]) -> None:
            payload = completion.payload if isinstance(completion.payload, dict) else {}
            run_id = str(payload.get("ok") or "") if payload else ""
            if completion.success and run_id:
                self._pending_run_id = run_id
                self._session_state.pending_run_id = run_id
                self._set_view("runs")
                self._request_reload(force=True)
            self.notify(
                completion.message,
                severity="information" if completion.success else "error",
            )

        try:
            submit(
                "tool-run-catalog",
                _body,
                display_name=f"run tool {tool_name}",
                cl_name=tool_name,
                on_complete=_on_complete,
            )
        except Exception as exc:
            self.notify(f"Could not run tool: {exc}", severity="error")

    def action_copy_run_id(self) -> None:
        """Copy the selected run's full 32-hex id."""

        run_id = self._selected_identity() or self._selected_run_id
        if self._view != "runs":
            run_id = None
        if not run_id or run_id.startswith("failure-"):
            self.notify("No run selected", severity="warning")
            return
        try:
            from sase.ace.tui.actions.clipboard import schedule_copy_delivery

            schedule_copy_delivery(
                self.app,
                run_id,
                copied_label="Tool run id",
                task_name="tools-pane-copy-run-id",
            )
        except Exception:
            try:
                self.app.copy_to_clipboard(run_id)  # type: ignore[attr-defined]
            except Exception:
                self.notify(f"run {run_id}", severity="information")


__all__ = ["ToolRunsPaneToolActionsMixin"]
