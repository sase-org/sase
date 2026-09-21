"""One app-scoped source for launch-context state (epic sase-14y, phase 1).

The launch default (model/effort) and the current project are global: launches
(the ``+`` picker, leader keys) work from every tab. The status-row cluster
added in phase 2 therefore needs one instance of this state per tab, and
Textual cannot share one widget instance across three parents. Mounting three
independent copies of the old self-polling indicators would triple the resolve
workers and let hidden copies disagree, and reparenting on tab switch would
repaint placeholders on every switch.

So this module owns the polling/resolution that used to live inside
:class:`LLMOverrideIndicator` and :class:`CurrentProjectIndicator`. It is a
non-rendering :class:`Widget` (``display: none``) mounted exactly once by
``AppLayoutMixin._compose_layout``. The two indicator widgets are render-only
views: they paint from :attr:`LaunchContextSource.state` on mount and re-render
whenever the source broadcasts via :meth:`apply_launch_context`.

The periodic tick stays peek-only (a time-gated config token plus ``os.stat``)
exactly as before; real resolves stay on worker threads, never the UI thread,
timers, or render paths. Do not "optimize" the tick back into a locking read
on the theory that fewer, heavier calls beat more, cheaper ones -- see
``launch_default_peek.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.widget import Widget
from textual.worker import Worker, WorkerState

from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.provider_styles import ProviderTextPalette, provider_text_palette
from sase.current_project import (
    CurrentProject,
    peek_current_project_change_token,
    resolve_current_project,
)
from sase.llm_provider.config import resolve_effective_effort
from sase.llm_provider.launch_default_peek import peek_launch_default_change_token
from sase.llm_provider.model_directive_label import format_model_directive_label
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    build_launch_model_setting_snapshot,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.llm_provider.temporary_override_peek import peek_active_temporary_override
from sase.xprompt.directives import PromptDirectives
from sase.xprompt.loader import get_known_project_workspaces

# Same cadence the two indicator widgets used to poll on independently. Still
# affordable only because the tick is pure peek (time-gated ``os.stat`` +
# config tokens), not a resolve.
_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_WORKER_GROUP = "llm-indicator-default"
_PROJECT_WORKER_GROUP = "current-project-indicator"


@dataclass(frozen=True, slots=True)
class LaunchDefaultSnapshot:
    """Resolved launch default plus rotation context for the tooltip."""

    provider: str
    model: str
    referenced_alias: str | None
    selector_mode: str | None
    member_count: int
    effort: str | None = None
    directive_label: str | None = None
    palette: ProviderTextPalette | None = None


@dataclass(frozen=True, slots=True)
class CurrentProjectSnapshot:
    """Resolved current project plus the accent computed off-thread."""

    project: CurrentProject | None
    accent: str


@dataclass(frozen=True, slots=True)
class LaunchContextState:
    """Immutable launch-context state broadcast to the indicator views.

    A ``None`` snapshot with a false ``*_failed`` flag means "still
    resolving" (views paint their placeholder/empty content); a true flag
    means the last resolve failed (views paint their fallback). ``override``
    is the peeked active ``default``-lane override itself -- a
    ``now``-independent value, since views compute the remaining countdown at
    render time from its absolute ``expires_at``.
    """

    default_snapshot: LaunchDefaultSnapshot | None = None
    default_failed: bool = False
    default_token: tuple[object, ...] | None = None
    project_snapshot: CurrentProjectSnapshot | None = None
    project_failed: bool = False
    project_token: tuple[object, ...] | None = None
    override: TemporaryLLMOverride | None = None


def _resolve_default_snapshot() -> LaunchDefaultSnapshot | None:
    """Resolve the launch default off the UI thread.

    ``consume=False`` keeps this display-only resolve from advancing a
    load-balanced pool's rotation cursor; the consuming launch path is the
    only writer.
    """

    try:
        snapshot = build_launch_model_setting_snapshot(
            DEFAULT_MODEL_FIELD, consume=False
        )
    except Exception:  # noqa: BLE001 - display reads always degrade.
        return None
    level, _explicit = resolve_effective_effort(
        PromptDirectives(),
        snapshot.effort,
    )
    return LaunchDefaultSnapshot(
        provider=snapshot.provider,
        model=snapshot.model,
        referenced_alias=snapshot.referenced_alias,
        selector_mode=snapshot.selector_mode,
        member_count=len(snapshot.selector_members),
        effort=level,
        directive_label=format_model_directive_label(snapshot.provider, snapshot.model),
        # Resolved here, not at render time: the first palette lookup walks
        # plugin metadata, which must never land on the UI thread.
        palette=provider_text_palette(snapshot.provider),
    )


def _enabled_project_keys() -> tuple[str, ...]:
    """Return enabled project keys for accent assignment.

    Disk-backed; call only from the off-thread resolve worker.
    """

    return tuple(get_known_project_workspaces())


def _resolve_project_snapshot() -> CurrentProjectSnapshot | None:
    """Resolve the current project and its accent off the UI thread."""

    try:
        project = resolve_current_project()
        enabled_keys = _enabled_project_keys()
        accent = ""
        if project is not None:
            accent = project_accent(project.project_key, among=enabled_keys)
    except Exception:  # noqa: BLE001 - display reads always degrade.
        return None
    return CurrentProjectSnapshot(project=project, accent=accent)


class LaunchContextSource(Widget):
    """App-scoped, non-rendering source for launch-context state.

    Mounted exactly once (id ``launch-context-source``). Owns the 5s
    peek-only tick and both resolve worker groups; every state change -- and
    every tick, so override countdowns advance -- is broadcast to all mounted
    :class:`LLMOverrideIndicator` / :class:`CurrentProjectIndicator` views via
    their ``apply_launch_context`` method.
    """

    DEFAULT_CSS = """
    LaunchContextSource {
        display: none;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        self._state = LaunchContextState()
        self._default_in_flight = False
        self._project_in_flight = False
        self._pending_default_token: tuple[object, ...] | None = None
        self._pending_project_token: tuple[object, ...] | None = None
        self._override_active_last_tick = False
        super().__init__(**kwargs)

    @property
    def state(self) -> LaunchContextState:
        """Return the current immutable launch-context state."""

        return self._state

    def on_mount(self) -> None:
        """Paint (broadcast) initial state, resolve off-thread, then poll."""

        self._tick()
        self._override_active_last_tick = peek_active_temporary_override() is not None
        self.set_interval(_POLL_INTERVAL_SECONDS, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Revalidate peek tokens and rebroadcast; never resolve on the tick."""

        if args or kwargs:
            return super().refresh(*args, **kwargs)

        self._tick()
        return super().refresh()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Commit a finished resolve to the state and broadcast it."""

        worker = event.worker
        if worker.group == _DEFAULT_WORKER_GROUP:
            self._apply_default_result(worker, event.state)
        elif worker.group == _PROJECT_WORKER_GROUP:
            self._apply_project_result(worker, event.state)

    def invalidate_launch_default(self) -> None:
        """Drop the cached launch default after provider routing changes."""

        self._state = LaunchContextState(
            default_snapshot=None,
            default_failed=False,
            default_token=None,
            project_snapshot=self._state.project_snapshot,
            project_failed=self._state.project_failed,
            project_token=self._state.project_token,
            override=self._state.override,
        )
        self._schedule_default_resolution()
        self._broadcast()

    def invalidate_current_project(self) -> None:
        """Force an off-thread project resolve, ignoring the peek-token floor.

        ``refresh()`` can miss a just-written MRU because
        :func:`peek_current_project_change_token` serves a 0.5s cached stat.
        Clearing the cached token makes the next schedule unconditional. A
        no-op while a resolve is already in flight.
        """

        if self._project_in_flight:
            return
        self._state = LaunchContextState(
            default_snapshot=self._state.default_snapshot,
            default_failed=self._state.default_failed,
            default_token=self._state.default_token,
            project_snapshot=self._state.project_snapshot,
            project_failed=self._state.project_failed,
            project_token=None,
            override=self._state.override,
        )
        self._schedule_project_resolution_if_needed()
        self._broadcast()

    def _tick(self) -> None:
        """Peek both lanes, schedule resolves as needed, then broadcast."""

        override = peek_active_temporary_override()
        override_active = override is not None
        override_lapsed = self._override_active_last_tick and not override_active
        self._override_active_last_tick = override_active

        if not override_active:
            cold_start = (
                self._state.default_snapshot is None and not self._default_in_flight
            )
            token_changed = (
                peek_launch_default_change_token() != self._state.default_token
            )
            if (
                cold_start
                or self._state.default_failed
                or token_changed
                or override_lapsed
            ):
                self._schedule_default_resolution()

        if self._project_settings().indicator:
            peek_current_project_change_token()
            self._schedule_project_resolution_if_needed()

        if override != self._state.override:
            self._state = LaunchContextState(
                default_snapshot=self._state.default_snapshot,
                default_failed=self._state.default_failed,
                default_token=self._state.default_token,
                project_snapshot=self._state.project_snapshot,
                project_failed=self._state.project_failed,
                project_token=self._state.project_token,
                override=override,
            )
        self._broadcast()

    def _schedule_default_resolution(self) -> None:
        """Launch the off-thread default-resolution worker, if appropriate."""

        if peek_active_temporary_override() is not None:
            return

        self._default_in_flight = True
        self._pending_default_token = peek_launch_default_change_token()
        self.run_worker(
            _resolve_default_snapshot,
            thread=True,
            exclusive=True,
            group=_DEFAULT_WORKER_GROUP,
        )

    def _schedule_project_resolution_if_needed(self) -> None:
        """Launch the off-thread project-resolve worker when the token says to."""

        if self._project_in_flight or not self._project_settings().indicator:
            return

        token = peek_current_project_change_token()
        cold_start = self._state.project_snapshot is None
        token_changed = token != self._state.project_token
        if not (cold_start or self._state.project_failed or token_changed):
            return

        self._project_in_flight = True
        self._pending_project_token = token
        self.run_worker(
            _resolve_project_snapshot,
            thread=True,
            exclusive=True,
            group=_PROJECT_WORKER_GROUP,
        )

    def _apply_default_result(self, worker: Worker, result_state: WorkerState) -> None:
        """Commit a finished default resolve and broadcast."""

        if result_state == WorkerState.CANCELLED:
            self._default_in_flight = False
            return
        self._default_in_flight = False
        result = worker.result
        if result_state == WorkerState.SUCCESS and isinstance(
            result, LaunchDefaultSnapshot
        ):
            self._state = LaunchContextState(
                default_snapshot=result,
                default_failed=False,
                default_token=self._pending_default_token,
                project_snapshot=self._state.project_snapshot,
                project_failed=self._state.project_failed,
                project_token=self._state.project_token,
                override=self._state.override,
            )
        elif result_state != WorkerState.CANCELLED:
            self._state = LaunchContextState(
                default_snapshot=self._state.default_snapshot,
                default_failed=True,
                default_token=self._state.default_token,
                project_snapshot=self._state.project_snapshot,
                project_failed=self._state.project_failed,
                project_token=self._state.project_token,
                override=self._state.override,
            )
        self._broadcast()

    def _apply_project_result(self, worker: Worker, result_state: WorkerState) -> None:
        """Commit a finished project resolve and broadcast."""

        if result_state == WorkerState.CANCELLED:
            self._project_in_flight = False
            return
        self._project_in_flight = False
        result = worker.result
        if result_state == WorkerState.SUCCESS and isinstance(
            result, CurrentProjectSnapshot
        ):
            self._state = LaunchContextState(
                default_snapshot=self._state.default_snapshot,
                default_failed=self._state.default_failed,
                default_token=self._state.default_token,
                project_snapshot=result,
                project_failed=False,
                project_token=self._pending_project_token,
                override=self._state.override,
            )
        elif result_state != WorkerState.CANCELLED:
            self._state = LaunchContextState(
                default_snapshot=self._state.default_snapshot,
                default_failed=self._state.default_failed,
                default_token=self._state.default_token,
                project_snapshot=self._state.project_snapshot,
                project_failed=True,
                project_token=self._state.project_token,
                override=self._state.override,
            )
        self._broadcast()

    def _project_settings(self) -> CurrentProjectSettings:
        """Read the app's parsed ``ace.current_project`` block."""

        try:
            app = self.app
        except Exception:  # noqa: BLE001 - unmounted source degrades.
            return CurrentProjectSettings()
        settings = getattr(app, "_current_project_settings", None)
        if isinstance(settings, CurrentProjectSettings):
            return settings
        return CurrentProjectSettings()

    def _broadcast(self) -> None:
        """Push the current state to every mounted indicator view."""

        try:
            app = self.app
        except Exception:  # noqa: BLE001 - unmounted source has no views.
            return
        from .current_project_indicator import CurrentProjectIndicator
        from .llm_override_indicator import LLMOverrideIndicator

        try:
            views = [
                *app.query(LLMOverrideIndicator),
                *app.query(CurrentProjectIndicator),
            ]
        except Exception:  # noqa: BLE001 - display state always degrades.
            return
        for view in views:
            view.apply_launch_context(self._state)


__all__ = [
    "CurrentProjectSnapshot",
    "LaunchContextSource",
    "LaunchContextState",
    "LaunchDefaultSnapshot",
]
