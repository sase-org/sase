"""Deferred Artifacts provider discovery and coherent publication.

Bootstrap uses fixed panes only. The startup loads mixin schedules one
pump-free discovery pass after first paint; its completion is published as
one generation: new panes are mounted first, then the app snapshot, tab
strip, digit bindings, active pane, and help/catalog invalidation commit
synchronously with no await in between.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def _fresh_artifacts_discovery_blocking() -> tuple[Any, int, tuple[Any, ...], str]:
    """Run provider enumeration + token read off the event loop.

    Returns ``(token, epoch, descriptors, status_name)``. A ``None`` token
    marks a failed/retryable discovery; an empty descriptor provider set
    with a valid token is an authoritative completed zero-provider result.
    """

    from .._artifact_tab_descriptors import build_artifacts_strip, provider_descriptors
    from .._artifact_tab_discovery import (
        load_project_provider_records,
        provider_source_token,
    )
    from .._artifact_tab_snapshot import ArtifactsDiscoveryStatus
    from ..artifact_tabs import artifacts_tab_cache_epoch

    token = provider_source_token()
    loaded = load_project_provider_records(project=None)
    providers = provider_descriptors(loaded.records, loaded.issues)
    descriptors = build_artifacts_strip(providers)
    # Capture the epoch after the work so a reset during enumeration is
    # visible to the UI-thread stale check.
    epoch = artifacts_tab_cache_epoch()
    status = (
        ArtifactsDiscoveryStatus.FAILED
        if token is None
        else ArtifactsDiscoveryStatus.COMPLETED
    )
    return token, epoch, descriptors, status.value


class _ArtifactsPublicationError(RuntimeError):
    """Essential publication infrastructure is missing."""


class ArtifactsPublicationMixin:
    """Schedule deferred provider discovery and publish one generation."""

    _artifacts_pending_provider_target: str | None
    _artifacts_pending_provider_tab: Any
    _artifacts_discovery_teardown: bool
    _artifacts_last_discovery_error: str | None
    _artifacts_last_discovery_mono: float | None

    def _artifacts_source_result_is_stale(self: Any, epoch: int) -> bool:
        """Return whether *epoch* no longer matches the live cache epoch."""

        from ..artifact_tabs import artifacts_tab_cache_epoch

        return int(artifacts_tab_cache_epoch()) != int(epoch)

    def _current_artifacts_scope_display_name(self: Any) -> str | None:
        scope = getattr(self, "artifacts_project_scope", None)
        choices = getattr(self, "_artifacts_project_choices", None)
        if scope is None or choices is None:
            return None
        display_names = getattr(choices, "display_names", None)
        if not isinstance(display_names, dict):
            return None
        display_name = display_names.get(scope)
        return display_name if isinstance(display_name, str) else None

    def _schedule_artifacts_provider_discovery_if_source_changed(self: Any) -> bool:
        """Schedule discovery when the cached source token/epoch drifted.

        Periodic ticks revalidate the cached token; they do not enumerate
        providers. A ``None`` token keeps the last coherent generation and
        waits for explicit refresh to retry.
        """

        snapshot = getattr(self, "artifacts_descriptor_snapshot", None)
        if snapshot is None or bool(getattr(snapshot, "is_pending", False)):
            return False
        if getattr(self, "_artifacts_discovery_in_flight", False):
            return False
        from .._artifact_tab_discovery import provider_source_token
        from ..artifact_tabs import artifacts_tab_cache_epoch

        token = provider_source_token()
        if token is None:
            return False
        epoch = artifacts_tab_cache_epoch()
        if snapshot.source_token == token and int(snapshot.source_epoch) == int(epoch):
            return False
        return self._schedule_artifacts_provider_discovery(reason="source-changed")

    def _schedule_artifacts_provider_discovery(
        self: Any,
        *,
        reason: str = "startup",
    ) -> bool:
        """Coalesce to one in-flight discovery plus one pending refresh."""
        if getattr(self, "_artifacts_discovery_teardown", False):
            return False
        if getattr(self, "_artifacts_discovery_in_flight", False):
            self._artifacts_discovery_pending = True
            return False
        self._artifacts_discovery_in_flight = True
        self._artifacts_discovery_pending = False
        self._artifacts_discovery_seq = (
            int(getattr(self, "_artifacts_discovery_seq", 0)) + 1
        )
        try:
            from ..util.pump_tasks import spawn_pump_free_task
        except Exception:
            log.exception("Failed to import pump-free task helper")
            self._artifacts_discovery_in_flight = False
            return False
        task = spawn_pump_free_task(
            self,
            self._run_artifacts_provider_discovery(
                int(self._artifacts_discovery_seq),
                reason=reason,
            ),
            name="artifacts-provider-discovery",
            registry_attr="_pump_free_artifacts_discovery_tasks",
        )
        if task is None:
            self._artifacts_discovery_in_flight = False
            log.debug("artifacts discovery skipped without a running loop")
            return False
        return True

    async def _run_artifacts_provider_discovery(
        self: Any,
        seq: int,
        *,
        reason: str,
    ) -> None:
        """Discover providers off-pump, then publish one coherent generation."""
        started_mono = time.monotonic()
        try:
            token, epoch, descriptors, status_value = await asyncio.to_thread(
                _fresh_artifacts_discovery_blocking
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("Artifacts provider discovery failed: %s", error)
            self._artifacts_last_discovery_error = str(error)
            self._finish_artifacts_discovery_pass(seq, published=False)
            return
        if getattr(self, "_artifacts_discovery_teardown", False):
            self._finish_artifacts_discovery_pass(seq, published=False)
            return
        if int(getattr(self, "_artifacts_discovery_seq", seq)) != int(seq):
            self._finish_artifacts_discovery_pass(seq, published=False)
            return
        try:
            published = await self._prepare_and_commit_artifacts_snapshot(
                token,
                int(epoch),
                tuple(descriptors),
                str(status_value),
                reason=reason,
                started_mono=started_mono,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Artifacts publication failed; retaining generation")
            self._artifacts_last_discovery_error = "publication_failed"
            published = False
        self._finish_artifacts_discovery_pass(seq, published=published)

    def _finish_artifacts_discovery_pass(
        self: Any,
        seq: int,
        *,
        published: bool,
    ) -> None:
        """Release the in-flight guard and run a coalesced pending pass."""
        del published
        if int(getattr(self, "_artifacts_discovery_seq", seq)) != int(seq):
            return
        self._artifacts_discovery_in_flight = False
        if getattr(self, "_artifacts_discovery_teardown", False):
            self._artifacts_discovery_pending = False
            return
        if getattr(self, "_artifacts_discovery_pending", False):
            self._artifacts_discovery_pending = False
            try:
                self._schedule_artifacts_provider_discovery(reason="coalesced")
            except Exception:
                log.exception("Failed to schedule coalesced artifacts discovery")

    async def _prepare_and_commit_artifacts_snapshot(
        self: Any,
        token: Any,
        epoch: int,
        descriptors: tuple[Any, ...],
        status_value: str,
        *,
        reason: str,
        started_mono: float,
    ) -> bool:
        """Mount missing panes, await them, then commit one generation."""
        from .._artifact_tab_snapshot import (
            ArtifactsDiscoveryStatus,
            snapshot_from_descriptors,
        )

        try:
            status = ArtifactsDiscoveryStatus(status_value)
        except ValueError:
            status = ArtifactsDiscoveryStatus.COMPLETED
        # Reject failed generations that carry no usable token: retain the
        # last coherent generation and leave retry to the caller.
        if status is ArtifactsDiscoveryStatus.FAILED:
            self._artifacts_last_discovery_error = "provider_source_failed"
            self._artifacts_last_discovery_mono = time.monotonic()
            return False
        if self._artifacts_source_result_is_stale(epoch):
            self._artifacts_discovery_pending = True
            return False
        new_snapshot = snapshot_from_descriptors(
            tuple(descriptors),
            status=status,
            source_token=token,
            source_epoch=int(epoch),
        )
        current = getattr(self, "artifacts_descriptor_snapshot", None)
        if current is not None and tuple(current.descriptors) == tuple(
            new_snapshot.descriptors
        ):
            if self._artifacts_source_result_is_stale(epoch):
                self._artifacts_discovery_pending = True
                return False
            # Same panes: still adopt the completed status/token so pending
            # clears authoritatively without churning widgets or bindings.
            self._commit_artifacts_snapshot(
                new_snapshot,
                reason=reason,
                started_mono=started_mono,
                staged_widgets=(),
                removed_pane_ids=(),
                replaced_pane_ids=(),
            )
            return True

        staged_widgets: list[Any] = []
        removed_pane_ids: tuple[str, ...] = ()
        replaced_pane_ids: tuple[str, ...] = ()
        try:
            (
                staged_widgets,
                removed_pane_ids,
                replaced_pane_ids,
            ) = await self._stage_artifacts_panes(new_snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("Artifacts prepare failed; retaining generation")
            self._artifacts_last_discovery_error = str(error) or "prepare_failed"
            self._artifacts_last_discovery_mono = time.monotonic()
            try:
                await self._discard_staged_artifacts_panes(staged_widgets)
            except Exception:
                log.debug("Staged pane cleanup failed", exc_info=True)
            return False
        # Re-check lifetime, generation, source epoch, scope, and user
        # navigation after every await before committing.
        if getattr(self, "_artifacts_discovery_teardown", False):
            await self._discard_staged_artifacts_panes(staged_widgets)
            return False
        if self._artifacts_source_result_is_stale(epoch):
            self._artifacts_discovery_pending = True
            await self._discard_staged_artifacts_panes(staged_widgets)
            return False
        committed_snapshot = getattr(self, "artifacts_descriptor_snapshot", None)
        if committed_snapshot is not current:
            await self._discard_staged_artifacts_panes(staged_widgets)
            return False
        try:
            self._apply_current_scope_to_artifacts_widgets(staged_widgets)
            self._commit_artifacts_snapshot(
                new_snapshot,
                reason=reason,
                started_mono=started_mono,
                staged_widgets=tuple(staged_widgets),
                removed_pane_ids=tuple(removed_pane_ids),
                replaced_pane_ids=tuple(replaced_pane_ids),
            )
        except Exception:
            try:
                await self._discard_staged_artifacts_panes(staged_widgets)
            except Exception:
                log.debug("Staged pane cleanup failed", exc_info=True)
            raise
        return True

    async def _stage_artifacts_panes(
        self: Any, new_snapshot: Any
    ) -> tuple[list[Any], tuple[str, ...], tuple[str, ...]]:
        """Mount missing and replacement panes without advertising them."""
        from ..widgets.artifacts.view import ArtifactsView

        from ._artifacts_publication_diff import (
            diff_artifact_descriptors,
            mark_staged_replacement,
        )

        try:
            view = self.query_one("#artifacts-view", ArtifactsView)  # type: ignore[attr-defined]
        except Exception as error:
            raise _ArtifactsPublicationError("artifacts view missing") from error
        added, removed, replaced = diff_artifact_descriptors(
            view.descriptors, new_snapshot.descriptors
        )
        replaced_pane_ids = tuple(descriptor.pane_id for descriptor in replaced)
        staged: list[Any] = []
        if not added and not replaced:
            return staged, removed, replaced_pane_ids
        try:
            switcher = view.query_one("#artifacts-content-switcher")
        except Exception as error:
            raise _ArtifactsPublicationError("artifacts switcher missing") from error
        try:
            for descriptor in added:
                for widget in view._compose_pane(descriptor):
                    staged.append(widget)
            for descriptor in replaced:
                for widget in view._compose_pane(descriptor, assign_id=False):
                    mark_staged_replacement(widget, descriptor.pane_id)
                    staged.append(widget)
            if not staged:
                return [], removed, replaced_pane_ids
            self._propagate_presentation_to_staged_artifacts_panes(staged)
            for widget in staged:
                await switcher.mount(widget)
            try:
                view.set_keymap_registry(view._keymap_registry)  # type: ignore[attr-defined]
            except Exception:
                log.debug("Staged pane keymap refresh failed", exc_info=True)
            return staged, removed, replaced_pane_ids
        except BaseException:
            await self._discard_staged_artifacts_panes(staged)
            raise

    def _propagate_presentation_to_staged_artifacts_panes(
        self: Any, staged: list[Any]
    ) -> None:
        """Copy keymap and current scope onto panes that are about to mount."""

        try:
            registry = getattr(self, "_keymap_registry", None)
            if registry is not None:
                for widget in staged:
                    setter = getattr(widget, "set_keymap_registry", None)
                    if callable(setter):
                        setter(registry)
        except Exception:
            log.debug("Staged pane keymap propagation failed", exc_info=True)
        self._apply_current_scope_to_artifacts_widgets(staged)

    def _apply_current_scope_to_artifacts_widgets(
        self: Any, widgets: list[Any] | tuple[Any, ...]
    ) -> None:
        """Re-read live project scope/display and apply it to *widgets*."""

        scope = getattr(self, "artifacts_project_scope", None)
        display_name = self._current_artifacts_scope_display_name()
        for widget in widgets:
            setter = getattr(widget, "set_project_scope", None)
            if not callable(setter):
                continue
            try:
                setter(scope, display_name=display_name)
            except TypeError:
                try:
                    setter(scope)
                except Exception:
                    pass
            except Exception:
                log.debug("Staged pane scope propagation failed", exc_info=True)

    async def _discard_staged_artifacts_panes(self: Any, staged: Any) -> None:
        """Remove staged widgets that will never be advertised."""
        for widget in tuple(staged or ()):
            try:
                await widget.remove()
            except Exception:
                pass

    def _commit_artifacts_snapshot(
        self: Any,
        new_snapshot: Any,
        *,
        reason: str,
        started_mono: float,
        staged_widgets: tuple[Any, ...] = (),
        removed_pane_ids: tuple[str, ...] = (),
        replaced_pane_ids: tuple[str, ...] = (),
    ) -> None:
        """Synchronously replace the committed generation; no await inside."""
        from textual.binding import BindingsMap

        from ..keymaps.bindings import build_app_bindings
        from ._artifacts_publication_diff import (
            is_staged_replacement_widget,
            promote_staged_replacement,
        )

        new_bindings = BindingsMap(
            build_app_bindings(
                self._keymap_registry.app,  # type: ignore[attr-defined]
                snapshot=new_snapshot,
            )
        )

        view = None
        try:
            from ..widgets.artifacts.view import ArtifactsView

            view = self.query_one("#artifacts-view", ArtifactsView)  # type: ignore[attr-defined]
        except Exception:
            view = None
        old_current = str(getattr(self, "current_artifacts_subtab", "stitches"))
        old_tab = getattr(self, "current_tab", None)
        old_widget: Any = None
        if view is not None:
            try:
                old_widget = view._pane(old_current)  # type: ignore[attr-defined]
            except Exception:
                old_widget = None

        # Promote staged replacements onto published pane ids before any
        # lookup that keys on those ids. Remove the outgoing widget first
        # so the DOM never holds duplicate ids. Missing view/switcher or a
        # failed id promotion is an essential commit failure.
        if staged_widgets or replaced_pane_ids:
            if view is None:
                raise _ArtifactsPublicationError("artifacts view missing")
            try:
                switcher = view.query_one("#artifacts-content-switcher")
            except Exception as error:
                raise _ArtifactsPublicationError(
                    "artifacts switcher missing"
                ) from error
            replaced = set(replaced_pane_ids)
            if replaced:
                doomed = [
                    child
                    for child in list(switcher.children)
                    if getattr(child, "id", None) in replaced
                ]
                for widget in doomed:
                    widget.remove()
            for widget in staged_widgets:
                if is_staged_replacement_widget(widget):
                    promote_staged_replacement(widget)

        # App snapshot first so view helpers that read the app see the new
        # generation during the same commit.
        self._artifacts_descriptor_snapshot = new_snapshot
        self._artifacts_last_discovery_error = None
        self._artifacts_last_discovery_mono = time.monotonic()
        self._bindings = new_bindings  # type: ignore[attr-defined]

        if view is not None:
            view._snapshot = new_snapshot
            view._descriptors = new_snapshot.descriptors
            view._descriptor_by_id = {
                descriptor.id: descriptor for descriptor in new_snapshot.descriptors
            }
            try:
                strip = view.query_one("#artifacts-subtabs")
                strip.set_tabs(view._panel_tabs(), active_tab=None)
            except Exception:
                log.debug("Artifacts tab strip commit failed", exc_info=True)
            # Preserve selection by stable pane ID; removed panes fall back
            # to the existing fixed default with correct lifecycle hooks.
            new_current = new_snapshot.normalize(old_current)
            artifacts_visible = old_tab == "artifacts"
            new_widget: Any = None
            try:
                new_widget = view._pane(new_current)  # type: ignore[attr-defined]
            except Exception:
                new_widget = None
            view._current_subtab = new_current  # type: ignore[attr-defined]
            try:
                switcher = view.query_one("#artifacts-content-switcher")
                switcher.current = view._pane_id(new_current)  # type: ignore[attr-defined]
            except Exception:
                log.debug("Artifacts switcher commit failed", exc_info=True)
            try:
                strip = view.query_one("#artifacts-subtabs")
                strip.set_active_tab(new_current)
            except Exception:
                pass
            try:
                view._refresh_split_badge()
                view._refresh_pane_brief()
                view._refresh_provider_diagnostics()
                view.set_discovery_pending(False)
            except Exception:
                log.debug("Artifacts header commit failed", exc_info=True)
            if (
                artifacts_visible
                and old_widget is not None
                and old_widget is not new_widget
            ):
                try:
                    old_widget.deactivate()
                except Exception:
                    pass
            if (
                artifacts_visible
                and new_widget is not None
                and old_widget is not new_widget
            ):
                try:
                    new_widget.activate()
                except Exception:
                    pass
            # Sync the app reactive through the normal watcher path so the
            # footer, link rail, and help follow the committed generation.
            # The view already shows new_current, so the watcher's own
            # switch is a no-op; its side effects are what matter.
            try:
                self.current_artifacts_subtab = new_current  # type: ignore[attr-defined]
            except Exception:
                log.debug("Artifacts subtab sync failed", exc_info=True)

        # Apply a retained explicit provider target only when no later user
        # navigation superseded it and the completed generation has it.
        # A missing ID after completion gets an unavailable response.
        # Any later in-Artifacts navigation or scope change already cleared
        # the target; a tab switch away drops it silently here instead of
        # yanking the user back.
        try:
            pending_target = getattr(self, "_artifacts_pending_provider_target", None)
            pending_tab = getattr(self, "_artifacts_pending_provider_tab", None)
            if isinstance(pending_target, str) and pending_target:
                self._artifacts_pending_provider_target = None
                self._artifacts_pending_provider_tab = None
                if old_tab == "artifacts" and pending_tab == "artifacts":
                    if new_snapshot.lookup(pending_target) is not None:
                        self._switch_artifacts_subtab(pending_target)  # type: ignore[attr-defined]
                    else:
                        notify = getattr(self, "notify", None)
                        if callable(notify):
                            label = new_snapshot.label(pending_target)
                            notify(
                                f"Artifacts pane {label} is unavailable",
                                severity="warning",
                            )
        except Exception:
            log.debug("Pending provider target apply failed", exc_info=True)

        # Remove obsolete widgets only after they are no longer reachable.
        # Pane DOM ids can carry provider characters (e.g. "ref:plan"),
        # which are not safe query selectors, so match mounted children by
        # their widget id instead of building a selector.
        if view is not None and removed_pane_ids:
            try:
                switcher = view.query_one("#artifacts-content-switcher")
                doomed = [
                    child
                    for child in list(switcher.children)
                    if getattr(child, "id", None) in set(removed_pane_ids)
                ]
            except Exception:
                doomed = []
            for widget in doomed:
                try:
                    widget.remove()
                except Exception:
                    pass

        # Refresh already-open help/palette, preserving filter and selection.
        try:
            self._invalidate_artifacts_help_catalog()  # type: ignore[attr-defined]
        except Exception:
            log.debug("Help/catalog invalidation failed", exc_info=True)

        try:
            from ..util.trace import trace_event
        except Exception:
            trace_event = None  # type: ignore[assignment]
        if callable(trace_event):
            try:
                trace_event(
                    "artifacts.provider_publication",
                    generation=int(getattr(new_snapshot, "generation", 0)),
                    panes=len(tuple(getattr(new_snapshot, "descriptors", ()))),
                    reason=str(reason),
                    elapsed_ms=int((time.monotonic() - started_mono) * 1000),
                )
            except Exception:
                pass

    def _invalidate_artifacts_help_catalog(self: Any) -> None:
        """Refresh open help/palette against the committed generation."""
        try:
            stack = list(getattr(self, "screen_stack", []) or [])
        except Exception:
            return
        for screen in stack:
            name = type(screen).__name__
            if name == "HelpModal":
                try:
                    screen._filter_result = None  # type: ignore[attr-defined]
                    screen._render_keymaps_content()  # type: ignore[attr-defined]
                except Exception:
                    pass
            if name == "CommandPaletteModal":
                try:
                    self._refresh_open_command_palette(screen)  # type: ignore[attr-defined]
                except Exception:
                    pass

    def _refresh_open_command_palette(self: Any, screen: Any) -> None:
        """Rebuild an open palette catalog, preserving filter/selection."""
        from ..commands import build_command_catalog, extract_command_context
        from ..commands import is_command_available

        try:
            query = screen._filter_text()  # type: ignore[attr-defined]
        except Exception:
            query = ""
        highlighted: str | None = None
        try:
            from textual.widgets import OptionList

            option_list = screen.query_one("#command-palette-list", OptionList)
            idx = option_list.highlighted
            if idx is not None and 0 <= idx < len(screen._filtered_specs):  # type: ignore[attr-defined]
                highlighted = screen._filtered_specs[idx].id  # type: ignore[attr-defined]
        except Exception:
            highlighted = None
        try:
            ctx = extract_command_context(self)  # type: ignore[arg-type]
            catalog = build_command_catalog(
                self._keymap_registry,  # type: ignore[attr-defined]
                snapshot=getattr(self, "artifacts_descriptor_snapshot", None),
            )
            applicable = [s for s in catalog if is_command_available(s, ctx)]
            screen._all_specs = list(applicable)  # type: ignore[attr-defined]
            screen._apply_filter(query)  # type: ignore[attr-defined]
            if highlighted is not None:
                try:
                    from textual.widgets import OptionList

                    option_list = screen.query_one("#command-palette-list", OptionList)
                    for index, spec in enumerate(screen._filtered_specs):  # type: ignore[attr-defined]
                        if spec.id == highlighted:
                            option_list.highlighted = index
                            break
                except Exception:
                    pass
            screen._refresh_status()  # type: ignore[attr-defined]
        except Exception:
            log.debug("Palette refresh failed", exc_info=True)

    def action_retry_artifacts_discovery(self: Any) -> None:
        """Retry a failed provider discovery without churning the UI."""
        self._artifacts_discovery_pending = False
        self._schedule_artifacts_provider_discovery(reason="retry")


__all__ = ["ArtifactsPublicationMixin"]
