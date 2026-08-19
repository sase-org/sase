"""Modal for choosing and launching an interactive agent CLI in a new tmux window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import os
from pathlib import Path
import shlex

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.config.tmux_agent import TmuxAgentConfig, get_tmux_agent_config
from sase.llm_provider import registry as llm_registry
from sase.tmux_agent import (
    TmuxAgentCatalog,
    TmuxAgentEntry,
    TmuxAgentLaunch,
    TmuxAgentLaunchError,
    TmuxRunner,
    launch_agent_window,
    next_window_name,
)

from .base import OptionListNavigationMixin
from .models_panel_duration import now as _wall_clock_now
from .models_panel_provider_state import remaining_label

_CATALOG_GROUP = "tmux-agent-catalog"
_LAUNCH_GROUP = "tmux-agent-launch"

_COLOR_SELECTOR = "bold #D7AF5F"
_COLOR_VENDOR = "dim #565f89"
_COLOR_READY = "bold #87D787"
_COLOR_NOT_INSTALLED = "dim #A8A8A8"
_COLOR_ROUTING_DISABLED = "bold #FFAF5F"
_COLOR_DESCRIPTION = "#B0B0B0"

_MAX_NAME_LEN = 24
_MAX_VENDOR_LEN = 14


@dataclass(frozen=True)
class _TmuxAgentModalState:
    """One completed background load: the catalog plus a window-name preview."""

    catalog: TmuxAgentCatalog
    preview_window_name: str


def _short_text(value: str, *, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return value[: max_len - 1] + "…"


def _compact_path(path: str) -> str:
    """Return a home-relative display for ``path`` when possible."""
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = ""
    if home and path.startswith(home):
        return "~" + path[len(home) :]
    return path


def _entry_row_text(entry: TmuxAgentEntry, *, now: float) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{entry.key or ' '}  ", style=_COLOR_SELECTOR)
    accent = entry.color or "#a9b1d6"
    text.append("● ", style=accent)
    text.append(
        _short_text(entry.display_name, max_len=_MAX_NAME_LEN).ljust(_MAX_NAME_LEN),
        style=f"bold {accent}",
    )
    text.append("  ")
    text.append(
        _short_text(entry.vendor, max_len=_MAX_VENDOR_LEN).ljust(_MAX_VENDOR_LEN),
        style=_COLOR_VENDOR,
    )
    text.append("  ")
    if not entry.installed:
        text.append("not installed", style=_COLOR_NOT_INSTALLED)
    elif entry.routing_disabled is not None:
        text.append(
            f"routing disabled · {remaining_label(entry.routing_disabled, now=now)}",
            style=_COLOR_ROUTING_DISABLED,
        )
    else:
        text.append("ready", style=_COLOR_READY)
    return text


def _strip_bypass_args(entry: TmuxAgentEntry) -> tuple[str, ...]:
    """Return *entry*'s argv with its provider's bypass flags removed."""
    descriptor = llm_registry.provider_interactive_cli_map().get(entry.provider) or {}
    bypass_args = set(descriptor.get("bypass_args") or ())
    if not bypass_args:
        return entry.argv
    return tuple(token for token in entry.argv if token not in bypass_args)


class TmuxAgentModal(OptionListNavigationMixin, ModalScreen[bool]):
    """Keyboard-first chooser that launches an agent CLI in a new tmux window."""

    _option_list_id = "tmux-agent-list"

    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "launch", "Launch"),
        ("s", "launch_safe", "Safe launch"),
    ]

    def __init__(
        self,
        catalog: TmuxAgentCatalog,
        *,
        load_catalog: Callable[[], TmuxAgentCatalog],
        config: TmuxAgentConfig | None = None,
        runner: TmuxRunner | None = None,
    ) -> None:
        super().__init__()
        self._load_catalog = load_catalog
        self._config = config if config is not None else get_tmux_agent_config()
        self._runner = runner if runner is not None else TmuxRunner()
        self._preview_window_name = ""
        self._updating_highlight = False
        self._pending_provider = ""
        self._catalog_worker: Worker[_TmuxAgentModalState] | None = None
        self._launch_worker: Worker[TmuxAgentLaunch | TmuxAgentLaunchError] | None = (
            None
        )
        self._apply_catalog_state(catalog, "")

    def compose(self) -> ComposeResult:
        with Container(id="tmux-agent-container"):
            yield Static(self._title_text(), id="tmux-agent-title")
            yield Static(
                "Opens a new tmux window in this directory.",
                id="tmux-agent-summary",
            )
            yield OptionList(*self._build_options(), id=self._option_list_id)
            yield Static("", id="tmux-agent-description")
            yield Static(self._footer_text(), id="tmux-agent-footer")

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.focus()
        self._restore_highlight(option_list, None)
        self._update_description()
        self._start_catalog_load()

    def on_unmount(self) -> None:
        for worker in (self._catalog_worker, self._launch_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()

    def _now(self) -> float:
        return _wall_clock_now()

    # -- catalog loading -----------------------------------------------

    def _start_catalog_load(self) -> None:
        if self._catalog_worker is not None and not self._catalog_worker.is_finished:
            self._catalog_worker.cancel()

        def task() -> _TmuxAgentModalState:
            catalog = self._load_catalog()
            existing = tuple(name for _index, name in self._runner.list_windows())
            preview = next_window_name(self._config.window_name, existing)
            return _TmuxAgentModalState(catalog=catalog, preview_window_name=preview)

        self._catalog_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_CATALOG_GROUP,
        )

    def _apply_catalog_state(
        self, catalog: TmuxAgentCatalog, preview_window_name: str
    ) -> None:
        self._catalog = catalog
        self._entries_by_provider = {entry.provider: entry for entry in catalog.entries}
        self._provider_by_key = {
            entry.key: entry.provider for entry in catalog.entries if entry.key
        }
        self._preview_window_name = preview_window_name

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._catalog_worker:
            self._on_catalog_worker(event)
        elif event.worker is self._launch_worker:
            self._on_launch_worker(event)

    def _on_catalog_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._catalog_worker = None
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            state = event.worker.result
            keep = self._highlighted_provider()
            self._apply_catalog_state(state.catalog, state.preview_window_name)
            option_list = self.query_one(f"#{self._option_list_id}", OptionList)
            option_list.clear_options()
            option_list.add_options(self._build_options())
            self._restore_highlight(option_list, keep)
            self._refresh_title()
            self._refresh_footer()
            self._update_description()
        elif event.state == WorkerState.ERROR:
            self.notify(
                f"Could not load tmux Agent catalog: {event.worker.error}",
                severity="warning",
            )

    # -- launching --------------------------------------------------------

    def _launch_busy(self) -> bool:
        return self._launch_worker is not None and not self._launch_worker.is_finished

    def action_launch(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        self._start_launch(entry.provider, safe=False)

    def action_launch_safe(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        self._start_launch(entry.provider, safe=True)

    def on_key(self, event: events.Key) -> None:
        provider = self._provider_by_key.get(event.key)
        if provider is None:
            return
        event.prevent_default()
        event.stop()
        self._start_launch(provider, safe=False)

    def _start_launch(self, provider: str, *, safe: bool) -> None:
        if self._launch_busy():
            self.notify("A tmux Agent launch is still in progress.", severity="warning")
            return
        entry = self._entries_by_provider.get(provider)
        if entry is None:
            return
        launch_entry = entry
        if safe and entry.bypass:
            launch_entry = replace(entry, argv=_strip_bypass_args(entry), bypass=False)
        directory = (
            self._catalog.directory
            or self._runner.current_pane_directory()
            or os.getcwd()
        )
        config = self._config
        runner = self._runner

        def task() -> TmuxAgentLaunch | TmuxAgentLaunchError:
            return launch_agent_window(
                launch_entry, directory=directory, config=config, runner=runner
            )

        self._pending_provider = provider
        self._launch_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_LAUNCH_GROUP,
        )

    def _on_launch_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        provider = self._pending_provider
        self._pending_provider = ""
        self._launch_worker = None
        if event.state == WorkerState.ERROR:
            self.notify(
                f"Could not launch {provider}: {event.worker.error}", severity="error"
            )
            return
        result = event.worker.result
        if isinstance(result, TmuxAgentLaunchError):
            self.notify(result.message, severity="error")
            return
        if result is None:
            self.notify(f"Could not launch {provider}: unknown error", severity="error")
            return
        entry = self._entries_by_provider.get(provider)
        display = entry.display_name if entry is not None else provider
        self.notify(f"Opened tmux window: {result.window_name} · {display}")
        self.dismiss(True)

    # -- rendering ----------------------------------------------------

    def action_cancel(self) -> None:
        if self._launch_busy():
            self.notify("A tmux Agent launch is still in progress.", severity="warning")
            return
        self.dismiss(False)

    def _title_text(self) -> str:
        if not self._catalog.directory:
            return "tmux Agent · loading…"
        count = len(self._catalog.entries)
        plural = "" if count == 1 else "s"
        return (
            f"tmux Agent · {count} agent CLI{plural} · "
            f"{_compact_path(self._catalog.directory)}"
        )

    def _refresh_title(self) -> None:
        try:
            title = self.query_one("#tmux-agent-title", Static)
        except Exception:
            return
        title.update(self._title_text())

    def _footer_text(self) -> str:
        close_hint = (
            "[dim]esc[/dim]=Close"
            if "q" in self._provider_by_key
            else "[dim]esc/q[/dim]=Close"
        )
        return (
            "[green]enter/key[/green]=Launch  "
            "[green]s[/green]=Safe launch  "
            "[dim]j/k[/dim]=Navigate  "
            f"{close_hint}"
        )

    def _refresh_footer(self) -> None:
        try:
            footer = self.query_one("#tmux-agent-footer", Static)
        except Exception:
            return
        footer.update(self._footer_text())

    def _build_options(self) -> list[Option]:
        entries = self._catalog.entries
        if not entries:
            return [
                Option(
                    Text("No agent CLIs registered.", style="dim"),
                    id="__empty__",
                    disabled=True,
                )
            ]
        now = self._now()
        return [
            Option(
                _entry_row_text(entry, now=now),
                id=entry.provider,
                disabled=not entry.installed,
            )
            for entry in entries
        ]

    @staticmethod
    def _option_is_disabled(option_list: OptionList, index: int) -> bool:
        try:
            return option_list.get_option_at_index(index).disabled
        except Exception:
            return True

    @classmethod
    def _first_enabled_option_index(cls, option_list: OptionList) -> int | None:
        for index in range(option_list.option_count):
            if not cls._option_is_disabled(option_list, index):
                return index
        return None

    def _set_highlighted_index(
        self,
        option_list: OptionList,
        index: int | None,
    ) -> None:
        self._updating_highlight = True
        try:
            option_list.highlighted = index
        finally:
            self._updating_highlight = False

    def _restore_highlight(
        self,
        option_list: OptionList,
        preferred: str | None,
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                if not self._option_is_disabled(option_list, index):
                    self._set_highlighted_index(option_list, index)
                    return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list,
            self._first_enabled_option_index(option_list),
        )

    def _highlighted_provider(self) -> str | None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        provider = str(option.id) if option.id is not None else ""
        return provider if provider in self._entries_by_provider else None

    def _highlighted_entry(self) -> TmuxAgentEntry | None:
        provider = self._highlighted_provider()
        if provider is None:
            return None
        return self._entries_by_provider.get(provider)

    def _update_description(self) -> None:
        try:
            description = self.query_one("#tmux-agent-description", Static)
        except Exception:
            return
        description.update(self._description_text(self._highlighted_entry()))

    def _description_text(self, entry: TmuxAgentEntry | None) -> Text:
        if entry is None:
            return Text("", style=_COLOR_DESCRIPTION)
        text = Text(style=_COLOR_DESCRIPTION, no_wrap=False)
        text.append(shlex.join(entry.argv))
        if not entry.installed:
            hint = (
                entry.install_hint.strip() or f"{entry.display_name} is not installed."
            )
            text.append(f"\n{hint}", style="dim")
            return text
        window_name = self._preview_window_name or self._config.window_name
        parts = [f"opens tmux window {window_name}"]
        if entry.effort:
            parts.append(f"effort {entry.effort}")
        if entry.effort_skipped:
            parts.append(f"effort {entry.effort_skipped} unsupported, skipped")
        parts.append("bypass on" if entry.bypass else "bypass off")
        text.append(f"\n{' · '.join(parts)}", style="dim")
        return text

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if self._updating_highlight:
            return
        self._update_description()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_launch()


__all__ = ["TmuxAgentModal"]
