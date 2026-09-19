"""Config hub Holds pane: list active ``sase agent hold`` records, release one.

Modeled on the runner-limit override panel's worker-driven load/apply shape
(``models_panel_runner_limit.py``) but simplified to a single scrollable
list -- holds are a variable-length collection with one mutation (release),
not a scalar setting with an edit chain.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import format_compact_duration
from sase.core.agent_hold_pending import format_stored_capture
from sase.core.time import get_timezone

from .base import CopyModeForwardingMixin
from .catalog_pane_contract import CatalogPaneHost

_LIST_ID = "holds-pane-list"


class HoldsPane(CopyModeForwardingMixin, Vertical):
    """Browse active agent holds and release one."""

    can_focus = False
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("d", "release_highlighted", "Release"),
        ("j", "next_hold", "Next"),
        ("k", "prev_hold", "Previous"),
        ("down", "next_hold", "Next"),
        ("up", "prev_hold", "Previous"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        *,
        host: CatalogPaneHost | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._host = host
        self._host_visible = True
        self._holds: tuple[dict[str, Any], ...] = ()
        self._loading = True
        self._error: str | None = None
        self._load_generation = 0
        self._load_worker: Worker[tuple[int, list[dict[str, Any]]]] | None = None
        self._release_worker: Worker[str | None] | None = None
        self._releasing = False

    def compose(self) -> ComposeResult:
        with Container(id="holds-pane-container"):
            yield Static(self._header_text(), id="holds-pane-header")
            yield OptionList(id=_LIST_ID)
            yield Static("", id="holds-pane-footer")

    def on_mount(self) -> None:
        self.focus_default()
        self._start_load()

    def on_unmount(self) -> None:
        for worker in (self._load_worker, self._release_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def on_key(self, event: events.Key) -> None:
        from .config_hub_keys import handle_config_hub_subtab_select_key

        if handle_config_hub_subtab_select_key(self, event):
            return
        super().on_key(event)

    def focus_default(self) -> None:
        """Focus the hold list when this pane is the active surface."""
        if not self._host_visible:
            return
        try:
            self.app.set_focus(self._hold_list())
        except Exception:
            pass

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self._host_visible = active
        if active:
            self._update_header()
            self._update_footer()
            self.focus_default()

    def action_close(self) -> None:
        if self._host is not None:
            self._host.request_close()

    def action_refresh(self) -> None:
        if self._releasing:
            return
        self._start_load()

    def action_next_hold(self) -> None:
        if self._holds:
            self._hold_list().action_cursor_down()

    def action_prev_hold(self) -> None:
        if self._holds:
            self._hold_list().action_cursor_up()

    def action_release_highlighted(self) -> None:
        hold = self._selected_hold()
        if hold is None or self._releasing:
            return
        armer = hold.get("armer")
        armer_key = armer.get("key") if isinstance(armer, Mapping) else None
        if not isinstance(armer_key, str) or not armer_key:
            return
        self._start_release(armer_key)

    def _list_holds(self) -> list[dict[str, Any]]:
        """Return active holds. A seam tests monkeypatch on the class."""
        from sase.core.agent_hold_facade import list_current_agent_holds

        return list_current_agent_holds()

    def _release_hold(self, armer_key: str) -> None:
        """Release one hold. A seam tests monkeypatch on the class."""
        from sase.core.agent_hold_facade import release_agent_hold

        release_agent_hold(armer_key, reason="Released from the TUI hold panel")

    def _start_load(self) -> None:
        self._loading = True
        self._error = None
        self._update_header()
        self._update_footer()
        self._load_generation += 1
        generation = self._load_generation

        def task() -> tuple[int, list[dict[str, Any]]]:
            return generation, self._list_holds()

        self._load_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="holds-pane-load",
        )

    def _start_release(self, armer_key: str) -> None:
        self._releasing = True
        self._update_footer()

        def task() -> str | None:
            try:
                self._release_hold(armer_key)
            except Exception as exc:  # noqa: BLE001 - surfaced via notify().
                return str(exc)
            return None

        self._release_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="holds-pane-release",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            self._on_load_state_changed(event)
        elif event.worker is self._release_worker:
            self._on_release_state_changed(event)

    def _on_load_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {WorkerState.SUCCESS, WorkerState.ERROR}:
            return
        if event.state == WorkerState.ERROR:
            self._loading = False
            self._error = "Hold list failed to load."
            self._holds = ()
            self._render_rows()
            self.focus_default()
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 2:
            return
        generation, holds = result
        if generation != self._load_generation:
            return
        self._loading = False
        self._error = None
        self._holds = tuple(holds)
        self._render_rows()
        self.focus_default()

    def _on_release_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {WorkerState.SUCCESS, WorkerState.ERROR}:
            return
        self._releasing = False
        if event.state == WorkerState.SUCCESS:
            error = event.worker.result
            if isinstance(error, str) and error:
                self.notify(f"Release failed: {error}", severity="error")
            else:
                self.notify("Hold released")
        else:
            self.notify("Release failed", severity="error")
        self._start_load()

    def _render_rows(self) -> None:
        option_list = self._hold_list()
        highlighted = option_list.highlighted
        option_list.clear_options()
        now = datetime.now(get_timezone())
        option_list.add_options(
            Option(_hold_row_text(hold, now=now), id=_armer_key(hold))
            for hold in self._holds
        )
        if self._holds:
            option_list.highlighted = (
                highlighted
                if highlighted is not None and highlighted < len(self._holds)
                else 0
            )
        self._update_header()
        self._update_footer()

    def _selected_hold(self) -> dict[str, Any] | None:
        if not self._holds:
            return None
        row = self._hold_list().highlighted
        if row is None or not 0 <= row < len(self._holds):
            return None
        return self._holds[row]

    def _hold_list(self) -> OptionList:
        return self.query_one(f"#{_LIST_ID}", OptionList)

    def _header_text(self) -> Text:
        if self._loading:
            return Text("Loading agent holds…", style="dim")
        if self._error:
            return Text(self._error, style="bold red")
        count = len(self._holds)
        label = "hold" if count == 1 else "holds"
        return Text(f"Agent Holds ({count} active {label})", style="bold")

    def _update_header(self) -> None:
        try:
            self.query_one("#holds-pane-header", Static).update(self._header_text())
        except Exception:
            pass

    def _update_footer(self) -> None:
        text = (
            "Releasing…"
            if self._releasing
            else "j/k move · d release · r refresh · q close"
        )
        try:
            self.query_one("#holds-pane-footer", Static).update(text)
        except Exception:
            pass


def _armer_key(hold: Mapping[str, Any]) -> str | None:
    armer = hold.get("armer")
    key = armer.get("key") if isinstance(armer, Mapping) else None
    return key if isinstance(key, str) else None


def _hold_row_text(hold: Mapping[str, Any], *, now: datetime) -> Text:
    raw_armer = hold.get("armer")
    armer: Mapping[str, Any] = raw_armer if isinstance(raw_armer, Mapping) else {}
    display = str(armer.get("display") or armer.get("key") or "?")
    kind = str(armer.get("kind") or "?")
    raw_scope = hold.get("scope")
    scope: Mapping[str, Any] = raw_scope if isinstance(raw_scope, Mapping) else {}
    scope_label = (
        "host"
        if scope.get("kind") == "host"
        else f"project:{scope.get('project', '?')}"
    )
    raw_selectors = hold.get("selectors")
    selectors: Mapping[str, Any] = (
        raw_selectors if isinstance(raw_selectors, Mapping) else {}
    )
    selectors_label = _selectors_label(selectors)
    capture_label = format_stored_capture(hold)
    expiry_label = _expiry_label(hold.get("expires_at"), now=now)

    text = Text()
    text.append(display, style="bold")
    text.append(f" ({kind})", style="dim")
    text.append(f"  {scope_label}", style="")
    text.append(f"  {selectors_label}", style="dim")
    text.append(f"  {capture_label}", style="dim")
    text.append(f"  {expiry_label}", style="dim cyan")
    return text


def _selectors_label(selectors: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("names", "hoods", "tribes"):
        values = selectors.get(key) or []
        if values:
            parts.append(f"{key}={','.join(str(value) for value in values)}")
    if selectors.get("future"):
        parts.append("future")
    artifact_dirs = selectors.get("artifact_dirs") or []
    if artifact_dirs:
        parts.append(f"pending={len(artifact_dirs)}")
    return "; ".join(parts) if parts else "(none)"


def _expiry_label(expires_at: object, *, now: datetime) -> str:
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return "expires ?"
    remaining = expires_at - now.timestamp()
    if remaining <= 0:
        return "expired"
    return f"expires {format_compact_duration(remaining)}"


__all__ = ["HoldsPane"]
