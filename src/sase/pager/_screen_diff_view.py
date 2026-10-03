"""Diff view state, toggle, and rendering for ``PagerScreen``.

Owns the ``=`` view toggle, the read/diff view application, the
background diff fetch with generation guards, and the ``yy``
unified-diff branch for ``PagerScreen`` history sections. Change
navigation lives in ``_screen_diff_navigate``; fold expansion lives in
``_screen_diff_folds``; this module never imports those siblings.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._body_layout import BodyLayout
from sase.pager._labels import PagerLabelLayer
from sase.pager.document import PagerSection
from sase.pager.history.diff import (
    build_diff_body,
    diff_endpoints,
    unified_diff_for_comparison,
)
from sase.pager.history.models import HistoryView

HISTORY_TASK_ATTR = "_pump_free_history_tasks"

_HISTORY_CACHE_LIMIT = 50

__all__ = ["HISTORY_TASK_ATTR", "PagerDiffViewMixin"]


class PagerDiffViewMixin:
    """Own the history diff view for one screen."""

    document: Any
    _body: BodyLayout | None
    _label_layer: PagerLabelLayer | None
    _history_states: dict[str, Any]
    _history_generation: int
    _history_supported: dict[str, bool]
    _history_view_sticky: HistoryView | None

    def _init_diff_state(self: Any) -> None:
        self._history_view_sticky = None

    def _effective_view(self: Any, section: PagerSection, state: Any) -> HistoryView:
        if self._history_view_sticky is not None:
            return self._history_view_sticky
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        if getattr(pin, "view", "read") == "diff":
            return "diff"
        return "read"

    def _current_ordinal(self: Any, section: PagerSection, state: Any) -> int:
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        return int(getattr(pin, "ordinal", 0) or 0)

    def _diff_endpoints_for(
        self: Any, section: PagerSection, state: Any
    ) -> tuple[int, int] | None:
        # The moment is the only source for diff endpoints: it skips hidden
        # versions and honours D3. The old function survives only for the
        # fail-open path where no moment can be built.
        try:
            from sase.pager.history.moment import (
                diff_endpoints as moment_endpoints,
            )
            from sase.pager.history.moment import moment_for_state

            moment = moment_for_state(state) if state is not None else None
        except Exception:
            moment = None
            moment_endpoints = None  # type: ignore[assignment]
        pin = state.current_pin if state is not None else None
        if pin is None:
            pin = section.version_pin
        if moment is not None:
            diff = getattr(moment, "diff", None)
            if getattr(moment, "view", "read") == "diff" and diff is not None:
                try:
                    return (int(diff[0]), int(diff[1]))
                except (TypeError, ValueError, IndexError):
                    pass
            # Sticky diffs and read-view callers share the moment's
            # hidden-skipping semantics even before the pin flips to diff.
            try:
                ordinal = int(getattr(pin, "ordinal", 0) or 0)
                raw_base = getattr(pin, "compare_base", None)
                try:
                    base_override = int(raw_base) if raw_base is not None else None
                except (TypeError, ValueError):
                    base_override = None
                explicit = bool(getattr(pin, "explicit_base", False))
                visible = tuple(state.visible_ordinals) if state is not None else ()
                navigable = [
                    int(v or 0)
                    for v in visible
                    if int(v or 0) > 0
                    and not (
                        bool(getattr(moment, "now_matches_newest", False))
                        and int(v or 0) == int(getattr(moment, "newest", 0) or 0)
                    )
                ]
                newest = int(getattr(moment, "newest", 0) or 0)
                # A pin to newest on a now ≡ vN subject diffs now itself.
                target = ordinal
                try:
                    from sase.pager.history.moment import canonical_ordinal

                    if canonical_ordinal(ordinal, moment) == 0 and ordinal != 0:
                        target = 0
                except Exception:
                    pass
                if moment_endpoints is not None:
                    endpoints = moment_endpoints(
                        target=target,
                        steppable=navigable,
                        newest=newest,
                        dirty=bool(getattr(moment, "worktree_dirty", False)),
                        explicit_base=base_override if explicit else None,
                    )
                    if endpoints is not None:
                        return endpoints
            except Exception:
                pass
            if getattr(moment, "view", "read") == "diff":
                return None
        ordinal = int(getattr(pin, "ordinal", 0) or 0)
        compare_base = getattr(pin, "compare_base", None)
        try:
            base_override = int(compare_base) if compare_base is not None else None
        except (TypeError, ValueError):
            base_override = None
        return diff_endpoints(
            ordinal=ordinal,
            visible_ordinals=tuple(state.visible_ordinals) if state is not None else (),
            dirty=bool(state is not None and state.status == "dirty-now"),
            compare_base=base_override,
            explicit_base=bool(getattr(pin, "explicit_base", False)),
        )

    def action_history_toggle_diff(self: Any) -> None:
        """Switch the current section between the read and diff views."""
        try:
            section = self._current_section()
        except Exception:
            return
        identity = section.identity
        state = self._history_states.get(identity)
        if state is None:
            if self._history_supported.get(identity) is False:
                self.notify("No history for this section.", severity="information")
                return
            # Discovery in flight: queue the toggle like version steps do.
            self._history_pending[identity] = "toggle-diff"
            self._start_history_discovery_after_paint()
            return
        self._toggle_diff_for_state(identity)

    def _toggle_diff_for_state(self: Any, identity: str) -> None:
        """Flip the diff view once history state for *identity* exists."""
        state = self._history_states.get(identity)
        if state is None:
            return
        try:
            section = next(s for s in self.document.sections if s.identity == identity)
        except StopIteration:
            return
        if not state.visible_ordinals:
            self.notify("No committed versions.", severity="information")
            return
        current = self._effective_view(section, state)
        switch: HistoryView = "read" if current == "diff" else "diff"
        # An explicit `=` sticks for the rest of the pager session.
        self._history_view_sticky = switch
        if switch == "read":
            self._apply_read_view(identity)
        else:
            self._ensure_diff_view(identity)

    def _apply_read_view(self: Any, identity: str) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        ordinal = self._history_current_pin_ordinal_for_identity(identity)
        read_section: PagerSection | None = None
        if ordinal == 0:
            live = getattr(state, "live_section", None)
            if isinstance(live, PagerSection):
                read_section = live
        else:
            cached = state.body_cache.get((ordinal, state.subject_id))
            if isinstance(cached, PagerSection):
                read_section = cached
        if read_section is None:
            task = spawn_pump_free_task(
                self,
                self._load_and_swap_version(
                    identity, ordinal, self.document, self._history_generation
                ),
                name="sase-pager-history-step",
                registry_attr=HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            return
        self._swap_active_section(read_section, ordinal, self._history_generation)

    def _ensure_diff_view(self: Any, identity: str) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        try:
            section = next(s for s in self.document.sections if s.identity == identity)
        except StopIteration:
            return
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            self.notify("No committed versions.", severity="information")
            return
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            comparison = None
        read_section = self._diff_read_section(identity, state, target)
        if comparison is not None and read_section is not None:
            self._apply_diff_view(identity, base, target, comparison)
            return
        self._set_footer_status("loading diff")
        task = spawn_pump_free_task(
            self,
            self._fetch_and_apply_diff(
                identity, base, target, self.document, self._history_generation
            ),
            name="sase-pager-history-diff",
            registry_attr=HISTORY_TASK_ATTR,
        )
        if task is None:
            self._set_footer_status(None)
            self.notify("History worker unavailable.", severity="warning")

    async def _fetch_and_apply_diff(
        self: Any,
        identity: str,
        base: int,
        target: int,
        document: Any,
        generation: int,
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return

        def _fetch() -> tuple[dict[str, Any] | None, Any | None]:
            try:
                section = next(s for s in document.sections if s.identity == identity)
            except StopIteration:
                return (None, None)
            try:
                from sase.pager.history.provider import history_provider_for_section
            except Exception:
                return (None, None)
            try:
                provider = history_provider_for_section(section)
            except Exception:
                return (None, None)
            if provider is None:
                return (None, None)
            try:
                comparison = provider.compare_versions(section, base, target)
            except Exception:
                comparison = None
            body: Any | None = None
            if target > 0:
                try:
                    body = provider.load_version(section, target)
                except Exception:
                    body = None
            return (comparison, body)

        comparison, body = await asyncio.to_thread(_fetch)
        if generation != self._history_generation or self.document is not document:
            return
        self._set_footer_status(None)
        if not isinstance(comparison, dict):
            self.notify("Diff load failed — keeping read view.", severity="warning")
            return
        if len(state.comparison_cache) >= _HISTORY_CACHE_LIMIT:
            state.comparison_cache.clear()
        state.comparison_cache[(base, target)] = comparison
        if isinstance(body, PagerSection) and target > 0:
            if len(state.body_cache) >= _HISTORY_CACHE_LIMIT:
                state.body_cache.clear()
            state.body_cache[(target, state.subject_id)] = body
        try:
            self._recompose_for_history_marks()
        except Exception:
            pass
        self._apply_diff_view(identity, base, target, comparison)

    def _diff_read_section(
        self: Any, identity: str, state: Any, target: int
    ) -> PagerSection | None:
        if target == 0:
            live = getattr(state, "live_section", None)
            if isinstance(live, PagerSection):
                return live
            try:
                current = next(
                    s for s in self.document.sections if s.identity == identity
                )
            except StopIteration:
                return None
            pin = getattr(current, "version_pin", None)
            if pin is None or getattr(pin, "view", "read") == "read":
                return current
            return None
        cached = state.body_cache.get((target, state.subject_id))
        if isinstance(cached, PagerSection):
            return cached
        return None

    def _apply_diff_view(
        self: Any, identity: str, base: int, target: int, comparison: dict[str, Any]
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        read_section = self._diff_read_section(identity, state, target)
        if read_section is None:
            self.notify("Diff load failed — keeping read view.", severity="warning")
            return
        # Keep the current ordinal: at a clean now the diff renders the
        # newest version's change against the live body, but the pin must
        # stay on now so the chrome never claims the past unprompted.
        pin = state.current_pin
        if pin is None:
            pin = read_section.version_pin
        if pin is None:
            from sase.pager.history.models import live_pin_for_subject

            pin = live_pin_for_subject(state.subject_id)
        try:
            new_pin = replace(
                pin,
                view="diff",
                compare_base=base if base > 0 else None,
                explicit_base=bool(getattr(pin, "explicit_base", False)),
            )
        except Exception:
            return
        try:
            styles_fn = getattr(self, "_history_styles", None)
            styles = styles_fn() if callable(styles_fn) else None
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
                history_styles=styles,
            )
        except Exception:
            self.notify("Diff render failed — keeping read view.", severity="warning")
            return
        try:
            index = next(
                i
                for i, s in enumerate(self.document.sections)
                if s.identity == identity
            )
        except StopIteration:
            return
        try:
            diff_section = replace(
                read_section,
                body=rendered.text,
                targets=rendered.fold_targets,
                version_pin=new_pin,
            )
        except ValueError as exc:
            self.notify(f"Diff render failed — {exc}", severity="warning")
            return
        state.current_pin = new_pin
        sections = list(self.document.sections)
        sections[index] = diff_section
        self.document = replace(self.document, sections=tuple(sections))
        self._body = None
        self._label_layer = None
        self._invalidate_body_layout()
        try:
            if self._search.is_active and self._search.query:
                self._reapply_history_search(self._search.query, self._search.direction)
            elif self._search.is_active:
                self._search.refresh_styled_base()
        except Exception:
            pass
        self._set_footer_status(None)
        self._update_footer()
        self._update_subject()
        try:
            self._schedule_syntax_preparation()
        except Exception:
            pass

    def _diff_unified_for_section(self: Any, section: Any) -> tuple[bool, bool, str]:
        """Return ``(is_diff_view, ready, unified_text)`` for ``yy``.

        *ready* is false while the comparison is still loading; a ready
        but empty text means core recorded no unified diff.
        """
        pin = getattr(section, "version_pin", None)
        if pin is None or getattr(pin, "view", "read") != "diff":
            return (False, False, "")
        state = self._history_states.get(section.identity)
        if state is None:
            return (True, False, "")
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            return (True, False, "")
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            return (True, False, "")
        return (True, True, unified_diff_for_comparison(comparison))
