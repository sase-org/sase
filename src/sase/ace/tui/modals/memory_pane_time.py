"""Card time state: ``(`` ``)`` ``{`` ``}`` stepping through versions.

Owns the phase card-stepping time travel behind :class:`MemoryPane`
(epic design ``plan:202610/memory_history_tui.md`` §10 and §4.3). Step
destinations always come from the pager's moment model
(:mod:`sase.pager.history_kit` ``build_moment`` / ``step_target`` /
``boundary_notice``); this module never re-derives numbering.

Pins are keyed per ``(scope_key, selector)`` so they never carry across
subjects (arrival rule D7). The displayed (applied) ordinal only ever
advances together with its body bytes: one immutable moment is applied
atomically, and a slow body shows an explicit ``loading vN…`` strip
instead of another version's text (§5.4 rules 1, 2, 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Toast shown when a mutation key is pressed while pinned in the past.
PIN_EDIT_REFUSAL = "leave the past to edit · } now"

#: Cap for memoized past bodies per pane (FIFO eviction).
_TIME_BODY_CACHE_SIZE = 256

#: Cap for parsed past notes per pane (FIFO eviction).
_TIME_PARSED_CACHE_SIZE = 64


@dataclass(frozen=True)
class _PastCard:
    """Everything one past-card paint needs, from a single moment."""

    applied_ordinal: int
    target_ordinal: int
    moment: Any
    body_text: str | None


def _moment_for_card(
    timeline: dict[str, Any] | None,
    *,
    subject_id: str,
    pin_ordinal: int,
) -> Any | None:
    """Return the kit moment for *pin_ordinal* (0 means now), or ``None``.

    Never raises: ``None`` means the card renders as it would with no
    history (fail-open per §5.4 rule 4).
    """
    if not isinstance(timeline, dict):
        return None
    try:
        from sase.pager.history_kit import (
            build_moment,
            committed_pin_for_ordinal,
            dirty_now_from_timeline,
            is_deleted_row,
            live_pin_for_subject,
            visible_ordinals_for_timeline,
        )

        versions = timeline.get("versions", ())
        rows = [
            row
            for row in (versions if isinstance(versions, (list, tuple)) else ())
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        if not rows:
            return None
        visible = visible_ordinals_for_timeline(timeline)
        pinned_row: dict[str, Any] | None = None
        for row in rows:
            try:
                if int(row.get("ordinal", 0) or 0) == int(pin_ordinal):
                    pinned_row = row
                    break
            except (TypeError, ValueError):
                continue
        if int(pin_ordinal) <= 0:
            pin = live_pin_for_subject(subject_id)
            status = "live"
            # Summaries filter out the ordinal-0 pseudo row before
            # caching, so they carry a precomputed `dirty` flag next to
            # the wire the kit reads.
            if bool(timeline.get("dirty", False)) or bool(
                dirty_now_from_timeline(timeline)
            ):
                status = "dirty-now"
        else:
            commit = None
            blob = None
            if pinned_row is not None:
                raw_commit = pinned_row.get("commit")
                commit = str(raw_commit) if isinstance(raw_commit, str) else None
                raw_blob = pinned_row.get("blob_oid")
                blob = str(raw_blob) if isinstance(raw_blob, str) else None
            pin = committed_pin_for_ordinal(
                subject_id, int(pin_ordinal), commit=commit, blob_oid=blob
            )
            status = (
                "tombstone"
                if (pinned_row is not None and bool(is_deleted_row(pinned_row)))
                else "live"
            )
        meta = timeline.get("meta", {})
        return build_moment(
            rows=tuple(rows),
            meta=meta if isinstance(meta, dict) else {},
            visible_ordinals=tuple(visible),
            pin=pin,
            status=status,
        )
    except Exception:
        return None


def _step_destination(moment: Any, intent: str) -> int | None:
    """Return the destination ordinal for *intent*, or ``None``.

    ``None`` means a boundary: the key has nowhere to go. Never raises.
    """
    try:
        from sase.pager.history_kit import step_target

        return step_target(moment, intent)  # type: ignore[arg-type]
    except Exception:
        return None


def _step_boundary_notice(moment: Any, intent: str) -> str:
    """Return the pager's boundary notice for a refused step."""
    try:
        from sase.pager.history_kit import boundary_notice

        return str(boundary_notice(moment, intent))  # type: ignore[arg-type]
    except Exception:
        return "Already at the oldest version."


