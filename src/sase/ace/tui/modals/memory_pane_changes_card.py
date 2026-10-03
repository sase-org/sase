"""Changeset card rendering for the Changes lens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text

from .memory_pane_diff import CARD_FOLD_VERB

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


def _changes_provenance_text(view: Any) -> str:
    """Return the ``◈ bead ⬡ agent ◉ commit`` provenance chips for a card."""
    bits: list[str] = []
    try:
        bead = str(getattr(view, "bead", "") or "")
        agent = str(getattr(view, "agent", "") or "")
        commit = str(getattr(view, "commit", "") or "")
    except Exception:
        return ""
    if bead:
        bits.append(f"◈ {bead}")
    if agent:
        bits.append(f"⬡ {agent}")
    if commit:
        bits.append(f"◉ {commit[:7]}")
    return "   ".join(bits)


def _changes_totals_text(view: Any) -> str:
    """Return the ``3 subjects · +200w −3w · ⟳ 3 regenerated`` totals line."""
    try:
        count = len(getattr(view, "authored", ()) or ())
    except Exception:
        count = 0
    try:
        delta = str(getattr(view, "word_delta", "") or "")
    except Exception:
        delta = ""
    try:
        regen = len(getattr(view, "consequences", ()) or ())
    except Exception:
        regen = 0
    noun = "subject" if count == 1 else "subjects"
    parts = [f"{count} {noun}"]
    if delta:
        parts.append(delta)
    if regen:
        parts.append(f"⟳ {regen} regenerated")
    return " · ".join(parts)


def _changes_section_title(index: int, subject: Any) -> str:
    """Return the ``.1 ◆ display · meaning`` title for one card section."""
    try:
        glyph = str(getattr(subject, "glyph", "") or "◆")
        display = str(getattr(subject, "display", "") or "")
        meaning = str(getattr(subject, "meaning", "") or "")
    except Exception:
        return f".{index}"
    title = f".{index} {glyph} {display}".rstrip()
    if meaning:
        title += f" · {meaning}"
    words = ""
    try:
        words = str(getattr(subject, "words", "") or "")
    except Exception:
        words = ""
    if words:
        title += f"  {words}"
    return title


class MemoryPaneChangesCardMixin(_MixinBase):
    """Render the cursor changeset card with progressive subject sections."""

    if TYPE_CHECKING:
        _changes_all_scopes: bool
        _changes_cursor: int
        _changes_failed: tuple[str, ...]
        _changes_feed: dict[str, Any] | None
        _changes_filter: str
        _changes_generation: int
        _changes_limit: int
        _changes_listed: tuple[dict[str, Any], ...]
        _changes_loading: bool
        _changes_mark_worker: Any | None
        _changes_older: int
        _changes_review: tuple[Any, ...]
        _changes_scheduled: int
        _changes_scope_label: str
        _changes_sections: dict[tuple[str, str, str], str]
        _changes_section_failed: set[tuple[str, str, str]]
        _changes_total: int
        _changes_worker: Any | None
        _current_note: str | None
        _debouncer: Any | None
        _filter_text: str
        _lens: Any
        _lens_snapshot: Any | None
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _selection_guard: Any
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _changes_cursor_row(self) -> dict[str, Any] | None: ...
        def _changes_cursor_view(self) -> Any | None: ...
        def _lens_is_changes(self) -> bool: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- card ---------------------------------------------------------------

    def _render_note_card(self) -> None:
        """Render the changeset card in the lens; Notes otherwise."""
        if not self._lens_is_changes():
            try:
                super()._render_note_card()  # type: ignore[misc]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415
        except Exception:
            return
        view = self._changes_cursor_view()
        try:
            title_widget = self.query_one("#memory-panel-card-title", Static)
            strip_widget = self.query_one("#memory-panel-time-strip", Static)
            description_widget = self.query_one(
                "#memory-panel-card-description", Static
            )
            meta_widget = self.query_one("#memory-panel-card-meta", Static)
        except Exception:
            return
        try:
            from textual.widgets import Markdown as _Markdown  # noqa: PLC0415

            body_widget: Any | None = self.query_one(
                "#memory-panel-card-body", _Markdown
            )
        except Exception:
            body_widget = None
        try:
            diff_widget: Any | None = self.query_one("#memory-panel-card-diff", Static)
        except Exception:
            diff_widget = None
        if view is None:
            row = self._changes_cursor_row()
            kind = str((row or {}).get("kind", "") or "")
            if kind == "more":
                notice = "loading more changesets…"
            elif bool(getattr(self, "_changes_loading", False)):
                notice = "loading changes…"
            else:
                notice = "select a changeset to review it"
            try:
                title_widget.update(Text("Changes", style="bold"))
                strip_widget.update(Text(notice, style="dim"))
                strip_widget.display = True
                description_widget.update("")
                if body_widget is not None:
                    body_widget.update("")
                if diff_widget is not None:
                    diff_widget.display = False
                    diff_widget.update("")
                meta_widget.update("")
            except Exception:
                pass
            return
        try:
            import time as _time  # noqa: PLC0415

            now_epoch = int(_time.time())
        except Exception:
            now_epoch = 0
        try:
            from sase.pager.history_kit import format_age  # noqa: PLC0415
        except Exception:
            format_age = None  # type: ignore[assignment]
        try:
            epoch = int(getattr(view, "committer_time", 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        try:
            import datetime as _dt  # noqa: PLC0415

            absolute = (
                _dt.datetime.fromtimestamp(epoch).strftime("%a %b %d %H:%M")
                if epoch
                else "undated"
            )
        except Exception:
            absolute = "undated"
        try:
            relative = (
                format_age(now_epoch, epoch)
                if (format_age is not None and epoch)
                else ""
            )
        except Exception:
            relative = ""
        try:
            subject = str(getattr(view, "subject_line", "") or "(no subject)")
            scope_key = str(getattr(view, "scope_key", "") or "")
        except Exception:
            subject, scope_key = "(no subject)", ""
        path_line = f"{absolute}"
        if relative:
            path_line += f" · {relative} ago"
        if scope_key:
            path_line += f" · {scope_key}"
        try:
            title_widget.update(Text(subject, style="bold"))
            strip_widget.update(Text(_changes_provenance_text(view) or "·", style=""))
            strip_widget.display = True
            description_widget.update(Text(path_line, style="dim"))
            meta_widget.update(Text(_changes_totals_text(view), style="dim"))
        except Exception:
            pass
        try:
            if diff_widget is not None:
                diff_widget.display = False
                diff_widget.update("")
        except Exception:
            pass
        sections_text = self._changes_sections_text(view)
        try:
            if body_widget is not None:
                body_widget.update(sections_text)
        except Exception:
            pass
        self._changes_ensure_sections(view)

    def _changes_sections_text(self, view: Any) -> str:
        """Return the progressive per-subject card body for a changeset."""
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                MAX_INLINE_SECTIONS,
            )
        except Exception:
            MAX_INLINE_SECTIONS = 6
        try:
            authored = tuple(getattr(view, "authored", ()) or ())
        except Exception:
            authored = ()
        try:
            commit = str(getattr(view, "commit", "") or "")
        except Exception:
            commit = ""
        lines: list[str] = []
        shown = authored[:MAX_INLINE_SECTIONS]
        for position, subject in enumerate(shown, start=1):
            title = _changes_section_title(position, subject)
            lines.append(title)
            try:
                key = (
                    commit,
                    str(getattr(subject, "selector", "") or ""),
                    str(getattr(subject, "revision", "") or ""),
                )
            except Exception:
                key = (commit, "", "")
            sections: dict[tuple[str, str, str], Any] = (
                getattr(self, "_changes_sections", {}) or {}
            )
            failed: set[tuple[str, str, str]] = (
                getattr(self, "_changes_section_failed", set()) or set()
            )
            if key in sections:
                body = str(sections.get(key, "") or "")
                lines.append(body if body else "(empty)")
            elif key in failed:
                lines.append("diff unavailable for this subject")
            else:
                lines.append("loading diff…")
            lines.append("")
        try:
            hidden = max(0, len(authored) - len(shown))
        except Exception:
            hidden = 0
        if hidden:
            lines.append(f"+{hidden} more · .N or ⏎ to open")
            lines.append("")
        try:
            consequences = tuple(getattr(view, "consequences", ()) or ())
        except Exception:
            consequences = ()
        if consequences:
            lines.append(f"⟳ {' · '.join(consequences)}")
        return "\n".join(lines).rstrip() + "\n" if lines else "(no authored subjects)\n"

    def _changes_ensure_sections(self, view: Any) -> None:
        """Fill per-subject diff sections progressively (generation-guarded)."""
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                MAX_INLINE_SECTIONS,
            )
        except Exception:
            MAX_INLINE_SECTIONS = 6
        try:
            authored = tuple(getattr(view, "authored", ()) or ())
        except Exception:
            return
        try:
            commit = str(getattr(view, "commit", "") or "")
            scope_key = str(getattr(view, "scope_key", "") or "")
        except Exception:
            return
        shown = authored[:MAX_INLINE_SECTIONS]
        try:
            generation = int(getattr(self, "_changes_generation", 0) or 0)
        except Exception:
            generation = 0
        try:
            sections: dict[tuple[str, str, str], Any] = (
                getattr(self, "_changes_sections", {}) or {}
            )
            failed: set[tuple[str, str, str]] = (
                getattr(self, "_changes_section_failed", set()) or set()
            )
        except Exception:
            sections, failed = {}, set()
        pending: list[tuple[tuple[str, str, str], Any]] = []
        for subject in shown:
            try:
                key = (
                    commit,
                    str(getattr(subject, "selector", "") or ""),
                    str(getattr(subject, "revision", "") or ""),
                )
            except Exception:
                continue
            if key in sections or key in failed:
                continue
            pending.append((key, subject))
        if not pending:
            return

        async def _fill() -> None:
            import asyncio

            def _query() -> dict[tuple[str, str, str], str]:
                results: dict[tuple[str, str, str], str] = {}
                try:
                    history = self._ace_history()
                except Exception:
                    return results
                if history is None:
                    return results
                try:
                    service = history.service
                except Exception:
                    service = history
                scope = None
                try:
                    from .memory_panel_history import (  # noqa: PLC0415
                        history_scopes_for_ring,
                    )

                    ring = tuple(getattr(self, "_ring", ()) or ())
                    scopes = history_scopes_for_ring(ring, service)
                    for candidate in scopes:
                        if str(getattr(candidate, "scope_key", "")) == scope_key:
                            scope = candidate
                            break
                    if scope is None:
                        scope = (
                            history.scope_for_ref(
                                next(
                                    (
                                        ref
                                        for ref in ring
                                        if str(getattr(ref, "key", "")) == scope_key
                                    ),
                                    None,
                                )
                            )
                            if hasattr(history, "scope_for_ref")
                            else None
                        )
                except Exception:
                    scope = None
                if scope is None:
                    return results
                for key, subject in pending:
                    _commit, selector, revision = key
                    if not selector or not revision:
                        continue
                    try:
                        class_name = str(getattr(subject, "class_name", "") or "")
                    except Exception:
                        class_name = ""
                    if class_name == "deleted":
                        results[key] = "deleted · last content shown"
                        continue
                    try:
                        body_wire = history.version_body(scope, selector, revision)
                    except Exception:
                        continue
                    try:
                        target_body = str(body_wire.get("body", "") or "")
                    except Exception:
                        target_body = ""
                    try:
                        ordinal = int(str(revision).lstrip("v") or 0)
                    except (TypeError, ValueError):
                        ordinal = 0
                    try:
                        if ordinal <= 1:
                            base = "empty"
                        else:
                            base = f"v{ordinal - 1}"
                        comparison = history.comparison(scope, selector, base, revision)
                    except Exception:
                        comparison = None
                    try:
                        if comparison is None:
                            results[key] = (
                                target_body.splitlines()[0]
                                if target_body
                                else "(empty)"
                            )
                            continue
                        from sase.pager.history_kit import (  # noqa: PLC0415
                            build_diff_body,
                        )

                        rendered = build_diff_body(
                            comparison, target_body, fold_verb=CARD_FOLD_VERB
                        )
                        results[key] = rendered.text.plain.strip() or "(no changes)"
                    except Exception:
                        try:
                            results[key] = (
                                target_body.splitlines()[0]
                                if target_body
                                else "(empty)"
                            )
                        except Exception:
                            pass
                return results

            filled = await asyncio.to_thread(_query)
            if not self._lens_is_changes():
                return
            if int(getattr(self, "_changes_generation", 0) or 0) != generation:
                return  # Stale: the cursor moved to another changeset.
            current = self._changes_cursor_view()
            try:
                current_commit = str(getattr(current, "commit", "") or "")
            except Exception:
                current_commit = ""
            if current_commit != commit:
                return  # Stale: a newer changeset won.
            if not isinstance(filled, dict):
                return
            try:
                sections = dict(getattr(self, "_changes_sections", {}) or {})
                sections.update(filled)
                self._changes_sections = sections
                self._render_note_card()
            except Exception:
                pass

        try:
            self.run_worker(
                _fill(),
                exclusive=True,
                group="memory-panel-changes-sections",
                exit_on_error=False,
            )
        except Exception:
            pass


__all__ = [
    "MemoryPaneChangesCardMixin",
    "_changes_provenance_text",
    "_changes_section_title",
    "_changes_totals_text",
]
