"""Sticky subject and footer chrome for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.pager._chrome import (
    footer_legend,
    section_accent,
    subject_line,
    subject_parts,
    time_verbs_for_moment,
)
from sase.pager._layout import current_section_index
from sase.pager.history.styles import HistoryStyles, history_styles_for_theme


class PagerChromeMixin:
    """Render the visible pager chrome around the scrollable body."""

    def _history_styles(self: Any) -> HistoryStyles:
        """Return the cached theme-aware history style set."""
        theme_fn = getattr(self, "_current_syntax_theme", None)
        theme = theme_fn() if callable(theme_fn) else None
        return history_styles_for_theme(theme)

    _chrome_signature: object | None

    def _set_footer_status(self: Any, status: str | None) -> None:
        self._footer_status = status
        self._update_footer()

    def _visible_label_count(self: Any) -> int:
        if self._label_layer is None:
            return 0
        return self._label_layer.visible_label_count

    def _history_chrome_state(self: Any) -> tuple[bool, bool, dict[str, object] | None]:
        states = getattr(self, "_history_states", None)
        if not states:
            return (False, False, None)
        try:
            section = self._current_section()
        except Exception:
            return (False, False, None)
        state = states.get(section.identity)
        if state is None:
            return (False, False, None)
        from sase.pager.history.moment import moment_for_state

        moment = moment_for_state(state)
        pin = state.current_pin or section.version_pin
        kind: str
        view: str
        if moment is not None:
            # Numbering is absolute: the displayed version over N, the
            # newest committed ordinal with hidden versions included.
            ordinal = moment.ordinal
            total = moment.newest
            kind = moment.kind
            view = moment.view
            age = ""
            if moment.committed_time:
                try:
                    import time as _time

                    from sase.pager._time_band_vocab import format_age

                    age = format_age(int(_time.time()), moment.committed_time)
                except Exception:
                    age = ""
        else:
            ordinal = pin.ordinal if pin is not None else 0
            # Fail-open numbering stays absolute: the newest committed
            # ordinal, hidden versions included, never a visible count.
            total = 0
            try:
                rows = getattr(state, "timeline", ())
                if isinstance(rows, (list, tuple)):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        try:
                            value = int(row.get("ordinal", 0) or 0)
                        except (TypeError, ValueError):
                            continue
                        if value > total:
                            total = value
                if not total:
                    visible = getattr(state, "visible_ordinals", ())
                    if isinstance(visible, (list, tuple)) and visible:
                        total = max(int(v or 0) for v in visible)
            except Exception:
                total = 0
            if not total:
                try:
                    total = len(state.visible_ordinals)
                except Exception:
                    total = 0
            kind = ""
            view = str(getattr(pin, "view", "read") or "read")
            age = ""
        if moment is not None and moment.view == "diff" and moment.diff is not None:
            diff_base: int | None = moment.diff[0]
            diff_target: int | None = moment.diff[1]
        else:
            diff_base = self._history_diff_base_for(state, ordinal)
            diff_target = ordinal if view == "diff" else None
        history_state: dict[str, object] = {
            "ordinal": ordinal,
            "total": total,
            "kind": kind,
            "dirty": kind == "now_dirty" or state.status == "dirty-now",
            "tombstone": kind == "deleted" or state.status == "tombstone",
            "age": age,
            "view": view,
            "diff_base": diff_base,
            "diff_target": diff_target,
            "moment": moment,
            "time_verbs": time_verbs_for_moment(moment),
        }
        try:
            height = max(int(self._chrome_height()), 1)
        except Exception:
            height = 24
        history_state["band_folded"] = height <= 12
        if height <= 12:
            # The time band folds into the subject chip at this height, so
            # the honest state rides along instead of vanishing with it.
            band_fn = getattr(self, "_time_band_data", None)
            if callable(band_fn):
                try:
                    band_data = band_fn()
                except Exception:
                    band_data = None
                if band_data is not None and getattr(
                    band_data, "honest_kind", "ok"
                ) not in ("ok", None):
                    history_state["folded_honest"] = (
                        getattr(band_data, "honest_kind", ""),
                        getattr(band_data, "honest_detail", None),
                    )
        # Pinned means the live pin reads a committed version; a clean
        # now ≡ vN still counts its version in the chip but is not pinned.
        pinned = pin.ordinal > 0 if pin is not None else False
        return (True, pinned, history_state)

    def _history_diff_base_for(self: Any, state: Any, ordinal: int) -> int | None:
        # Chrome fallback reads the moment first; the old function is only
        # the fail-open path where no moment can be built.
        try:
            from sase.pager.history.moment import moment_for_state

            moment = moment_for_state(state) if state is not None else None
        except Exception:
            moment = None
        if moment is not None:
            diff = getattr(moment, "diff", None)
            if diff is not None:
                try:
                    return int(diff[0])
                except (TypeError, ValueError, IndexError):
                    pass
            if getattr(moment, "view", "read") == "diff":
                return None
        try:
            from sase.pager.history.diff import diff_endpoints
        except Exception:
            return None
        try:
            pin = state.current_pin
            compare_base = getattr(pin, "compare_base", None)
            base_override = int(compare_base) if compare_base is not None else None
            explicit = bool(getattr(pin, "explicit_base", False))
        except (TypeError, ValueError):
            base_override = None
            explicit = False
        try:
            endpoints = diff_endpoints(
                ordinal=ordinal,
                visible_ordinals=tuple(state.visible_ordinals),
                dirty=bool(state.status == "dirty-now"),
                compare_base=base_override,
                explicit_base=explicit,
            )
        except Exception:
            return None
        return None if endpoints is None else endpoints[0]

    def _update_footer(self: Any) -> None:
        _available, pinned, history_state = self._history_chrome_state()
        time_verbs = None
        if isinstance(history_state, dict):
            raw_verbs = history_state.get("time_verbs")
            if isinstance(raw_verbs, list):
                time_verbs = raw_verbs
        split = bool(getattr(self, "_pane_framed", False))
        legend = footer_legend(
            section_total=len(self.document.sections),
            label_count=self._visible_label_count(),
            pending_prefix=self._label_pending_prefix,
            pending_action=self._pending_action,
            trail_back_count=len(self._back_trail),
            trail_forward_count=len(self._forward_trail),
            status=self._footer_status,
            history_pinned=pinned,
            time_verbs=time_verbs,
            split=split,
        )
        # The footer is host-owned: only the focused view may paint it.
        self.pager_host.paint_footer(self, legend)

    def _update_subject(self: Any) -> None:
        scroll = self._body_scroll()
        total = len(self.document.sections)
        width = max(scroll.size.width, 1)
        subject_widget = self.query_one("#pager-subject", Static)
        framed = bool(getattr(self, "_pane_framed", False))
        focused = bool(getattr(self, "_pane_focused", True))
        if total == 0:
            if framed:
                self._apply_framed_chrome(
                    Text(self.document.title, style="bold"),
                    Text("", style="dim"),
                    kind="",
                    focused=focused,
                )
                try:
                    subject_widget.add_class("hidden")
                    self.query_one("#pager-chrome-rule", Static).add_class("hidden")
                except Exception:
                    pass
            else:
                subject_widget.update(Text(self.document.title, style="bold"))
            return

        offsets = self._body.section_offsets if self._body is not None else (0,)
        index = current_section_index(offsets, int(scroll.scroll_y))
        section = self.document.sections[index]
        composed = 0 if self._body is None else self._body.total_height
        fits = composed <= max(int(scroll.size.height), 1)
        percent = (
            100
            if fits or scroll.max_scroll_y <= 0
            else min(100, round(scroll.scroll_y / scroll.max_scroll_y * 100))
        )
        char_count = sum(len(part.plain_text) for part in self.document.sections)
        _, _, history_state = self._history_chrome_state()
        if framed:
            try:
                pane_width = max(int(self.size.width) - 2, 1)
            except Exception:
                pane_width = width
            left, right = subject_parts(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=max(pane_width, width),
                syntax_hint=self._current_syntax_hint(),
                history_state=history_state,
                history_styles=self._history_styles(),
            )
            if not focused:
                left = left.copy()
                left.stylize("dim")
                right = right.copy()
                right.stylize("dim")
            self._apply_framed_chrome(left, right, kind=section.kind, focused=focused)
            try:
                subject_widget.add_class("hidden")
                self.query_one("#pager-chrome-rule", Static).add_class("hidden")
            except Exception:
                pass
            return
        # Single-pane chrome: clear any framed border and show the rows.
        try:
            if getattr(self, "_chrome_signature", None) is not None:
                self._chrome_signature = None  # type: ignore[assignment]
                self.border_title = ""  # type: ignore[assignment]
                self.border_subtitle = ""  # type: ignore[assignment]
                try:
                    self.styles.border = ("none", "transparent")
                except Exception:
                    pass
            subject_widget.remove_class("hidden")
            self.query_one("#pager-chrome-rule", Static).remove_class("hidden")
        except Exception:
            pass
        subject_widget.update(
            subject_line(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=width,
                syntax_hint=self._current_syntax_hint(),
                history_state=history_state,
                history_styles=self._history_styles(),
            )
        )

    def _apply_framed_chrome(
        self: Any, left: Text, right: Text, *, kind: str, focused: bool
    ) -> None:
        """Paint the pane frame border and title/subtitle when split."""
        accent = section_accent(kind or "")
        if focused:
            border_color: object = accent
        else:
            try:
                from textual.color import Color

                border_color = Color.parse(accent).with_alpha(0.35)
            except Exception:
                border_color = accent
        signature = (
            str(border_color),
            left.plain,
            tuple((span.start, span.end, span.style) for span in left.spans),
            right.plain,
            focused,
        )
        if getattr(self, "_chrome_signature", None) == signature:
            return
        self._chrome_signature = signature  # type: ignore[assignment]
        try:
            self.styles.border = ("round", border_color)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            self.border_title = left  # type: ignore[assignment]
        except Exception:
            pass
        try:
            self.border_subtitle = right  # type: ignore[assignment]
        except Exception:
            pass


__all__ = ["PagerChromeMixin"]
