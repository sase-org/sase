"""Modeless time-band chrome for ``PagerScreen``.

Owns the ``#pager-time`` region between the trail band and the chrome rule:
it builds a :mod:`sase.pager._time_band` model for the current section's
moment (life strip at now, meaning + sparkline rows in the past, honest
states always), paints it with signature caching, and serves the band's
jump-label targets ahead of body targets so band letters stay stable.
All git and file IO stays in the history provider workers; every method
here reads only in-memory state.
"""

from __future__ import annotations

import time
from typing import Any

from textual.widgets import Static

from sase.pager._labels import prefix_free_hint_sequence
from sase.pager._time_band import (
    TimeBandData,
    TimeBandTarget,
    build_time_band_data,
    chrome_row_budget,
    render_time_band,
    time_band_targets,
)


class PagerTimeBandMixin:
    """Own the time-band widget, its model, and its label targets."""

    _body_width: int | None
    _time_band_labels: tuple[TimeBandTarget, ...]
    _time_band_hints: dict[str, int]
    _time_band_signature: object | None

    def _init_time_band_state(self: Any) -> None:
        self._time_band_labels = ()
        self._time_band_hints = {}
        self._time_band_signature = None

    def _time_band_mode(self: Any) -> str:
        """Return ``hidden``/``now``/``past`` for the current section."""
        data = self._time_band_data()
        if data is None:
            return "hidden"
        if data.mode == "notice":
            return "now"
        return data.mode

    def _time_band_data(self: Any) -> TimeBandData | None:
        """Build the band model for the current section, if any."""
        try:
            section = self._current_section()
        except Exception:
            return None
        states = getattr(self, "_history_states", None) or {}
        state = states.get(section.identity)
        if state is None:
            supported = getattr(self, "_history_supported", None) or {}
            if supported.get(section.identity) is False:
                return None
            if not self._time_band_section_recognized(section):
                return None
            return build_time_band_data(
                subject_id=section.subject_ref or section.identity,
                timeline=None,
                current_ordinal=0,
                loading=True,
                now_epoch=int(time.time()),
            )
        timeline = self._timeline_for_time_band(state)
        pin = getattr(state, "current_pin", None) or getattr(
            section, "version_pin", None
        )
        ordinal = int(getattr(pin, "ordinal", 0) or 0)
        try:
            pinned_now = int(getattr(self, "_time_band_now_epoch", None) or 0)
        except Exception:
            pinned_now = 0
        return build_time_band_data(
            subject_id=getattr(state, "subject_id", "")
            or section.subject_ref
            or section.identity,
            timeline=timeline,
            current_ordinal=ordinal,
            dirty=getattr(state, "status", "") == "dirty-now",
            now_epoch=pinned_now or int(time.time()),
            total_visible=len(getattr(state, "visible_ordinals", ()) or ()),
        )

    def _timeline_for_time_band(self: Any, state: Any) -> dict[str, Any]:
        """Reconstruct the provider timeline wire from cached state."""
        timeline: dict[str, Any] = dict(getattr(state, "timeline_meta", None) or {})
        timeline["versions"] = list(getattr(state, "timeline", ()) or ())
        error = getattr(state, "error", None)
        if isinstance(error, str) and error:
            timeline.setdefault("error", error)
        timeline.setdefault("state", "tracked")
        return timeline

    def _time_band_section_recognized(self: Any, section: Any) -> bool:
        """Return whether any history provider owns *section* (no IO)."""
        try:
            from sase.pager.history.provider import history_provider_for_section
        except Exception:
            return False
        try:
            return history_provider_for_section(section) is not None
        except Exception:
            return False

    def _time_band_targets(self: Any) -> tuple[TimeBandTarget, ...]:
        """Return the current band targets in assignment order."""
        try:
            data = self._time_band_data()
        except Exception:
            return ()
        if data is None:
            return ()
        try:
            return time_band_targets(data)
        except Exception:
            return ()

    def _update_subject(self: Any) -> None:
        super()._update_subject()  # type: ignore[misc]
        self._update_time_band()

    def _update_trail(self: Any) -> None:
        super()._update_trail()  # type: ignore[misc]
        self._update_time_band()

    def _build_label_layer(self: Any, width: int, hint_offset: int = 0) -> Any:
        band_targets = self._time_band_targets()
        layer = super()._build_label_layer(  # type: ignore[misc]
            width, hint_offset=hint_offset + len(band_targets)
        )
        try:
            total = len(band_targets) + len(layer.labels)
            sequence = prefix_free_hint_sequence(total)
            self._time_band_hints = {
                sequence[index]: index for index in range(len(band_targets))
            }
            self._time_band_labels = band_targets
        except Exception:
            self._time_band_hints = {}
            self._time_band_labels = ()
        return layer

    def _handle_label_key(self: Any, event: Any) -> bool:
        hints = getattr(self, "_time_band_hints", None) or {}
        if hints:
            from sase.ace.tui.actions.navigation.jump_hints import (
                JumpHintMatchOutcome,
                match_jump_hint,
                normalize_jump_key,
            )

            try:
                key = normalize_jump_key(event.key, event.character)
            except Exception:
                return super()._handle_label_key(event)  # type: ignore[misc]
            match = match_jump_hint(hints, self._label_pending_prefix, key)
            if match.outcome is JumpHintMatchOutcome.COMPLETE:
                index = match.target
                labels = getattr(self, "_time_band_labels", ())
                if index is not None and 0 <= index < len(labels):
                    self._label_pending_prefix = ""
                    self._activate_time_band_label(labels[index])
                    self._repaint_label_state()
                    return True
            elif match.outcome is JumpHintMatchOutcome.PENDING:
                self._label_pending_prefix = match.prefix
                self._repaint_label_state()
                return True
        return super()._handle_label_key(event)  # type: ignore[misc]

    def _activate_time_band_label(self: Any, target: TimeBandTarget) -> None:
        if target.kind == "commit":
            self._activate_time_band_commit(target)
            return
        try:
            index = self._current_section_index()
        except Exception:
            index = 0
        try:
            context = self._link_context_for_section_index(index)
        except Exception:
            context = None
        self._resolve_and_dispatch(
            target.ref,
            intent="follow",
            context=context,
        )

    def _activate_time_band_commit(self: Any, target: TimeBandTarget) -> None:
        """Follow a band commit, copying its SHA when no resolver exists."""
        import asyncio

        from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

        try:
            index = self._current_section_index()
        except Exception:
            index = 0
        try:
            context = self._link_context_for_section_index(index)
        except Exception:
            context = None
        self._set_footer_status("loading")
        self._resolve_generation += 1
        history_bump = getattr(self, "_bump_history_generation", None)
        if callable(history_bump):
            history_bump()
        generation = self._resolve_generation
        document = self.document

        async def resolve_task() -> None:
            try:
                resolved = await asyncio.to_thread(
                    self._resolve_ref,
                    target.ref,
                    context=context,
                )
            except Exception as exc:  # noqa: BLE001 - a press must not crash
                if generation == self._resolve_generation and self.document is document:
                    self._set_footer_status(None)
                    self.notify(f"Could not resolve {target.ref} - {exc}")
                return
            if generation != self._resolve_generation or self.document is not document:
                return
            if resolved is None:
                self._set_footer_status(None)
                self._copy_ref(target.commit or target.display, label="commit")
                return
            self._apply_resolution(
                target.ref,
                resolved,
                intent="follow",
                context=context,
            )

        spawn_pump_free_task(
            self,
            resolve_task(),
            name="sase-pager-time-band-commit",
            registry_attr="_pump_free_resolve_tasks",
        )

    def _update_time_band(self: Any, *, time_rows: int | None = None) -> None:
        """Repaint ``#pager-time`` when its signature changed.

        A changed band target count rebuilds the body label layer so band
        hints stay assigned ahead of body targets.
        """
        try:
            widget = self.query_one("#pager-time", Static)
        except Exception:
            return
        try:
            height = max(int(self._chrome_height()), 1)
        except Exception:
            height = 24
        try:
            snapshot_visible = self._trail_snapshot().visible
        except Exception:
            snapshot_visible = False
        data = self._time_band_data()
        mode = "hidden"
        if data is not None:
            mode = "now" if data.mode != "past" else "past"
        _, budgeted = chrome_row_budget(height, snapshot_visible, mode)
        rows = budgeted if time_rows is None else max(0, min(int(time_rows), 2))
        if data is None or rows == 0:
            labels: tuple[TimeBandTarget, ...] = ()
        else:
            try:
                labels = time_band_targets(data)
            except Exception:
                labels = ()
        previous = getattr(self, "_time_band_labels", ())
        if len(labels) != len(previous) and getattr(self, "_body", None) is not None:
            self._body_width = None
            try:
                self._ensure_body()
            except Exception:
                pass
            hints = getattr(self, "_time_band_hints", None) or {}
        else:
            hints = getattr(self, "_time_band_hints", None) or {}
            if data is not None and labels and not hints:
                try:
                    total = len(labels) + len(getattr(self._label_layer, "labels", ()))
                    sequence = prefix_free_hint_sequence(total)
                    hints = {sequence[index]: index for index in range(len(labels))}
                    self._time_band_hints = hints
                except Exception:
                    hints = {}
        width = self._time_band_paint_width()
        if data is None:
            signature: object = ("hidden", width, rows)
        else:
            signature = (
                data.mode,
                data.subject_id,
                data.spark_current,
                data.dirty,
                data.honest_kind,
                data.honest_detail,
                data.upstream_ahead,
                data.upstream_branch,
                data.newest.ordinal if data.newest is not None else None,
                data.current.ordinal if data.current is not None else 0,
                tuple(sorted(hints)),
                width,
                rows,
            )
        if self._time_band_signature == signature:
            return
        self._time_band_signature = signature
        if data is None or rows == 0:
            widget.update("")
            widget.add_class("hidden")
            widget.remove_class("two")
            self._update_chrome_rule_for_time_band(False)
            return
        # ``hints`` maps hint -> target index for key handling; rendering
        # needs the inverse (target index -> hint capsule).
        paint_hints = {index: hint for hint, index in hints.items()}
        try:
            rendered = render_time_band(data, width=width, rows=rows, hints=paint_hints)
        except Exception:
            widget.update("")
            widget.add_class("hidden")
            widget.remove_class("two")
            self._update_chrome_rule_for_time_band(False)
            return
        widget.update(rendered)
        widget.remove_class("hidden")
        if rows == 2:
            widget.add_class("two")
        else:
            widget.remove_class("two")
        self._update_chrome_rule_for_time_band(True)

    def _update_chrome_rule_for_time_band(self: Any, time_visible: bool) -> None:
        """Hide the chrome rule while the trail or time band shows."""
        try:
            rule = self.query_one("#pager-chrome-rule", Static)
        except Exception:
            return
        try:
            trail_visible = self._trail_snapshot().visible
        except Exception:
            trail_visible = False
        if trail_visible or time_visible:
            rule.add_class("hidden")
        else:
            rule.remove_class("hidden")

    def _time_band_paint_width(self: Any) -> int:
        try:
            widget = self.query_one("#pager-time", Static)
            padding = widget.styles.padding
            horizontal = int(padding.left) + int(padding.right)
            width = int(widget.size.width)
        except Exception:
            return 80
        if width <= 0:
            try:
                width = max(int(self.size.width), int(self._body_scroll().size.width))
            except Exception:
                width = 80
        return max(width - horizontal, 0)


__all__ = ["PagerTimeBandMixin"]
