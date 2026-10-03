"""Sticky word-diff view on the Memory card (``=``).

Owns the phase card-diff toggle behind :class:`MemoryPane` (epic design
``plan:202610/memory_history_tui.md`` §11 and §4.3). ``=`` flips one
pane-global read/diff flag: sticky across selections for the pane
session, reset to read when the pane opens (arrival rule D7).

Endpoints always come from the pager's moment model through
:func:`card_moment_for_view` with ``view="diff"`` and are never
re-derived here: past shows parent → pin, clean now shows the latest
change, dirty now shows HEAD → worktree, the first version compares
against empty, and a tombstone shows the deletion summary.

Committed pairs memoize in a small pane FIFO (the app-scoped service
already caches them by blob pair); anything involving now always
refetches and is never memoized. On a cache miss the read view stays
on screen until the worker lands (last wins); a comparison failure
keeps the read view and toasts (§5.4 rules 1, 2, 4, 6).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Toast shown when ``=`` cannot diff the current selection.
DIFF_UNAVAILABLE = "comparison unavailable · kept the read view"

#: Cap for memoized committed diffs per pane (FIFO eviction).
_DIFF_MEMO_SIZE = 64


def _diff_key(
    scope_key: str, selector: str, base: int, target: int
) -> tuple[str, str, int, int]:
    """Return the memo key for one committed comparison."""
    return (str(scope_key), str(selector), int(base), int(target))


class MemoryPaneDiffMixin(_MixinBase):
    """Sticky read/diff flag, comparison loads, and pager carry."""

    if TYPE_CHECKING:
        _closed: bool
        _diff_failed: set[tuple[str, str, int, int]]
        _diff_generation: int
        _diff_request: tuple[str, str, int, int, int] | None
        _diff_worker: Worker[Any] | None
        _keymaps: Any
        _loading: bool
        _time_diff_view: bool
        _time_diffs: dict[tuple[str, str, int, int], dict[str, Any]]
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_subject_id(self, node: Any | None) -> str: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_strip_styles(self) -> Any: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Worker: ...  # type: ignore[override]

    # --- view state -----------------------------------------------------

    def _diff_view_on(self) -> bool:
        """Return whether the sticky diff view is on for this pane."""
        try:
            return bool(self._time_diff_view)
        except Exception:
            return False

    def _reset_diff_view(self) -> None:
        """Reset the sticky choice to read when the pane opens (D7)."""
        try:
            self._time_diff_view = False
        except Exception:
            pass
        try:
            self._diff_request = None
        except Exception:
            pass
        try:
            self._diff_failed.clear()
        except Exception:
            pass

    def _drop_diff_state_for_scope(self, scope_key: str) -> None:
        """Forget diff memos and failures after scope invalidation."""
        prefix = str(scope_key)
        for attr in ("_time_diffs", "_diff_failed"):
            try:
                memo = getattr(self, attr)
            except Exception:
                continue
            try:
                stale = [key for key in memo if key[0] == prefix]
            except Exception:
                continue
            for key in stale:
                try:
                    if isinstance(memo, dict):
                        memo.pop(key, None)
                    else:
                        memo.discard(key)
                except Exception:
                    pass
        try:
            if self._diff_request is not None and self._diff_request[0] == prefix:
                self._diff_request = None
        except Exception:
            pass

    # --- endpoints ------------------------------------------------------

    def _diff_endpoints(self, node: Any | None) -> tuple[int, int] | None:
        """Return the ``(base, target)`` pair for *node*, or ``None``.

        The pair comes from the card's displayed (applied) version read
        through a diff-view kit moment, so pill, body, strip, and diff
        always describe the same version (§5.4 rule 2).
        """
        if node is None:
            return None
        try:
            from .memory_pane_time import card_moment_for_view

            timeline = self._time_timeline(node)
            moment = card_moment_for_view(
                timeline,
                subject_id=self._time_subject_id(node),
                pin_ordinal=self._time_applied_ordinal(node),
                view="diff",
            )
        except Exception:
            return None
        if moment is None:
            return None
        try:
            diff = getattr(moment, "diff", None)
            if diff is None:
                return None
            base, target = int(diff[0]), int(diff[1])
        except (TypeError, ValueError, IndexError):
            return None
        return (base, target)

    def _diff_ready_for_node(
        self, node: Any | None
    ) -> tuple[dict[str, Any], str] | None:
        """Return the memoized ``(comparison, target body)``, if ready."""
        if not self._diff_view_on() or node is None:
            return None
        key = self._time_key(node)
        endpoints = self._diff_endpoints(node)
        if key is None or endpoints is None:
            return None
        try:
            memo = self._time_diffs.get(
                _diff_key(key[0], key[1], endpoints[0], endpoints[1])
            )
        except Exception:
            return None
        if not isinstance(memo, dict):
            return None
        comparison = memo.get("comparison")
        body = memo.get("body")
        if not isinstance(comparison, dict) or not isinstance(body, str):
            return None
        return (comparison, body)

    def _diff_overlay_for_node(self, node: Any | None) -> Any | None:
        """Return head/strip chrome for a ready diff, or ``None``.

        The overlay carries the diff-view kit moment (so the pill
        context gains the pager's ``Δ vA → vB`` segment and strip row 1
        shows the band's diff row) with the card's own applied/target
        ordinals, so an in-flight step still shows its loading strip.
        ``None`` means the card renders its read chrome: diff off, not
        ready yet, or failed (the read view stays on screen).
        """
        if not self._diff_view_on() or node is None:
            return None
        if self._diff_ready_for_node(node) is None:
            return None
        try:
            from .memory_pane_time import card_moment_for_view

            timeline = self._time_timeline(node)
            moment = card_moment_for_view(
                timeline,
                subject_id=self._time_subject_id(node),
                pin_ordinal=self._time_applied_ordinal(node),
                view="diff",
            )
        except Exception:
            return None
        if moment is None:
            return None
        try:
            return SimpleNamespace(
                moment=moment,
                applied_ordinal=self._time_applied_ordinal(node),
                target_ordinal=self._time_pinned_ordinal(node),
            )
        except Exception:
            return None

    def _diff_text_for_node(self, node: Any | None) -> Any | None:
        """Return the rendered diff body for *node*, or ``None``."""
        ready = self._diff_ready_for_node(node)
        if ready is None:
            return None
        comparison, target_body = ready
        try:
            from sase.pager.history_kit import build_diff_body

            built = build_diff_body(
                comparison, target_body, history_styles=self._time_strip_styles()
            )
            return built.text
        except Exception:
            return None

    # --- toggle action --------------------------------------------------

    def action_history_toggle_diff(self) -> None:
        """Toggle the sticky read/diff view for the pane session."""
        from sase.ace.tui.util.trace import tui_trace

        with tui_trace("memory.history.diff", op="toggle"):
            node = self._selected_row()
            key = self._time_key(node)
            if node is None or key is None:
                self.notify("no history for this selection", severity="warning")
                return
            timeline = self._time_timeline(node)
            if timeline is None:
                try:
                    failed = key in getattr(self, "_history_failed", set())
                except Exception:
                    failed = False
                if failed:
                    self.notify("history unavailable · r retry", severity="warning")
                    return
                # Indexing: flip the flag and let the render-path load
                # fetch the diff when the timeline lands (§5.4 rule 6).
                self._time_diff_view = not self._time_diff_view
                try:
                    self._render_note_card()
                except Exception:
                    pass
                return
            self._time_diff_view = not self._time_diff_view
            if self._time_diff_view:
                try:
                    self._ensure_diff(node)
                except Exception:
                    pass
                try:
                    endpoints = self._diff_endpoints(node)
                    if endpoints is not None:
                        self._prefetch_diff_comparisons(node, *endpoints)
                except Exception:
                    pass
            try:
                self._render_note_card()
            except Exception:
                pass

    # --- comparison loads, memo, atomic apply ---------------------------

    def _remember_diff(
        self,
        key: tuple[str, str, int, int],
        comparison: dict[str, Any],
        body: str,
    ) -> None:
        """Memoize one committed comparison (FIFO eviction).

        Pairs involving now always refetch and are never memoized, so
        an edit or a return from the editor is visible on the next
        render without explicit invalidation.
        """
        if key[2] <= 0 and key[3] <= 0:
            return
        if key[2] == 0 or key[3] == 0:
            # Now-involving pairs are never cached (service LRU agrees).
            return
        self._time_diffs[key] = {"comparison": comparison, "body": body}
        while len(self._time_diffs) > _DIFF_MEMO_SIZE:
            try:
                self._time_diffs.pop(next(iter(self._time_diffs)))
            except StopIteration:
                break

    def _ensure_diff(self, node: Any) -> bool:
        """Start a worker for a missing diff; True when ready to render."""
        if self._diff_ready_for_node(node) is not None:
            return True
        key = self._time_key(node)
        endpoints = self._diff_endpoints(node)
        if key is None or endpoints is None or self._loading:
            return False
        base, target = endpoints
        memo_key = _diff_key(key[0], key[1], base, target)
        try:
            if memo_key in self._diff_failed:
                return False
        except Exception:
            pass
        try:
            if self._diff_request is not None and self._diff_request[:4] == memo_key:
                return False  # Already in flight; last wins on landing.
        except Exception:
            pass
        try:
            keyed = self._history_key_for_node(node)
            ref = keyed[2] if keyed is not None else None
        except Exception:
            ref = None
        if ref is None:
            return False
        try:
            from .memory_panel_history import selector_for_node

            selector = selector_for_node(node)
        except Exception:
            return False
        self._diff_generation += 1
        generation = self._diff_generation
        self._diff_request = (key[0], key[1], base, target, generation)

        def task() -> tuple[
            str, str, int, int, int, dict | None, str | None, str | None
        ]:
            try:
                history = self._ace_history()
                if history is None:
                    return (
                        key[0],
                        key[1],
                        base,
                        target,
                        generation,
                        None,
                        None,
                        "no history service",
                    )
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return (
                        key[0],
                        key[1],
                        base,
                        target,
                        generation,
                        None,
                        None,
                        "no scope",
                    )
                if base <= 0 and target > 0:
                    # First version: compare against empty, exactly as
                    # the pager provider does for the same endpoints.
                    wire = history.version_body(scope, selector, f"v{target}")
                    body = str(wire.get("body", "") or "")
                    if bool(wire.get("body_missing")):
                        return (
                            key[0],
                            key[1],
                            base,
                            target,
                            generation,
                            None,
                            None,
                            "body not stored",
                        )
                    from sase.core.rust import require_rust_binding

                    binding = require_rust_binding("compare_prose")
                    comparison = dict(
                        binding(
                            {
                                "base": "",
                                "target": body,
                                "format": "prose",
                                "context_lines": 3,
                            }
                        )
                    )
                    return (
                        key[0],
                        key[1],
                        base,
                        target,
                        generation,
                        comparison,
                        body,
                        None,
                    )
                base_arg = f"v{base}" if base > 0 else "now"
                target_arg = f"v{target}" if target > 0 else "now"
                comparison = dict(
                    history.comparison(scope, selector, base_arg, target_arg)
                )
                target_wire = history.version_body(scope, selector, target_arg)
                target_body = str(target_wire.get("body", "") or "")
                if bool(target_wire.get("body_missing")):
                    return (
                        key[0],
                        key[1],
                        base,
                        target,
                        generation,
                        None,
                        None,
                        "body not stored",
                    )
                return (
                    key[0],
                    key[1],
                    base,
                    target,
                    generation,
                    comparison,
                    target_body,
                    None,
                )
            except Exception as exc:
                return (key[0], key[1], base, target, generation, None, None, str(exc))

        try:
            self._diff_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-diff",
                exit_on_error=False,
            )
        except Exception:
            return False
        return False

    def _on_diff_state_changed(self, event: Any) -> None:
        """Apply a landed diff only when it is still the target."""
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 8:
            return
        scope_key, selector, base, target, generation, comparison, body, error = result
        memo_key = _diff_key(scope_key, selector, int(base), int(target))
        if self._diff_request != (
            scope_key,
            selector,
            int(base),
            int(target),
            generation,
        ):
            return  # Stale: a newer toggle or step already won.
        self._diff_request = None
        if not isinstance(comparison, dict) or not isinstance(body, str):
            # Fail-open: keep the read view and say so (§5.4 rule 4).
            try:
                self._diff_failed.add(memo_key)
            except Exception:
                pass
            self.notify(DIFF_UNAVAILABLE, severity="warning")
            if self._closed or not self.is_mounted:
                return
            try:
                self._render_note_card()
            except Exception:
                pass
            return
        try:
            self._diff_failed.discard(memo_key)
        except Exception:
            pass
        self._remember_diff(memo_key, comparison, body)
        node = self._selected_row()
        if node is None or self._time_key(node) != (scope_key, selector):
            return  # Stale: the selection moved before this load landed.
        if not self._diff_view_on():
            return
        current = self._diff_endpoints(node)
        if current is None or (int(current[0]), int(current[1])) != (
            int(base),
            int(target),
        ):
            return  # Stale: the pin moved before this load landed.
        if self._closed or not self.is_mounted:
            return
        try:
            self._render_note_card()
        except Exception:
            pass
        try:
            self._prefetch_diff_comparisons(node, int(base), int(target))
        except Exception:
            pass

    def _prefetch_diff_comparisons(self, node: Any, base: int, target: int) -> None:
        """Fetch the pin's parent and neighbours' comparisons off-thread.

        Only committed pairs prefetch; now-involving pairs always
        refetch on demand. Best effort: failures stay silent and the
        render-path load retries them.
        """
        if not self._diff_view_on():
            return
        key = self._time_key(node)
        timeline = self._time_timeline(node)
        if key is None or not isinstance(timeline, dict) or self._loading:
            return
        try:
            from sase.pager.history_kit import visible_ordinals_for_timeline

            visible = sorted(int(v) for v in visible_ordinals_for_timeline(timeline))
        except Exception:
            return
        if not visible:
            return
        applied = 0
        try:
            applied = int(self._time_applied_ordinal(node))
        except Exception:
            applied = 0
        center = (
            int(applied)
            if int(applied) > 0
            else int(target)
            if int(target) > 0
            else max(visible)
        )
        neighbours = [v for v in visible if abs(v - center) <= 2 and v != center]
        pairs = [(int(base), int(target))]
        for ordinal in neighbours:
            below = [v for v in visible if v < ordinal]
            pairs.append(((max(below) if below else 0), int(ordinal)))
        wanted: list[tuple[int, int]] = []
        for pair_base, pair_target in pairs:
            if pair_base <= 0 or pair_target <= 0:
                continue  # Now-involving pairs never prefetch.
            memo_key = _diff_key(key[0], key[1], pair_base, pair_target)
            try:
                if memo_key in self._time_diffs or memo_key in self._diff_failed:
                    continue
            except Exception:
                pass
            wanted.append((pair_base, pair_target))
        if not wanted:
            return
        try:
            keyed = self._history_key_for_node(node)
            ref = keyed[2] if keyed is not None else None
        except Exception:
            ref = None
        if ref is None:
            return
        try:
            from .memory_panel_history import selector_for_node

            selector = selector_for_node(node)
        except Exception:
            return

        def task() -> None:
            try:
                history = self._ace_history()
                if history is None:
                    return
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return
                for pair_base, pair_target in wanted[:5]:
                    if self._closed:
                        return
                    memo_key = _diff_key(key[0], key[1], pair_base, pair_target)
                    try:
                        if memo_key in self._time_diffs:
                            continue
                    except Exception:
                        pass
                    try:
                        comparison = dict(
                            history.comparison(
                                scope, selector, f"v{pair_base}", f"v{pair_target}"
                            )
                        )
                        target_wire = history.version_body(
                            scope, selector, f"v{pair_target}"
                        )
                        target_body = str(target_wire.get("body", "") or "")
                    except Exception:
                        continue
                    if bool(target_wire.get("body_missing")):
                        continue
                    self._remember_diff(memo_key, comparison, target_body)
            except Exception:
                pass

        try:
            self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-diff-prefetch",
                exit_on_error=False,
            )
        except Exception:
            pass

    # --- pager carry ----------------------------------------------------

    def _history_diff_carry(self) -> tuple[str, str | None]:
        """Return the pager ``(view, compare_base)`` for the card's state.

        ``H`` carries the exact view on screen; a committed base rides
        along for past pins (a ``now`` target's explicit base waits for
        the Timeline-lens ``explicit_base`` support).
        """
        try:
            if not self._diff_view_on():
                return ("read", None)
            node = self._selected_row()
            endpoints = self._diff_endpoints(node)
            if endpoints is None:
                return ("read", None)
            base = int(endpoints[0])
            return ("diff", f"v{base}" if base > 0 else None)
        except Exception:
            return ("read", None)


__all__ = [
    "DIFF_UNAVAILABLE",
    "MemoryPaneDiffMixin",
]
