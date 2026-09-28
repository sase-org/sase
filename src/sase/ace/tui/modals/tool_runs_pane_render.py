"""List and detail rendering for the Admin Center Tools pane (sase-1bt.10)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Label, OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.tool_runs.deck import ToolRunsDetailLevel

from .tool_runs_pane_data import format_failure_row, format_run_row

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .config_center_session import ToolRunsSessionState
else:
    _MixinBase = object


class ToolRunsPaneRenderMixin(_MixinBase):
    """Rebuild the Runs/Failures/Catalog list and paint the detail region."""

    if TYPE_CHECKING:
        _catalog_entries: list[Any]
        _catalog_project: str
        _catalog_summaries: dict[str, dict[str, Any]]
        _detail_cache: dict[str, Any]
        _failure_groups: list[dict[str, Any]]
        _loaded_once: bool
        _pending_run_id: str | None
        _run_rows: list[tuple[str, Any]]
        _selected_run_id: str | None
        _session_state: ToolRunsSessionState
        _view: str

        def _title_text(self) -> str: ...

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

    def _runs_detail_text(self, width: int) -> str | Text:
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
            from sase.ace.tui.tool_runs.blocks import render_tool_run_block

            return render_tool_run_block(
                brief,
                detail_obj,
                level=ToolRunsDetailLevel.STANDARD,
                width=width,
            )
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


__all__ = ["ToolRunsPaneRenderMixin"]
