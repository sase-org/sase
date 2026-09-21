"""Current-project chip for the status-row launch-context cluster.

Renders ``+<display_name>`` in the project's accent color after the
``current`` label. Empty (zero width) when no project resolves or when
``ace.current_project.indicator`` is false; the hosting
:class:`LaunchContextBar` then collapses the whole project group.

A render-only view over :class:`LaunchContextSource`: the periodic tick (a
cheap change-token peek) and the real
:func:`sase.current_project.resolve_current_project` call -- plus the enabled
project key set used for accent assignment -- live in the app-scoped source,
which pushes fresh state here via :meth:`apply_launch_context`. The chip
renders without edge pads: the bar labels supply the spacing.

Clicking opens the ``+`` launch picker. The current project is derived
from the VCS xprompt MRU store: launching an agent, ``sase project
set-current``, or the Projects tab set-current key all promote that head.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.current_project import CurrentProject

from .launch_context_source import (
    LaunchContextSource,
    LaunchContextState,
    CurrentProjectSnapshot,
)


class CurrentProjectIndicator(Static):
    """Shows ``+<project>`` for the current project, or nothing.

    The cached fields below are the view's render inputs -- the source copies
    its state into them on broadcast, and ``refresh()`` re-pulls them -- so
    content and tooltip builders stay pure functions of already-resolved
    values.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._cached_snapshot: CurrentProjectSnapshot | None = None
        self._cached_token: tuple[object, ...] | None = None
        self._cached_failed = False
        super().__init__(Text(""), **kwargs)
        self.tooltip = None

    def on_mount(self) -> None:
        """Paint the source's current state (instantly resolved, no placeholder)."""

        state = self._source_state()
        if state is not None:
            self.apply_launch_context(state)
        else:
            self._apply_content()

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Re-render from the source state, preserving Widget.refresh kwargs."""

        if args or kwargs:
            return super().refresh(*args, **kwargs)

        state = self._source_state()
        if state is not None:
            self.apply_launch_context(state)
        else:
            self._apply_content()
        return super().refresh()

    def apply_launch_context(self, state: LaunchContextState) -> None:
        """Copy broadcast source state into the render inputs and repaint."""

        self._cached_snapshot = state.project_snapshot
        self._cached_token = state.project_token
        self._cached_failed = state.project_failed
        self._apply_content()

    async def on_click(self) -> None:
        """Open the ``+`` launch picker — the surface that moves the MRU."""

        await self.app.run_action("start_custom_agent")

    def _source_state(self) -> LaunchContextState | None:
        """Return the app-scoped source state, or ``None`` when unmounted."""

        if not self.is_attached:
            return None
        try:
            source = self.app.query_one("#launch-context-source", LaunchContextSource)
        except Exception:  # noqa: BLE001 - unmounted views degrade to cache.
            return None
        return source.state

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
        self.update(
            self._build_content(project, accent=accent, indicator=settings.indicator)
        )
        self.tooltip = self._build_tooltip(project, indicator=settings.indicator)

    @staticmethod
    def _build_content(
        project: CurrentProject | None,
        *,
        accent: str,
        indicator: bool,
    ) -> Text:
        """Build the chip, or empty text when hidden."""

        if not indicator or project is None:
            return Text("")
        text = Text()
        text.append("+", style=f"dim {accent}")
        text.append(project.display_name, style=f"bold {accent}")
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
        lines = [f"Current project: {project.display_name}"]
        lines.append(
            "Your working project: it seeds project filters and is "
            "preselected in the + launch picker."
        )
        if project.origin == "patch":
            lines.append(f"Set via Patch {project.origin_ref}")
        elif project.workflow_type:
            lines.append(
                f"Set by your last launch (#{project.workflow_type}:{project.origin_ref})"
            )
        else:
            lines.append(f"Set by your last launch ({project.origin_ref})")
        lines.append(
            "Click to launch an agent on a project · "
            "press c on the Projects tab to switch."
        )
        return "\n".join(lines)


__all__ = ["CurrentProjectIndicator"]
