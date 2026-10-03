"""Rail recency glance and deleted subjects (phase rail-glance).

Owns the phase rail-glance Notes rail behind :class:`MemoryPane`
(epic design ``plan:202610/memory_history_tui.md`` §14 and §4.6): a
right-aligned newest-change glyph and age on every Notes rail row,
built off-thread from one ``subjects()`` plus one ``feed()`` per
scope load, and a ``D`` toggle listing tombstoned subjects in a
trailing ``DELETED`` group with read-only tombstone cards.

History presentation comes only through ``sase.pager.history_kit``
(the import-guard door). Feed iteration is defensive: a malformed
feed omits the column and keeps the rail (§5.4 rule 4).
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.memory_panel_catalog import MemoryRailNode
from sase.memory.notes import AGENTS_PARENT, MemoryNote

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Style for DELETED rail rows (the tombstone role is red in the kit).
_DELETED_ROW_STYLE = "red"

#: Classes whose glance glyph keeps a bold highlight (promotions only).
_PROMOTION_CLASSES = frozenset({"promoted", "demoted"})


@dataclass(frozen=True)
class DeletedSubject:
    """One subject whose latest feed entry is a deletion."""

    subject_id: str
    path: str
    display: str
    committer_time: int
    ordinal: int
    commit: str


def _feed_changesets(feed: Any) -> tuple[dict[str, Any], ...]:
    """Return the feed's changesets, newest first, or ``()`` when malformed."""
    if not isinstance(feed, dict):
        return ()
    changesets = feed.get("changesets", ())
    if not isinstance(changesets, (list, tuple)):
        return ()
    return tuple(row for row in changesets if isinstance(row, dict))