def step_footer_verbs(moment: Any, *, keymaps: Any) -> tuple[str, ...]:
    """Return the footer step verbs for *moment* with configured keys.

    Only the stepping verbs of this phase (``(`` ``)`` ``}``): the
    ``=``/``@`` verbs belong to later phases whose keys do not exist
    yet, so showing them would advertise dead keys.
    """
    try:
        from sase.pager.history_kit import time_verbs_for_moment
        from sase.ace.tui.keymaps import key_display_name

        verbs = time_verbs_for_moment(moment)
    except Exception:
        return ()
    try:
        key_for = {
            "(": key_display_name(keymaps.history_older),
            ")": key_display_name(keymaps.history_newer),
            "}": key_display_name(keymaps.history_now),
        }
    except Exception:
        key_for = {"(": "(", ")": ")", "}": "}"}
    shown: list[str] = []
    for text, _label in verbs:
        glyph = str(text or "")[:1]
        if glyph not in key_for:
            continue
        rest = str(text or "")[1:]
        shown.append(f"{key_for[glyph]}{rest}")
    return tuple(shown)


def _parse_past_note(node: Any, body_text: str) -> Any | None:
    """Parse a historical body into a :class:`MemoryNote`, or ``None``."""
    try:
        from sase.memory.notes import parse_memory_note_text

        path = str(getattr(getattr(node, "note", None), "relative_path", "") or "past")
        return parse_memory_note_text(str(body_text or ""), path)
    except Exception:
        return None


