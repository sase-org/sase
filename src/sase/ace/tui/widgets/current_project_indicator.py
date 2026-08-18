"""Current-project chip for the ACE TUI top bar.

Renders ``+<display_name>`` boxed by two accent-colored rails and a tinted
plate, immediately after the provider-disables pill. Empty (zero width) when
no project resolves or when ``ace.current_project.indicator`` is false.

The periodic tick only peeks a cheap change token. The real
:func:`sase.current_project.resolve_current_project` call — plus the enabled
project key set used for accent assignment — runs on a worker thread.

Clicking opens the ``+`` launch picker. The current project is a pure
derivation of the VCS xprompt MRU store: launching an agent is how it moves.
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
from typing import Any

from rich.text import Text
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.project_styles import project_accent, project_chip_plate
from sase.current_project import (
    CurrentProject,
    peek_current_project_change_token,
    resolve_current_project,
)
from sase.xprompt.loader import get_known_project_workspaces

# Same cadence as :class:`LLMOverrideIndicator`. Affordable only because the
# tick is a peek (time-gated ``os.stat`` + config token), not a resolve.
_POLL_INTERVAL_SECONDS = 5.0
_WORKER_GROUP = "current-project-indicator"
_LAUNCH_HINT = "Launch an agent on a project to make it current."

_FRAME_LEFT = "▏"  # U+258F LEFT ONE EIGHTH BLOCK
_FRAME_RIGHT = "▕"  # U+2595 RIGHT ONE EIGHTH BLOCK


@functools.cache
def _fallback_theme_background() -> str:
    """Return the pinned theme's background when no live app theme is usable."""

    from textual.theme import BUILTIN_THEMES

    from sase.xprompt.highlight_theme import ACE_THEME_NAME

    return BUILTIN_THEMES[ACE_THEME_NAME].background or "#000000"


@dataclass(frozen=True, slots=True)
class _CurrentProjectSnapshot:
    """Resolved current project plus the accent computed off-thread."""

    project: CurrentProject | None
    accent: str


def _enabled_project_keys() -> tuple[str, ...]:
    """Return enabled project keys for accent assignment.

    Disk-backed; call only from the off-thread resolve worker.
    """

    return tuple(get_known_project_workspaces())


def _resolve_snapshot() -> _CurrentProjectSnapshot | None:
    """Resolve the current project and its accent off the UI thread."""

    try:
        project = resolve_current_project()
        enabled_keys = _enabled_project_keys()
        accent = ""
        if project is not None:
            accent = project_accent(project.project_key, among=enabled_keys)
    except Exception:  # noqa: BLE001 - display reads always degrade.
        return None
    return _CurrentProjectSnapshot(project=project, accent=accent)


class CurrentProjectIndicator(Static):
    """Shows ``+<project>`` for the current project, or nothing."""

    def __init__(self, **kwargs: Any) -> None:
        self._cached_snapshot: _CurrentProjectSnapshot | None = None
        self._cached_token: tuple[object, ...] | None = None
        self._pending_resolve_token: tuple[object, ...] | None = None
        self._resolve_in_flight = False
        self._cached_failed = False
        super().__init__(Text(""), **kwargs)
        self.tooltip = None

    def on_mount(self) -> None:
        """Paint cached state, then resolve off-thread and poll."""

        self._apply_content()
        self._schedule_resolution_if_needed()
        self.set_interval(_POLL_INTERVAL_SECONDS, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Revalidate the peek token; never resolve on the timer tick."""

        if args or kwargs:
            return super().refresh(*args, **kwargs)

        if self._settings().indicator:
            peek_current_project_change_token()
            self._schedule_resolution_if_needed()
        self._apply_content()
        return super().refresh()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Pick up the resolved project once the background worker finishes."""

        worker = event.worker
        if worker.group != _WORKER_GROUP:
            return
        if event.state == WorkerState.SUCCESS:
            self._resolve_in_flight = False
            result = worker.result
            if isinstance(result, _CurrentProjectSnapshot):
                self._cached_snapshot = result
                self._cached_failed = False
                self._cached_token = self._pending_resolve_token
            else:
                self._cached_failed = True
            self._apply_content()
        elif event.state == WorkerState.ERROR:
            self._resolve_in_flight = False
            self._cached_failed = True
            self._apply_content()
        elif event.state == WorkerState.CANCELLED:
            self._resolve_in_flight = False

    async def on_click(self) -> None:
        """Open the ``+`` launch picker — the surface that moves the MRU."""

        await self.app.run_action("start_custom_agent")

    def _schedule_resolution_if_needed(self) -> None:
        """Launch the off-thread resolve worker when the token says to."""

        if self._resolve_in_flight or not self._settings().indicator:
            return

        token = peek_current_project_change_token()
        cold_start = self._cached_snapshot is None
        token_changed = token != self._cached_token
        if not (cold_start or self._cached_failed or token_changed):
            return

        self._resolve_in_flight = True
        self._pending_resolve_token = token
        self.run_worker(
            _resolve_snapshot,
            thread=True,
            exclusive=True,
            group=_WORKER_GROUP,
        )

    def _settings(self) -> CurrentProjectSettings:
        """Read the app's parsed ``ace.current_project`` block."""

        if not self.is_attached:
            return CurrentProjectSettings()
        settings = getattr(self.app, "_current_project_settings", None)
        if isinstance(settings, CurrentProjectSettings):
            return settings
        return CurrentProjectSettings()

    def _apply_content(self) -> None:
        """Update content and tooltip from the cached snapshot."""

        settings = self._settings()
        snapshot = self._cached_snapshot
        project = None if snapshot is None else snapshot.project
        accent = "" if snapshot is None else snapshot.accent
        plate = (
            project_chip_plate(accent, background=self._theme_background())
            if accent
            else ""
        )
        self.update(
            self._build_content(
                project, accent=accent, plate=plate, indicator=settings.indicator
            )
        )
        self.tooltip = self._build_tooltip(project, indicator=settings.indicator)

    def _theme_background(self) -> str:
        """Return the live app theme's background, or the pinned theme's."""

        if self.is_attached:
            theme = getattr(self.app, "current_theme", None)
            background = getattr(theme, "background", None)
            if isinstance(background, str) and background:
                return background
        return _fallback_theme_background()

    @staticmethod
    def _build_content(
        project: CurrentProject | None,
        *,
        accent: str,
        plate: str,
        indicator: bool,
    ) -> Text:
        """Build the chip, or empty text when hidden."""

        if not indicator or project is None:
            return Text("")
        text = Text()
        text.append(" ")
        text.append(_FRAME_LEFT, style=f"{accent} on {plate}")
        text.append("+", style=f"dim {accent} on {plate}")
        text.append(project.display_name, style=f"bold {accent} on {plate}")
        text.append(_FRAME_RIGHT, style=f"{accent} on {plate}")
        text.append(" ")
        return text

    @staticmethod
    def _build_tooltip(
        project: CurrentProject | None,
        *,
        indicator: bool,
    ) -> str | None:
        """Build the hover text, or ``None`` when the chip is hidden."""

        if not indicator or project is None:
            return None
        lines = [project.display_name]
        if project.origin == "patch":
            lines.append(f"via Patch {project.origin_ref}")
        if project.workflow_type:
            lines.append(f"#{project.workflow_type}:{project.origin_ref}")
        else:
            lines.append(project.origin_ref)
        lines.append(_LAUNCH_HINT)
        return "\n".join(lines)


__all__ = ["CurrentProjectIndicator"]
