"""Admin Center Tools pane: Runs, Failures, and Catalog views (sase-1bt.10).

Read-only project/machine views over the machine-local ToolRun ledger.
Never reconciles, never settles, never shells out on a UI path. Stop and
run actions belong to phase ``tool-run-actions`` (sase-1bt.11).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.keymaps import (
    ToolRunsPaneKeymaps,
    build_tool_runs_bindings,
    load_keymap_registry,
)
from sase.ace.tui.tool_runs.deck import ToolRunsDetailLevel
from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip

from .config_center_session import ToolRunsSessionState
from .tool_runs_pane_data import (
    ToolRunFocusTarget,
    filter_briefs,
    format_failure_row,
    format_run_row,
    order_runs,
)

_VIEWS: tuple[str, ...] = ("runs", "failures", "catalog")
_VIEW_TABS: tuple[PanelTab, ...] = (
    PanelTab("runs", "Runs", "#87D7FF"),
    PanelTab("failures", "Failures", "#FF5F5F"),
    PanelTab("catalog", "Catalog", "#FFAF5F"),
)
_POLL_INTERVAL_SECONDS = 2.0
_RUNS_LIMIT = 100


def _store_token() -> tuple[object, ...]:
    """Stat the ToolRun store files; a quiet tick opens nothing else."""

    try:
        from sase.core.tool_run import tool_run_store_path
    except Exception:
        return ()
    try:
        path = tool_run_store_path()
    except Exception:
        return ()
    token: list[object] = []
    for candidate in (path, path.parent / f"{path.name}-wal"):
        try:
            stat = candidate.stat()
            token.append((str(candidate), stat.st_mtime_ns, stat.st_size))
        except OSError:
            token.append((str(candidate), None))
    return tuple(token)


def _resolve_scope_project(modal_project: str | None) -> str | None:
    """Return the default Runs scope project, if one is known."""

    if modal_project:
        return modal_project
    try:
        from sase.current_project import resolve_current_project
    except Exception:
        return None
    try:
        current = resolve_current_project()
    except Exception:
        return None
    if current is None:
        return None
    return getattr(current, "project_key", None)


class ToolRunsPane(Vertical):
    """Three read-only ToolRun views with a shared detail region."""

    can_focus = False
    BINDINGS = []

    def __init__(
        self,
        *,
        project: str | None = None,
        session_state: ToolRunsSessionState | None = None,
        keymaps: ToolRunsPaneKeymaps | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._modal_project = project
        self._session_state = session_state or ToolRunsSessionState()
        self._keymaps = keymaps or load_keymap_registry({}).tool_runs
        self._bindings = BindingsMap(build_tool_runs_bindings(self._keymaps))
        self._view = (
            self._session_state.active_view
            if self._session_state.active_view in _VIEWS
            else "runs"
        )
        self._scope_project = _resolve_scope_project(project)
        self._all_projects = self._session_state.all_projects
        self._query = self._session_state.query or ""
        self._run_rows: list[tuple[str, Any]] = []
        self._run_briefs: list[Any] = []
        self._failure_groups: list[dict[str, Any]] = []
        self._catalog_entries: list[Any] = []
        self._catalog_project = ""
        self._catalog_summaries: dict[str, dict[str, Any]] = {}
        self._detail_cache: dict[str, Any] = {}
        self._selected_run_id: str | None = self._session_state.run.identity
        self._pending_run_id: str | None = self._session_state.pending_run_id
        self._loaded_once = False
        self._loading = False
        self._reload_pending = False
        self._poll_timer: Any | None = None
        self._last_token: tuple[object, ...] = ()
        self._tab_active = False

    def compose(self) -> ComposeResult:
        yield Label(self._title_text(), id="tools-pane-title")
        yield PanelTabStrip(
            _VIEW_TABS, self._view, id="tools-view-tabs", show_numbers=False
        )
        yield Input(
            value=self._query,
            placeholder="tool: state: agent: verdict: text",
            id="tools-filter",
        )
        with Horizontal(id="tools-panels"):
            with Vertical(id="tools-list-panel"):
                yield OptionList(id="tools-list")
            with Vertical(id="tools-detail-panel"):
                with VerticalScroll(id="tools-detail-scroll"):
                    yield Static("", id="tools-detail", markup=False)
        yield Static(self._hints(), id="tools-hints", markup=False)

    def on_mount(self) -> None:
        self._last_token = _store_token()
        self._request_reload()
        self._poll_timer = self.set_interval(_POLL_INTERVAL_SECONDS, self._on_poll_tick)

    def on_unmount(self) -> None:
        if self._poll_timer is not None:
            try:
                self._poll_timer.stop()
            except Exception:
                pass
            self._poll_timer = None

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        """Pause polling while the Tools tab is hidden."""

        self._tab_active = bool(active)
        if active:
            self._request_reload()

    def focus_default(self) -> None:
        """Focus the Tools list and refresh on activation."""

        self._request_reload()
        try:
            self.query_one("#tools-list", OptionList).focus()
        except Exception:
            pass

    def focus_tool_run(self, target: ToolRunFocusTarget | str) -> bool:
        """Hold *run_id* as pending until the first load lands, then select."""

        run_id = target.run_id if isinstance(target, ToolRunFocusTarget) else target
        if not run_id:
            return False
        self._pending_run_id = run_id
        self._session_state.pending_run_id = run_id
        if self._loaded_once:
            return self._select_run(run_id)
        if self._view != "runs":
            self._set_view("runs")
        return True

    def _is_active_tab(self) -> bool:
        try:
            return getattr(self.screen, "_active_tab", None) == self.id
        except Exception:
            return False

    def _title_text(self) -> str:
        scope = (
            "all projects"
            if self._all_projects
            else (self._scope_project or "current project")
        )
        return f"⚒ Tools   Runs │ Failures │ Catalog      +{scope} · A all projects"

    def _hints(self) -> str:
        return (
            "j/k: move  enter: detail  a: agent  s: stop  r: run"
            "  v: log  y: copy id  /: filter  [ ]: view  A: all  R: reload"
            "  Esc: close"
        )

    def _set_view(self, view: str) -> None:
        if view not in _VIEWS:
            return
        self._view = view
        self._session_state.active_view = view
        try:
            self.query_one("#tools-view-tabs", PanelTabStrip).set_active_tab(view)
        except Exception:
            pass
        self._rebuild_list()
        self._render_detail()

    def _request_reload(self, *, force: bool = False) -> None:
        if self._loading:
            self._reload_pending = True
            return
        self._loading = True
        self._reload_pending = False
        if force:
            self._detail_cache.clear()
        self.run_worker(
            self._load_async(force=force),
            exclusive=True,
            group="tools-pane-load",
        )

    async def _load_async(self, *, force: bool) -> None:
        try:
            await asyncio.to_thread(self._load_sync)
        except Exception:
            pass
        finally:
            self._loading = False
        try:
            self._rebuild_list()
            self._render_detail()
        except Exception:
            pass
        self._loaded_once = True
        if self._reload_pending:
            self._reload_pending = False
            self._request_reload()

    def _load_sync(self) -> None:
        project = None if self._all_projects else self._scope_project
        self._load_runs(project)
        self._load_failures(project)
        self._load_catalog()

    def _load_runs(self, project: str | None) -> None:
        try:
            from sase.core.tool_run import tool_run_briefs, tool_run_live_glance
        except Exception:
            self._run_rows = []
            self._run_briefs = []
            return
        try:
            glance = tool_run_live_glance()
            live_by_id = {run.run_id: run for run in glance.runs}
            silent_after = int(getattr(glance, "silent_after_s", 60) or 60)
        except Exception:
            live_by_id = {}
            silent_after = 60
        try:
            request: dict[str, Any] = {"limit": _RUNS_LIMIT}
            if project is not None:
                request["project"] = project
            briefs = tool_run_briefs(request)
            rows = list(briefs.runs)
        except Exception:
            rows = []
        filtered = filter_briefs(list(rows), self._query, project=None)
        now_ts = int(time.time())
        self._run_briefs = [
            brief
            for _, brief in order_runs(
                filtered, live_by_id, now_ts=now_ts, silent_after_s=silent_after
            )
        ]
        self._run_rows = order_runs(
            filtered, live_by_id, now_ts=now_ts, silent_after_s=silent_after
        )

    def _load_failures(self, project: str | None) -> None:
        try:
            from sase.core.tool_run import tool_run_failures
        except Exception:
            self._failure_groups = []
            return
        try:
            request: dict[str, Any] = {"days": 7, "limit": 50}
            if project is not None:
                request["project"] = project
            result = tool_run_failures(request)
            groups = result.get("groups", ())
            self._failure_groups = [
                dict(group) for group in groups if isinstance(group, dict)
            ]
        except Exception:
            self._failure_groups = []

    def _load_catalog(self) -> None:
        try:
            from sase.config.tools import load_project_tool_catalog_at
            from sase.core.tool_run import tool_run_summary
        except Exception:
            self._catalog_entries = []
            return
        try:
            from sase.ace.tui.actions.agents._tool_run_actions import (
                primary_checkout_root,
            )

            root = primary_checkout_root(self._scope_project) or None
        except Exception:
            root = None
        try:
            catalog = load_project_tool_catalog_at(root)
        except Exception:
            self._catalog_entries = []
            return
        self._catalog_entries = list(catalog.entries)
        self._catalog_project = str(getattr(catalog, "project", "") or "")
        summaries: dict[str, dict[str, Any]] = {}
        for entry in self._catalog_entries[:50]:
            try:
                summaries[entry.name] = tool_run_summary(
                    {
                        "schema_version": 1,
                        "project": catalog.project,
                        "tool_name": entry.name,
                        "definition_digest": entry.digest,
                    }
                )
            except Exception:
                continue
        self._catalog_summaries = summaries

    def _on_poll_tick(self) -> None:
        if not self._is_active_tab() and self._tab_active is False:
            pass
        token = _store_token()
        if token == self._last_token:
            return
        self._last_token = token
        if self._is_active_tab() or self._tab_active:
            self._request_reload()

    def _rebuild_list(self) -> None:
        try:
            option_list = self.query_one("#tools-list", OptionList)
        except Exception:
            return
        option_list.clear_options()
        if self._view == "runs":
            if not self._run_rows and self._loaded_once:
                option_list.add_option(Option("No tool runs in scope", disabled=True))
            for kind, brief in self._run_rows:
                run_id = str(getattr(brief, "run_id", "") or "")
                option_list.add_option(Option(format_run_row(kind, brief), id=run_id))
            if self._pending_run_id:
                self._select_run(self._pending_run_id)
            elif self._selected_run_id:
                self._select_run(self._selected_run_id)
        elif self._view == "failures":
            if not self._failure_groups and self._loaded_once:
                option_list.add_option(Option("No recorded failures", disabled=True))
            for index, group in enumerate(self._failure_groups):
                option_list.add_option(
                    Option(format_failure_row(group), id=f"failure-{index}")
                )
        else:
            if not self._catalog_entries and self._loaded_once:
                option_list.add_option(Option("No tools in catalog", disabled=True))
            for entry in self._catalog_entries:
                name = str(getattr(entry, "name", "") or "")
                option_list.add_option(Option(self._catalog_row(name), id=name))
        try:
            self.query_one("#tools-pane-title", Label).update(self._title_text())
        except Exception:
            pass

    def _catalog_row(self, name: str) -> str:
        summary = self._catalog_summaries.get(name, {})
        last = summary.get("last") if isinstance(summary, dict) else None
        typical_ms = (
            summary.get("typical_duration_ms") if isinstance(summary, dict) else None
        )
        samples = (
            summary.get("typical_sample_count") if isinstance(summary, dict) else 0
        )
        last_text = "no runs yet"
        if isinstance(last, dict):
            bucket = str(last.get("bucket", "") or "")
            last_text = f"LAST {bucket}" if bucket else "LAST ?"
        typical_text = (
            f"TYPICAL n={int(samples or 0)}"
            if typical_ms is None
            else f"TYPICAL {self._format_ms(typical_ms)} n={int(samples or 0)}"
        )
        return f"{name}  {last_text}  {typical_text}".rstrip()

    @staticmethod
    def _format_ms(value: Any) -> str:
        try:
            total_ms = int(value)
        except (TypeError, ValueError):
            return "?"
        if total_ms < 1000:
            return f"{total_ms}ms"
        seconds = total_ms / 1000
        if seconds < 60:
            return f"{seconds:.0f}s"
        return f"{seconds / 60:.0f}m"

    def _selected_identity(self) -> str | None:
        try:
            option_list = self.query_one("#tools-list", OptionList)
            highlighted = option_list.highlighted
        except Exception:
            return None
        if highlighted is None:
            return None
        identity = getattr(highlighted, "id", None)
        return str(identity) if identity else None

    def _select_run(self, run_id: str) -> bool:
        try:
            option_list = self.query_one("#tools-list", OptionList)
        except Exception:
            return False
        for index in range(option_list.option_count):
            try:
                option = option_list.get_option_at_index(index)
            except Exception:
                continue
            if str(getattr(option, "id", "") or "") == run_id:
                option_list.highlighted = index
                self._selected_run_id = run_id
                self._session_state.run.record(run_id, index)
                self._pending_run_id = None
                self._session_state.pending_run_id = None
                self._render_detail()
                return True
        return False

    def _render_detail(self) -> None:
        try:
            detail = self.query_one("#tools-detail", Static)
        except Exception:
            return
        try:
            width = max(40, int(self.size.width) - 4)
        except Exception:
            width = 100
        if self._view == "runs":
            detail.update(self._runs_detail_text(width))
        elif self._view == "failures":
            detail.update(self._failures_detail_text())
        else:
            detail.update(self._catalog_detail_text())

    def _runs_detail_text(self, width: int) -> str:
        run_id = self._selected_identity() or self._selected_run_id
        brief = next(
            (
                item
                for _, item in self._run_rows
                if str(getattr(item, "run_id", "")) == run_id
            ),
            None,
        )
        if brief is None and self._run_rows:
            _kind, brief = self._run_rows[0]
            run_id = str(getattr(brief, "run_id", "") or "")
        if brief is None:
            if not self._loaded_once:
                return "Loading tool runs…"
            return "No tool runs in scope."
        detail_obj = self._detail_for(run_id)
        try:
            from rich.console import Console

            from sase.ace.tui.tool_runs.blocks import render_tool_run_block

            text = render_tool_run_block(
                brief,
                detail_obj,
                level=ToolRunsDetailLevel.STANDARD,
                width=width,
            )
            console = Console(width=width)
            with console.capture() as capture:
                console.print(text, end="")
            return capture.get()
        except Exception:
            return format_run_row("settled", brief)

    def _detail_for(self, run_id: str | None) -> Any | None:
        if not run_id:
            return None
        if run_id in self._detail_cache:
            return self._detail_cache[run_id]
        try:
            from sase.core.tool_run import tool_run_detail
        except Exception:
            return None
        try:
            detail_obj = tool_run_detail(run_id)
        except Exception:
            return None
        if len(self._detail_cache) >= 32:
            self._detail_cache.pop(next(iter(self._detail_cache)))
        self._detail_cache[run_id] = detail_obj
        return detail_obj

    def _failures_detail_text(self) -> str:
        identity = self._selected_identity()
        index = 0
        if identity and identity.startswith("failure-"):
            try:
                index = int(identity.split("-", 1)[1])
            except (ValueError, IndexError):
                index = 0
        if not self._failure_groups:
            return (
                "Loading failures…"
                if not self._loaded_once
                else "No recorded failures."
            )
        if not 0 <= index < len(self._failure_groups):
            index = 0
        group = self._failure_groups[index]
        lines = [
            format_failure_row(group),
            "",
            f"signature: {group.get('signature', '')}",
            f"runs: {group.get('runs', group.get('witness_runs', 0))}"
            f" · agents: {group.get('agents', group.get('witness_agents', 0))}",
            f"first seen: {group.get('first_seen', group.get('first_seen_ts', ''))}"
            f" · last seen: {group.get('last_seen', group.get('last_seen_ts', ''))}",
            "",
            "enter lists affected runs · a jumps to one",
        ]
        return "\n".join(str(line) for line in lines)

    def _catalog_detail_text(self) -> str:
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
            name = str(getattr(entry, "name", "") or "")
        if entry is None:
            return (
                "Loading catalog…" if not self._loaded_once else "No tools in catalog."
            )
        definition = getattr(entry, "definition", {}) or {}
        argv = definition.get("argv", ())
        lines = [
            f"{name} · project {self._catalog_project or 'unknown'}",
            f"$ {' '.join(str(part) for part in argv)}".rstrip(),
            f"stages: {definition.get('stages', 'none')}"
            f" · args: {definition.get('args', 'deny')}",
            self._catalog_row(str(name or "")),
            "",
            "r runs the selected tool at the project root.",
        ]
        return "\n".join(lines)

    def on_option_list_option_highlighted(
        self, _event: OptionList.OptionHighlighted
    ) -> None:
        """Repaint detail as the cursor moves; record the selection."""

        identity = self._selected_identity()
        if self._view == "runs" and identity:
            self._selected_run_id = identity
            self._session_state.run.record(identity, None)
        self._render_detail()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        """Focus detail on enter; failures enter is a no-op detail refresh."""

        self._render_detail()
        try:
            self.query_one("#tools-detail-scroll", VerticalScroll).focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refilter runs as the ``/`` query changes."""

        if getattr(event.input, "id", "") != "tools-filter":
            return
        self._query = event.value or ""
        self._session_state.query = self._query
        self._load_runs(None if self._all_projects else self._scope_project)
        self._rebuild_list()
        self._render_detail()

    def on_key(self, event: events.Key) -> None:
        """Handle view-local keys before the modal's numbered tab keys."""

        from sase.ace.tui.keymaps import split_key_alternatives

        keys = self._keymaps
        key = event.key or ""
        if key in split_key_alternatives(keys.cycle_subtab):
            event.prevent_default()
            event.stop()
            self.action_cycle_subtab()
        elif key in split_key_alternatives(keys.cycle_subtab_reverse):
            event.prevent_default()
            event.stop()
            self.action_cycle_subtab_reverse()
        elif key in split_key_alternatives(keys.toggle_scope):
            event.prevent_default()
            event.stop()
            self.action_toggle_scope()
        elif key in split_key_alternatives(keys.reload):
            event.prevent_default()
            event.stop()
            self.action_reload_tool_runs()

    def action_next_option(self) -> None:
        """Move the list cursor down."""

        try:
            self.query_one("#tools-list", OptionList).action_cursor_down()
        except Exception:
            pass

    def action_prev_option(self) -> None:
        """Move the list cursor up."""

        try:
            self.query_one("#tools-list", OptionList).action_cursor_up()
        except Exception:
            pass

    def action_focus_filter(self) -> None:
        """Focus the ``/`` filter input."""

        try:
            self.query_one("#tools-filter", Input).focus()
        except Exception:
            pass

    def action_cycle_subtab(self) -> None:
        """Switch to the next Tools view."""

        self._set_view(_VIEWS[(_VIEWS.index(self._view) + 1) % len(_VIEWS)])

    def action_cycle_subtab_reverse(self) -> None:
        """Switch to the previous Tools view."""

        self._set_view(_VIEWS[(_VIEWS.index(self._view) - 1) % len(_VIEWS)])

    def action_toggle_scope(self) -> None:
        """Toggle current-project filtering (``A`` toggles all projects)."""

        self._all_projects = not self._all_projects
        self._session_state.all_projects = self._all_projects
        self._request_reload(force=True)

    def action_reload_tool_runs(self) -> None:
        """Reload all three Tools views."""

        self._request_reload(force=True)

    def action_focus_detail(self) -> None:
        """Focus the detail region."""

        try:
            self.query_one("#tools-detail-scroll", VerticalScroll).focus()
        except Exception:
            pass

    def action_jump_to_agent(self) -> None:
        """Close the modal and reveal the selected run's owning agent row."""

        from .config_center_modal import ConfigCenterModal

        brief = next(
            (
                item
                for _, item in self._run_rows
                if str(getattr(item, "run_id", "") or "")
                == (self._selected_identity() or self._selected_run_id or "")
            ),
            None,
        )
        agent_name = str(getattr(brief, "agent", "") or "") if brief is not None else ""
        if not agent_name:
            self.notify("No owning agent for the selected run", severity="warning")
            return
        screen = self.screen
        if not isinstance(screen, ConfigCenterModal):
            return
        screen.action_close()
        app = self.app

        def _reveal() -> None:
            try:
                app._save_current_tab_position()  # type: ignore[attr-defined]
                app.current_tab = "agents"  # type: ignore[attr-defined]
                app._reveal_agent_row(  # type: ignore[attr-defined]
                    agent_name, subject="Tool run agent"
                )
            except Exception as exc:
                self.notify(f"Could not reveal agent: {exc}", severity="warning")

        app.call_after_refresh(_reveal)

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
    def _read_tail(brief: Any, detail_obj: Any) -> Any:
        from sase.tool.logs import tool_run_log_tail

        logs = getattr(detail_obj, "logs", None) if detail_obj is not None else None
        metadata = (
            logs.to_tail_metadata()
            if logs is not None and hasattr(logs, "to_tail_metadata")
            else {}
        )
        return tool_run_log_tail(
            str(getattr(brief, "run_id", "") or ""),
            metadata,
            getattr(brief, "owner_kind", None),
            getattr(brief, "owner_id", None),
            60,
            256 * 1024,
        )

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


__all__ = ["ToolRunsPane"]