def _feed_entries(changeset: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one changeset's authored plus consequence entries."""
    entries: list[dict[str, Any]] = []
    for key in ("authored", "consequences"):
        rows = changeset.get(key, ())
        if isinstance(rows, (list, tuple)):
            entries.extend(row for row in rows if isinstance(row, dict))
    return tuple(entries)


def _entry_time(changeset: dict[str, Any]) -> int | None:
    """Return one changeset's committer time, or ``None`` when unusable."""
    try:
        moment = int(changeset.get("committer_time", 0) or 0)
    except (TypeError, ValueError):
        return None
    return moment if moment > 0 else None


def build_recency_map(feed: Any) -> dict[str, tuple[str, int]]:
    """Return ``{path: (class, committer_time)}`` for the newest entry.

    The feed arrives newest first, so the first entry seen per path
    wins. Entries without a path or a usable time are skipped. Notes,
    web descriptors, and strands all match by file path, which is what
    the rail rows carry. Never raises: a malformed feed yields ``{}``,
    omitting the column while the rail keeps working.
    """
    recency: dict[str, tuple[str, int]] = {}
    try:
        for changeset in _feed_changesets(feed):
            moment = _entry_time(changeset)
            if moment is None:
                continue
            for entry in _feed_entries(changeset):
                path = entry.get("path", "")
                if not isinstance(path, str) or not path or path in recency:
                    continue
                class_name = entry.get("class", "")
                if not isinstance(class_name, str) or not class_name:
                    continue
                recency[path] = (class_name, moment)
    except Exception:
        return {}
    return recency


def subject_displays(subjects: Any) -> dict[str, str]:
    """Return ``{subject_id: display_name}`` from a subjects wire dict."""
    displays: dict[str, str] = {}
    try:
        rows = subjects.get("subjects", ()) if isinstance(subjects, dict) else ()
    except Exception:
        return {}
    if not isinstance(rows, (list, tuple)):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        subject_id = row.get("id", "")
        display = row.get("display_name", "")
        if isinstance(subject_id, str) and subject_id and isinstance(display, str):
            if display:
                displays[subject_id] = display
    return displays


def _display_for_entry(
    subject_id: str, path: str, displays: dict[str, str] | None
) -> str:
    """Return the DELETED row name for one deleted feed entry."""
    if displays is not None:
        try:
            display = displays.get(subject_id, "")
            if display:
                return str(display)
        except Exception:
            pass
    try:
        return Path(path).stem or path
    except Exception:
        return path


def deleted_subjects(
    feed: Any, *, displays: dict[str, str] | None = None
) -> tuple[DeletedSubject, ...]:
    """Return subjects whose latest entry is a deletion, newest first.

    The feed arrives newest first, so the first entry seen per
    subject id is its latest: a subject deleted and later recreated
    is never listed. Never raises.
    """
    latest: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for changeset in _feed_changesets(feed):
            moment = _entry_time(changeset)
            if moment is None:
                continue
            for entry in _feed_entries(changeset):
                subject_id = entry.get("subject_id", "")
                if not isinstance(subject_id, str) or not subject_id:
                    continue
                if subject_id not in latest:
                    latest[subject_id] = (changeset, entry)
    except Exception:
        return ()
    deleted: list[DeletedSubject] = []
    for subject_id, (changeset, entry) in latest.items():
        try:
            if entry.get("class") != "deleted":
                continue
            path = entry.get("path", "")
            if not isinstance(path, str) or not path:
                continue
            moment = _entry_time(changeset)
            if moment is None:
                continue
            try:
                ordinal = int(entry.get("ordinal", 0) or 0)
            except (TypeError, ValueError):
                ordinal = 0
            commit = entry.get("commit", changeset.get("commit", ""))
            deleted.append(
                DeletedSubject(
                    subject_id=subject_id,
                    path=path,
                    display=_display_for_entry(subject_id, path, displays),
                    committer_time=moment,
                    ordinal=ordinal,
                    commit=str(commit) if isinstance(commit, str) else "",
                )
            )
        except Exception:
            continue
    return tuple(deleted)


def glance_suffix(class_name: str, committer_time: int, *, now_epoch: int = 0) -> str:
    """Return the ``glyph age`` suffix (``⇧ 8d``) for one newest change."""
    try:
        from sase.pager.history_kit import format_age, glyph_for
    except Exception:
        return ""
    try:
        now = int(now_epoch) if now_epoch else int(_time.time())
        age = format_age(int(now), int(committer_time))
        glyph = glyph_for(str(class_name))
    except Exception:
        return ""
    if not age or not glyph:
        return ""
    return f"{glyph} {age}"


def glance_glyph_only(class_name: str) -> str:
    """Return just the vocabulary glyph for a change class."""
    try:
        from sase.pager.history_kit import glyph_for

        return str(glyph_for(str(class_name)) or "")
    except Exception:
        return ""


def node_glance_path(node: Any) -> str:
    """Return the feed path a rail row matches on (strands: strand file)."""
    try:
        strand = getattr(node, "strand", None)
        if strand is not None:
            relative = getattr(strand, "relative_path", "") or ""
            if relative:
                return str(relative)
        note = getattr(node, "note", None)
        if note is not None:
            return str(getattr(note, "relative_path", "") or "")
    except Exception:
        pass
    return ""


def deleted_age_text(committer_time: int, *, now_epoch: int = 0) -> str:
    """Return the compact age for a DELETED row (``3w``)."""
    try:
        from sase.pager.history_kit import format_age
    except Exception:
        return ""
    try:
        now = int(now_epoch) if now_epoch else int(_time.time())
        return str(format_age(int(now), int(committer_time)) or "")
    except Exception:
        return ""


def build_deleted_row_text(
    display: str, committer_time: int, *, now_epoch: int = 0
) -> Text:
    """Return one DELETED rail row: ``✖ name   deleted 3w``.

    Pure: the deleted style is fixed here so every caller paints the
    group identically. Never raises.
    """
    try:
        age = deleted_age_text(int(committer_time), now_epoch=int(now_epoch))
    except Exception:
        age = ""
    text = Text(style=_DELETED_ROW_STYLE)
    try:
        text.append(f"✖ {display}")
        text.append("   deleted")
        if age:
            text.append(f" {age}")
    except Exception:
        return Text(f"✖ {display}", style=_DELETED_ROW_STYLE)
    return text


def history_only_node(subject: DeletedSubject) -> MemoryRailNode:
    """Return the history-only rail node for one deleted subject.

    The synthetic note carries the deleted path so history selectors,
    filters, and pins resolve exactly like a live row; ``history_only``
    marks the kind so note-only paths skip or refuse it. Never raises.
    """
    note = MemoryNote(
        path=Path(subject.path),
        type="reference",
        parent=AGENTS_PARENT,
        description=None,
        body="",
        frontmatter={},
        type_source="missing",
        parent_source="missing",
        source_path=Path(subject.path),
    )
    return MemoryRailNode(
        note=note,
        depth=0,
        history_only=True,
        deleted_ordinal=int(subject.ordinal),
    )


def is_promotion_class(class_name: str) -> bool:
    """Return whether a glance class keeps its highlight (``⇧``/``⇩``)."""
    try:
        return str(class_name) in _PROMOTION_CLASSES
    except Exception:
        return False


#: Toast when ``D`` finds no deleted subjects to list.
_NO_DELETED_TOAST = "no deleted subjects in this scope"

#: Toast when a mutation or source key hits a history-only row.
_HISTORY_ONLY_REFUSAL = "deleted subjects are read-only"


def history_only_refusal() -> str:
    """Return the toast for mutation/source keys on history-only rows."""
    return _HISTORY_ONLY_REFUSAL


class MemoryPaneRailGlanceMixin(_MixinBase):
    """Recency glance loads, the ``D`` DELETED toggle, tombstone pins."""

    if TYPE_CHECKING:
        _closed: bool
        _current_note: str | None
        _deleted_subjects: tuple[DeletedSubject, ...]
        _filter_bodies: bool
        _filter_text: str
        _glance_failed: bool
        _glance_generation: int
        _glance_map: dict[str, tuple[str, int]]
        _glance_worker: Worker[tuple[str, dict, tuple, str | None, int]] | None
        _keymaps: Any
        _lens: Any
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _show_deleted: bool
        _time_pins: dict[tuple[str, str], int]
        _time_request: Any | None
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _apply_filter(
            self, pattern: str, *, include_bodies: bool, preferred_note: str | None
        ) -> None: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _ensure_time_body(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> bool: ...
        def _history_key_for_node(self, node: Any | None) -> Any | None: ...
        def _lens_name(self) -> Any: ...
        def _resize_note_rail(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- hooks overriding the state-mixin defaults ----------------------

    def _note_row_glance(self, node: Any) -> tuple[str, str, bool]:
        """Return ``(full, glyph, promoted)`` for one rail row, or blanks."""
        try:
            path = node_glance_path(node)
        except Exception:
            return ("", "", False)
        if not path:
            return ("", "", False)
        try:
            hit = self._glance_map.get(path)
        except Exception:
            return ("", "", False)
        if hit is None:
            return ("", "", False)
        class_name, moment = hit
        try:
            full = glance_suffix(str(class_name), int(moment))
        except Exception:
            return ("", "", False)
        if not full:
            return ("", "", False)
        return (
            full,
            glance_glyph_only(str(class_name)),
            is_promotion_class(class_name),
        )

    def _glance_column_width(self) -> int:
        """Return the widest full glance suffix (0 omits the column)."""
        try:
            entries = list(self._glance_map.values())
        except Exception:
            return 0
        if not entries:
            return 0
        try:
            import time as _now

            now_epoch = int(_now.time())
            widest = 0
            for class_name, moment in entries:
                suffix = glance_suffix(
                    str(class_name), int(moment), now_epoch=now_epoch
                )
                widest = max(widest, Text(suffix).cell_len if suffix else 0)
            return int(widest)
        except Exception:
            return 0

    def _deleted_filter_matches(self, pattern: str) -> tuple[MemoryRailNode, ...]:
        """Return DELETED rows matching *pattern* (by path), in feed order."""
        if not self._show_deleted:
            return ()
        try:
            subjects = tuple(self._deleted_subjects)
        except Exception:
            return ()
        if not subjects:
            return ()
        needle = str(pattern or "").strip().casefold()
        rows: list[MemoryRailNode] = []
        for subject in subjects:
            try:
                if needle and needle not in str(subject.path).casefold():
                    continue
                rows.append(history_only_node(subject))
            except Exception:
                continue
        return tuple(rows)

    def _deleted_header_count(self) -> int:
        """Return the header's ``N deleted`` count (0 hides the chip)."""
        try:
            if not self._show_deleted:
                return 0
            return len(self._deleted_subjects)
        except Exception:
            return 0

    def _history_only_option(self, node: Any) -> Any | None:
        """Return the ``✖ name   deleted 3w`` option for a DELETED row."""
        try:
            path = str(getattr(getattr(node, "note", None), "relative_path", "") or "")
            identity = str(getattr(node, "identity", "") or path)
        except Exception:
            return None
        if not path:
            return None
        display = ""
        moment = 0
        try:
            for subject in tuple(self._deleted_subjects):
                if str(subject.path) == path:
                    display = str(subject.display or "")
                    moment = int(subject.committer_time or 0)
                    break
        except Exception:
            pass
        if not display:
            try:
                display = Path(path).stem or path
            except Exception:
                display = path
        try:
            from textual.widgets.option_list import Option  # noqa: PLC0415

            return Option(
                build_deleted_row_text(display, int(moment or 0)), id=identity
            )
        except Exception:
            return None

    # --- scope lifecycle --------------------------------------------------

    def _apply_snapshot(self, snapshot: Any, *, preferred_note: str | None) -> None:
        """Apply the scope snapshot, then rebuild the glance off-thread."""
        try:
            super()._apply_snapshot(snapshot, preferred_note=preferred_note)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._start_glance_load()
        except Exception:
            pass

    def _start_glance_load(self) -> None:
        """Build the recency map plus DELETED list in a thread worker."""
        try:
            ring = self._ring
            scope_index = int(self._scope_index)
            ref = ring[scope_index]
            scope_key = str(getattr(ref, "key", "") or "")
        except Exception:
            return
        if not scope_key:
            return
        history = self._ace_history()
        if history is None:
            return
        try:
            scope = history.scope_for_ref(ref)
        except Exception:
            return
        if scope is None:
            return
        self._glance_generation = int(getattr(self, "_glance_generation", 0) or 0) + 1
        generation = self._glance_generation
        worker = getattr(self, "_glance_worker", None)
        try:
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass

        def task() -> tuple[str, dict, tuple, str | None, int]:
            try:
                subjects = history.subjects(scope)
            except Exception as exc:
                return (scope_key, {}, (), f"subjects: {exc}", generation)
            try:
                feed = history.feed([scope])
            except Exception as exc:
                return (scope_key, {}, (), f"feed: {exc}", generation)
            try:
                recency = build_recency_map(feed)
                deleted = deleted_subjects(feed, displays=subject_displays(subjects))
            except Exception as exc:
                return (scope_key, {}, (), f"map: {exc}", generation)
            return (scope_key, recency, deleted, None, generation)

        try:
            self._glance_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-glance",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _on_glance_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply a landed glance map only when it is still current."""
        if event.state != WorkerState.SUCCESS:
            if event.state == WorkerState.CANCELLED:
                return
            # Fail-open: omit the column and keep the rail (§5.4 rule 4).
            try:
                self._glance_failed = True
            except Exception:
                pass
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 5:
            return
        scope_key, recency, deleted, error, generation = result
        try:
            if int(generation) != int(getattr(self, "_glance_generation", 0) or 0):
                return  # Stale: a newer scope load already won.
            current_key = self._ring[self._scope_index].key
            if str(current_key) != str(scope_key):
                return
        except Exception:
            return
        if self._closed or not self.is_mounted:
            return
        if error is not None or not isinstance(recency, dict):
            try:
                self._glance_failed = True
            except Exception:
                pass
            return
        try:
            self._glance_map = dict(recency)
            self._deleted_subjects = tuple(deleted)
            self._glance_failed = False
            if not self._deleted_subjects:
                self._show_deleted = False
        except Exception:
            return
        # Rows paint first and gain the column when the map lands; the
        # rail width is recomputed once here. Inside a lens the Notes
        # rail stays frozen.
        try:
            if self._lens_name() != "notes":
                return
        except Exception:
            pass
        try:
            self._resize_note_rail()
        except Exception:
            pass
        try:
            self._apply_filter(
                self._filter_text,
                include_bodies=self._filter_bodies,
                preferred_note=self._current_note,
            )
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass
        try:
            self._update_footer()
        except Exception:
            pass

    # --- D toggle ---------------------------------------------------------

    def action_toggle_deleted(self) -> None:
        """Toggle the trailing DELETED group of tombstoned subjects."""
        try:
            if self._lens_name() != "notes":
                return  # Lenses own the rail while open.
        except Exception:
            pass
        if self._loading:
            return
        try:
            if self._show_deleted:
                self._show_deleted = False
            else:
                if not self._deleted_subjects:
                    self.notify(_NO_DELETED_TOAST)
                    return
                self._show_deleted = True
        except Exception:
            return
        try:
            self._resize_note_rail()
        except Exception:
            pass
        try:
            self._apply_filter(
                self._filter_text,
                include_bodies=self._filter_bodies,
                preferred_note=self._current_note,
            )
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass
        try:
            self._update_footer()
        except Exception:
            pass

    # --- tombstone cards ----------------------------------------------------

    def _is_history_only(self, node: Any | None) -> bool:
        """Return whether *node* is a history-only (deleted) row."""
        try:
            return bool(node is not None and getattr(node, "history_only", False))
        except Exception:
            return False

    def _ensure_tombstone_state(self, node: Any | None) -> None:
        """Pin a history-only row to its deletion so the card is a tombstone.

        The existing past-card machinery then renders the ``✖ DELETED``
        pill, the deleted frame, the tombstone strip row, and the last
        content; ``(``/``{`` step older and ``@``/``H`` keep working.
        Idempotent: cached pins and bodies short-circuit. Never raises.
        """
        if not self._is_history_only(node):
            return
        try:
            ordinal = int(getattr(node, "deleted_ordinal", 0) or 0)
        except (TypeError, ValueError):
            return
        if ordinal <= 0:
            return
        try:
            key = self._time_key(node)
        except Exception:
            return
        if key is None:
            return
        try:
            if self._time_pinned_ordinal(node) <= 0:
                self._time_pins[key] = int(ordinal)
        except Exception:
            pass
        try:
            if self._time_applied_ordinal(node) > 0:
                return
        except Exception:
            pass
        try:
            pending = getattr(self, "_time_request", None)
            if (
                isinstance(pending, tuple)
                and len(pending) == 4
                and pending[0] == key[0]
                and pending[1] == key[1]
                and int(pending[2]) == int(ordinal)
            ):
                return
        except Exception:
            pass
        try:
            timeline = self._time_timeline(node)
        except Exception:
            timeline = None
        if timeline is None:
            try:
                self._ensure_history_load(key[0], key[1])
            except Exception:
                pass
            return
        try:
            self._ensure_time_body(key, node, int(ordinal))
        except Exception:
            pass

    def _set_rows(self, nodes: Any, *, preferred_note: str | None) -> None:
        """Apply rail rows, then pin a selected tombstone to its deletion.

        The Timeline lens re-skins ``_render_note_card`` outside the
        MRO chain, so tombstone pins hook the selection paths (which
        always repaint the card) instead of the render itself.
        """
        try:
            super()._set_rows(nodes, preferred_note=preferred_note)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Pin a newly highlighted tombstone (Notes rail only)."""
        # Textual dispatches ``on_*`` along the whole MRO, so this also
        # fires inside the lenses, where the Notes selection is frozen.
        try:
            if self._lens_name() != "notes":  # type: ignore[attr-defined]
                return
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass

    def _after_history_landed(self, scope_key: str, selector: str) -> None:
        """Resolve the pin, then ensure a tombstone body when selected."""
        try:
            super()._after_history_landed(scope_key, selector)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass


__all__ = [
    "DeletedSubject",
    "MemoryPaneRailGlanceMixin",
    "build_deleted_row_text",
    "build_recency_map",
    "deleted_age_text",
    "deleted_subjects",
    "glance_glyph_only",
    "glance_suffix",
    "history_only_node",
    "history_only_refusal",
    "is_promotion_class",
    "node_glance_path",
    "subject_displays",
]