class MemoryPaneTimeMixin(_MixinBase):
    """Past pins, step actions, and guards for ``MemoryPane``."""

    if TYPE_CHECKING:
        _closed: bool
        _history_failed: set[tuple[str, str]]
        _history_latest: dict[tuple[str, str], dict]
        _keymaps: Any
        _loading: bool
        _ring: tuple[Any, ...]
        _scope_index: int
        _time_applied: dict[tuple[str, str], int]
        _time_bodies: dict[tuple[str, str, int], dict[str, Any]]
        _time_generation: int
        _time_parsed: dict[tuple[str, str, int], Any]
        _time_pending: dict[tuple[str, str], str]
        _time_pins: dict[tuple[str, str], int]
        _time_prefetched_key: tuple[str, str] | None
        _time_request: tuple[str, str, int, int] | None
        _time_worker: Worker[tuple[str, str, int, int, dict | None]] | None
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_strip_snapshot_for_node(self, node: Any | None) -> Any | None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Worker: ...  # type: ignore[override]

    # --- pin state ------------------------------------------------------

    def _time_key(self, node: Any | None) -> tuple[str, str] | None:
        """Return the ``(scope_key, selector)`` pin key for *node*."""
        try:
            keyed = self._history_key_for_node(node)
        except Exception:
            return None
        if keyed is None:
            return None
        return (keyed[0], keyed[1])

    def _time_pinned_ordinal(self, node: Any | None) -> int:
        """Return the target pin ordinal for *node* (0 means now)."""
        key = self._time_key(node)
        if key is None:
            return 0
        try:
            return int(self._time_pins.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _time_applied_ordinal(self, node: Any | None) -> int:
        """Return the displayed ordinal for *node* (0 means now)."""
        key = self._time_key(node)
        if key is None:
            return 0
        try:
            return int(self._time_applied.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _time_timeline(self, node: Any | None) -> dict[str, Any] | None:
        """Return the cached timeline for *node* without blocking."""
        key = self._time_key(node)
        if key is None:
            return None
        cached = self._history_latest.get(key)
        return dict(cached) if isinstance(cached, dict) else None

    def _time_subject_id(self, node: Any | None) -> str:
        """Return the band subject id for *node*."""
        try:
            keyed = self._history_key_for_node(node)
            selector = keyed[1] if keyed is not None else ""
        except Exception:
            selector = ""
        try:
            from .memory_pane_time_strip import subject_id_for_selector

            is_strand = bool(getattr(node, "strand", None) is not None)
            return subject_id_for_selector(str(selector or ""), is_strand=is_strand)
        except Exception:
            return f"note:{selector}"

    def _card_moment(self, node: Any | None, *, applied: bool = True) -> Any | None:
        """Return the kit moment for *node*'s applied (or target) pin."""
        ordinal = (
            self._time_applied_ordinal(node)
            if applied
            else self._time_pinned_ordinal(node)
        )
        if ordinal <= 0:
            return None
        return _moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=ordinal,
        )

    def _now_moment_for_footer(self, node: Any | None) -> Any | None:
        """Return the live moment for *node* so now cards show `( vN`."""
        return _moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=0,
        )

    def _past_card_for_node(self, node: Any | None) -> _PastCard | None:
        """Return the atomic past-card state for *node*, if pinned."""
        applied = self._time_applied_ordinal(node)
        if applied <= 0:
            return None
        key = self._time_key(node)
        if key is None:
            return None
        moment = _moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=applied,
        )
        if moment is None:
            return None
        wire = self._time_bodies.get((key[0], key[1], applied))
        body_text: str | None = None
        if isinstance(wire, dict):
            if bool(wire.get("body_missing")):
                body_text = "(unavailable: historical body is not stored)"
            else:
                try:
                    body_text = str(wire.get("body", "") or "")
                except Exception:
                    body_text = None
        return _PastCard(
            applied_ordinal=applied,
            target_ordinal=self._time_pinned_ordinal(node),
            moment=moment,
            body_text=body_text,
        )

    def _time_past_note(self, node: Any, body_text: str) -> Any | None:
        """Return the parsed past note for *node*, memoized per version."""
        key = self._time_key(node)
        if key is None:
            return None
        cache_key = (key[0], key[1], self._time_applied_ordinal(node))
        cached = self._time_parsed.get(cache_key)
        if cached is not None:
            return cached
        parsed = _parse_past_note(node, body_text)
        if parsed is None:
            return None
        self._time_parsed[cache_key] = parsed
        while len(self._time_parsed) > _TIME_PARSED_CACHE_SIZE:
            try:
                self._time_parsed.pop(next(iter(self._time_parsed)))
            except StopIteration:
                break
        return parsed

    # --- step actions -----------------------------------------------------

    def _step_time_pin(self, intent: str) -> None:
        """Step the current card along *intent* (``older``/``newer``/… )."""
        from sase.ace.tui.util.trace import tui_trace

        with tui_trace("memory.history.step", intent=intent):
            node = self._selected_row()
            key = self._time_key(node)
            if node is None or key is None:
                return
            timeline = self._time_timeline(node)
            if timeline is None:
                if key in self._history_failed:
                    self.notify(
                        "history unavailable for this selection", severity="error"
                    )
                    return
                # Indexing: record the intent (last wins) and apply it
                # when the timeline lands (§5.4 rule 6).
                self._time_pending[key] = intent
                try:
                    self._ensure_history_load(key[0], key[1])
                except Exception:
                    pass
                return
            moment = _moment_for_card(
                timeline,
                subject_id=self._time_subject_id(node),
                pin_ordinal=self._time_pinned_ordinal(node),
            )
            if moment is None:
                self.notify("No history to step through.", severity="warning")
                return
            self._apply_step_intent(key, node, timeline, moment, intent)

    def _apply_step_intent(
        self,
        key: tuple[str, str],
        node: Any,
        timeline: dict[str, Any],
        moment: Any,
        intent: str,
    ) -> None:
        """Apply one step intent against a loaded timeline and moment."""
        destination = _step_destination(moment, intent)
        if destination is None:
            self.notify(_step_boundary_notice(moment, intent), severity="warning")
            return
        if int(destination) == 0:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self._time_pending.pop(key, None)
            self._render_note_card()
            self._prefetch_time_bodies(node, timeline, center_ordinal=0)
            return
        self._time_pins[key] = int(destination)
        self._time_pending.pop(key, None)
        if not self._ensure_time_body(key, node, int(destination)):
            # Cache miss: the previous version stays on screen with a
            # ``loading vN…`` strip until the worker lands (last wins).
            self._render_note_card()
        else:
            self._apply_time_pin(key, node, int(destination))

    def action_history_older(self) -> None:
        """Step the card to the older version."""
        self._step_time_pin("older")

    def action_history_newer(self) -> None:
        """Step the card to the newer version."""
        self._step_time_pin("newer")

    def action_history_first(self) -> None:
        """Step the card to the first version."""
        self._step_time_pin("first")

    def action_history_now(self) -> None:
        """Return the card to now."""
        self._step_time_pin("now")

    # --- body loads, prefetch, atomic apply -------------------------------

    def _remember_time_body(
        self, key: tuple[str, str], ordinal: int, wire: dict[str, Any]
    ) -> None:
        """Memoize one version wire, evicting oldest first when full."""
        self._time_bodies[(key[0], key[1], int(ordinal))] = wire
        while len(self._time_bodies) > _TIME_BODY_CACHE_SIZE:
            try:
                self._time_bodies.pop(next(iter(self._time_bodies)))
            except StopIteration:
                break

    def _ensure_time_body(self, key: tuple[str, str], node: Any, ordinal: int) -> bool:
        """Start a worker for a missing past body; True when cached."""
        if (key[0], key[1], int(ordinal)) in self._time_bodies:
            return True
        try:
            keyed = self._history_key_for_node(node)
            ref = keyed[2] if keyed is not None else None
        except Exception:
            ref = None
        if ref is None:
            return False
        self._time_generation += 1
        generation = self._time_generation
        version_arg = f"v{int(ordinal)}"
        self._time_request = (key[0], key[1], int(ordinal), generation)

        def task() -> tuple[str, str, int, int, dict | None]:
            try:
                from .memory_panel_history import selector_for_node

                history = self._ace_history()
                if history is None:
                    return (key[0], key[1], int(ordinal), generation, None)
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return (key[0], key[1], int(ordinal), generation, None)
                wire = history.version_body(scope, selector_for_node(node), version_arg)
                return (
                    key[0],
                    key[1],
                    int(ordinal),
                    generation,
                    dict(wire) if isinstance(wire, dict) else None,
                )
            except Exception:
                return (key[0], key[1], int(ordinal), generation, None)

        try:
            self._time_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-body",
                exit_on_error=False,
            )
        except Exception:
            return False
        return False

    def _on_time_body_state_changed(self, event: Any) -> None:
        """Apply a landed past body only when it is still the target."""
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 5:
            return
        scope_key, selector, ordinal, generation, wire = result
        key = (scope_key, selector)
        if self._time_request != (scope_key, selector, int(ordinal), generation):
            return  # Stale: a newer step already won.
        self._time_request = None
        if not isinstance(wire, dict):
            # Fail-open: drop the pin and say so (§5.4 rule 4).
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self.notify("past body unavailable · back at now", severity="warning")
            if self._closed or not self.is_mounted:
                return
            try:
                self._render_note_card()
            except Exception:
                pass
            return
        self._remember_time_body(key, int(ordinal), wire)
        if self._time_pins.get(key, 0) != int(ordinal):
            return  # The user stepped elsewhere meanwhile.
        node = self._selected_row()
        if node is None or self._time_key(node) != key:
            return  # Stale: the selection moved before this load landed.
        self._apply_time_pin(key, node, int(ordinal))

    def _apply_time_pin(self, key: tuple[str, str], node: Any, ordinal: int) -> None:
        """Atomically show *ordinal*: pill, strip, frame, body, footer."""
        self._time_applied[key] = int(ordinal)
        if self._closed or not self.is_mounted:
            return
        try:
            self._render_note_card()
        except Exception:
            pass
        try:
            timeline = self._time_timeline(node)
            if timeline is not None:
                self._prefetch_time_bodies(node, timeline, center_ordinal=int(ordinal))
        except Exception:
            pass

    def _prefetch_time_bodies(
        self, node: Any, timeline: dict[str, Any], *, center_ordinal: int
    ) -> None:
        """Fetch the nearest two older/newer bodies off-thread (§5.4.6)."""
        key = self._time_key(node)
        if key is None or self._loading:
            return
        try:
            from sase.pager.history_kit import visible_ordinals_for_timeline

            visible = [int(v) for v in visible_ordinals_for_timeline(timeline)]
        except Exception:
            return
        if not visible:
            return
        center = int(center_ordinal) if int(center_ordinal) > 0 else max(visible) + 1
        ordered = sorted(visible)
        older = [v for v in ordered if v < center][-2:]
        newer = [v for v in ordered if v > center][:2]
        missing = [
            v for v in (*older, *newer) if (key[0], key[1], v) not in self._time_bodies
        ]
        if not missing:
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
                for ordinal in missing:
                    if self._closed:
                        return
                    cache_key = (key[0], key[1], int(ordinal))
                    if cache_key in self._time_bodies:
                        continue
                    try:
                        wire = history.version_body(scope, selector, f"v{int(ordinal)}")
                    except Exception:
                        continue
                    if isinstance(wire, dict):
                        self._remember_time_body(key, int(ordinal), wire)
            except Exception:
                pass

        try:
            self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-prefetch",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _maybe_prefetch_at_now(self, node: Any | None) -> None:
        """Prefetch neighbours once per selection while at now."""
        if node is None or self._time_pinned_ordinal(node) > 0:
            return
        key = self._time_key(node)
        if key is None or key == self._time_prefetched_key:
            return
        timeline = self._time_timeline(node)
        if timeline is None:
            return
        self._time_prefetched_key = key
        try:
            self._prefetch_time_bodies(node, timeline, center_ordinal=0)
        except Exception:
            pass

    # --- arrival, freshness, pending intents --------------------------------

    def _after_history_landed(self, scope_key: str, selector: str) -> None:
        """Re-resolve the pin, apply pending steps, prefetch at now."""
        key = (scope_key, selector)
        summary = self._history_latest.get(key)
        if not isinstance(summary, dict):
            return
        node = self._selected_row()
        if node is None or self._time_key(node) != key:
            return
        try:
            self._reresolve_time_pin(key, node, summary)
        except Exception:
            pass
        pending = self._time_pending.pop(key, None)
        if pending is not None:
            try:
                moment = _moment_for_card(
                    summary,
                    subject_id=self._time_subject_id(node),
                    pin_ordinal=self._time_pinned_ordinal(node),
                )
                if moment is None:
                    self.notify("No history to step through.", severity="warning")
                else:
                    self._apply_step_intent(key, node, summary, moment, pending)
                    return
            except Exception:
                pass
        try:
            self._maybe_prefetch_at_now(node)
        except Exception:
            pass

    def _reresolve_time_pin(
        self, key: tuple[str, str], node: Any, timeline: dict[str, Any]
    ) -> None:
        """Hold the pin across index rebuilds (§5.2 rule 5).

        The pin re-resolves by commit and blob; ``N newer`` updates come
        free with the new timeline. A vanished version returns to now
        with a toast.
        """
        pinned = int(self._time_pins.get(key, 0) or 0)
        if pinned <= 0:
            return
        rows = timeline.get("versions", ())
        match: dict[str, Any] | None = None
        if isinstance(rows, (list, tuple)):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    if int(row.get("ordinal", 0) or 0) == pinned:
                        match = row
                        break
                except (TypeError, ValueError):
                    continue
        if match is None:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self.notify("that version is gone · back at now", severity="warning")
            try:
                self._render_note_card()
            except Exception:
                pass

    def _drop_time_state_for_scope(self, scope_key: str) -> None:
        """Forget pins, bodies, and intents after scope invalidation."""
        pin_key: tuple[str, str]
        for pin_key in [key for key in self._time_pins if key[0] == scope_key]:
            self._time_pins.pop(pin_key, None)
        for pin_key in [key for key in self._time_applied if key[0] == scope_key]:
            self._time_applied.pop(pin_key, None)
        for pin_key in [key for key in self._time_pending if key[0] == scope_key]:
            self._time_pending.pop(pin_key, None)
        body_key: tuple[str, str, int]
        for body_key in [key for key in self._time_bodies if key[0] == scope_key]:
            self._time_bodies.pop(body_key, None)
        for body_key in [key for key in self._time_parsed if key[0] == scope_key]:
            self._time_parsed.pop(body_key, None)
        if (
            self._time_prefetched_key is not None
            and self._time_prefetched_key[0] == scope_key
        ):
            self._time_prefetched_key = None

    # --- Esc rung, guards, H -------------------------------------------------

    def _time_unpin_if_pinned(self) -> bool:
        """Return to now when pinned; True when the rung was consumed."""
        node = self._selected_row()
        if node is None or self._time_applied_ordinal(node) <= 0:
            return False
        key = self._time_key(node)
        if key is not None:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self._time_pending.pop(key, None)
        try:
            self._render_note_card()
        except Exception:
            pass
        return True

    def _refuse_while_pinned(self) -> bool:
        """Toast the past-edit refusal; True when the key must stop."""
        node = self._selected_row()
        applied = self._time_applied_ordinal(node) if node is not None else 0
        if applied <= 0:
            return False
        self.notify(PIN_EDIT_REFUSAL, severity="warning")
        return True

    def _refuse_link_while_pinned(self) -> bool:
        """Toast the past-link refusal; True when the key must stop."""
        node = self._selected_row()
        applied = self._time_applied_ordinal(node) if node is not None else 0
        if applied <= 0:
            return False
        self.notify(
            f"links are as of now · H follows them at v{applied}",
            severity="warning",
        )
        return True

    def _history_initial_revision(self) -> str:
        """Return the pager revision for the card's exact pin (``H``)."""
        try:
            applied = self._time_applied_ordinal(self._selected_row())
        except Exception:
            applied = 0
        return f"v{int(applied)}" if int(applied) > 0 else "now"


__all__ = [
    "MemoryPaneTimeMixin",
    "step_footer_verbs",
]
