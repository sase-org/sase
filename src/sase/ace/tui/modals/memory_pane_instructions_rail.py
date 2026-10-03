"""INSTRUCTIONS rail group loads and rendered now-bodies (phase instructions-group).

Worker-backed half of
:mod:`sase.ace.tui.modals.memory_pane_instructions`: the collapsed
group's off-thread subject loads plus the off-thread rendered-file
bodies behind :class:`MemoryPane`. Pure row/card builders live in the
sibling module; history presentation still comes only through
``sase.pager.history_kit``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.worker import Worker, WorkerState

from .memory_pane_instructions import (
    INSTRUCTIONS_GROUP_IDENTITY,
    INSTRUCTION_BODY_LOADING,
    INSTRUCTION_BODY_UNAVAILABLE,
    InstructionSubject,
    build_instruction_row_text,
    build_instructions_group_text,
    instruction_group_node,
    instruction_node,
    instruction_subjects,
    is_instruction_group_row,
    is_instruction_subject_row,
    matches_instruction_filter,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneInstructionsMixin(_MixinBase):
    """Collapsed INSTRUCTIONS group plus instruction now-bodies."""

    if TYPE_CHECKING:
        _accent: str
        _closed: bool
        _current_note: str | None
        _expanded_instructions: bool
        _filter_bodies: bool
        _filter_text: str
        _instruction_bodies: dict[tuple[str, str], str]
        _instruction_body_failed: set[tuple[str, str]]
        _instruction_body_request: tuple[str, str] | None
        _instruction_body_worker: Worker[Any] | None
        _instruction_generation: int
        _instruction_order: tuple[str, ...]
        _instruction_scope_key: str | None
        _instruction_subjects: dict[str, InstructionSubject]
        _instruction_worker: Worker[Any] | None
        _lens: Any
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _snapshot: Any
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _apply_filter(
            self,
            pattern: str,
            *,
            include_bodies: bool,
            preferred_note: str | None = None,
        ) -> None: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _lens_name(self) -> Any: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _update_header(self) -> None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- subject lookup -------------------------------------------------

    def _instruction_subject_for_node(self, node: Any) -> InstructionSubject | None:
        """Return the cached subject for an instruction row, if any."""
        try:
            subject_id = str(getattr(node, "instruction_subject", "") or "")
        except Exception:
            return None
        if not subject_id:
            return None
        try:
            return self._instruction_subjects.get(subject_id)
        except Exception:
            return None

    # --- rail hooks (state-mixin defaults overridden through the MRO) ---

    def _instruction_filter_matches(self, pattern: str) -> tuple[Any, ...]:
        """Return INSTRUCTIONS rows matching *pattern* (by path)."""
        try:
            ordered = tuple(self._instruction_order)
            subjects = self._instruction_subjects
        except Exception:
            return ()
        if not ordered:
            return ()
        try:
            matched = [
                subjects[key]
                for key in ordered
                if key in subjects
                and matches_instruction_filter(subjects[key], pattern)
            ]
        except Exception:
            return ()
        if pattern and not matched:
            return ()
        rows: list[Any] = [instruction_group_node()]
        try:
            expanded = bool(self._expanded_instructions)
        except Exception:
            expanded = False
        if expanded or (pattern and matched):
            rows.extend(instruction_node(subject) for subject in matched)
        return tuple(rows)

    def _history_only_option(self, node: Any) -> Any | None:
        """Return the rail option for INSTRUCTIONS rows; else super()."""
        if is_instruction_group_row(node):
            try:
                from textual.widgets.option_list import Option  # noqa: PLC0415

                try:
                    count = len(self._instruction_order)
                except Exception:
                    count = 0
                try:
                    expanded = bool(self._expanded_instructions)
                except Exception:
                    expanded = False
                return Option(
                    build_instructions_group_text(expanded, count),
                    id=INSTRUCTIONS_GROUP_IDENTITY,
                )
            except Exception:
                return None
        if is_instruction_subject_row(node):
            try:
                from textual.widgets.option_list import Option  # noqa: PLC0415

                subject = self._instruction_subject_for_node(node)
                if subject is not None:
                    prompt = build_instruction_row_text(subject)
                else:
                    try:
                        fallback = str(
                            getattr(getattr(node, "note", None), "relative_path", "")
                            or "AGENTS.md"
                        )
                    except Exception:
                        fallback = "AGENTS.md"
                    prompt = Text(f"● {fallback}")
                try:
                    identity = str(node.identity)
                except Exception:
                    identity = fallback
                return Option(prompt, id=identity)
            except Exception:
                return None
        try:
            parent = super()._history_only_option(node)  # type: ignore[misc]
        except Exception:
            parent = None
        return parent

    def _body_preview_for_node(self, node: Any) -> str:
        """Return the rendered file at now for instruction rows."""
        if is_instruction_group_row(node):
            return "Instruction files rendered from memory · space expands the group."
        if is_instruction_subject_row(node):
            try:
                key = self._time_key(node)
            except Exception:
                key = None
            if key is None:
                return INSTRUCTION_BODY_UNAVAILABLE
            try:
                cached = self._instruction_bodies.get(key)
            except Exception:
                cached = None
            if cached is not None:
                return cached if cached.strip() else "_No body content._"
            try:
                failed = key in self._instruction_body_failed
            except Exception:
                failed = False
            if failed:
                return INSTRUCTION_BODY_UNAVAILABLE
            try:
                self._ensure_instruction_body(key, node)
            except Exception:
                pass
            return INSTRUCTION_BODY_LOADING
        try:
            return super()._body_preview_for_node(node)  # type: ignore[misc]
        except Exception:
            return ""

    def action_toggle_web(self) -> None:
        """Toggle the INSTRUCTIONS group on instruction rows (space).

        This mixin leads the MRO for this key so the group toggle is
        reachable; every other row keeps the lens-owned routing
        (inert inside a lens, web expansion in Notes).
        """
        try:
            node = self._selected_row()
        except Exception:
            node = None
        if is_instruction_group_row(node) or is_instruction_subject_row(node):
            try:
                if self._lens_name() != "notes":  # type: ignore[attr-defined]
                    return
            except Exception:
                pass
            try:
                identity = str(getattr(node, "identity", "") or "") or None
            except Exception:
                identity = None
            try:
                self._expanded_instructions = not bool(self._expanded_instructions)
            except Exception:
                return
            try:
                self._apply_filter(
                    self._filter_text,
                    include_bodies=self._filter_bodies,
                    preferred_note=identity,
                )
            except Exception:
                pass
            return
        try:
            super().action_toggle_web()  # type: ignore[misc]
        except Exception:
            pass

    # --- scope lifecycle --------------------------------------------------

    def _apply_snapshot(self, snapshot: Any, *, preferred_note: str | None) -> None:
        """Apply the scope snapshot, then rebuild the group off-thread."""
        try:
            scope_key = str(getattr(getattr(snapshot, "scope", None), "key", ""))
        except Exception:
            scope_key = ""
        try:
            if scope_key != self._instruction_scope_key:
                self._instruction_scope_key = scope_key
                self._expanded_instructions = False
                self._instruction_bodies = {}
                self._instruction_body_failed = set()
        except Exception:
            pass
        try:
            super()._apply_snapshot(snapshot, preferred_note=preferred_note)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._start_instructions_load()
        except Exception:
            pass

    def _start_instructions_load(self) -> None:
        """Build the instruction subjects in a thread worker."""
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
        self._instruction_generation = (
            int(getattr(self, "_instruction_generation", 0) or 0) + 1
        )
        generation = self._instruction_generation
        worker = getattr(self, "_instruction_worker", None)
        try:
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass

        def task() -> tuple[str, tuple[InstructionSubject, ...], str | None, int]:
            try:
                subjects = history.subjects(scope)
            except Exception as exc:
                return (scope_key, (), f"subjects: {exc}", generation)
            try:
                found = instruction_subjects(subjects)
            except Exception as exc:
                return (scope_key, (), f"subjects: {exc}", generation)
            return (scope_key, found, None, generation)

        try:
            self._instruction_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-instructions",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _on_instructions_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply landed subjects only when still current (fail-open)."""
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 4:
            return
        scope_key, found, error, generation = result
        try:
            if int(generation) != int(getattr(self, "_instruction_generation", 0) or 0):
                return
            current_key = self._ring[self._scope_index].key
            if str(current_key) != str(scope_key):
                return
        except Exception:
            return
        if self._closed or not self.is_mounted:
            return
        if error is not None or not isinstance(found, tuple):
            return
        try:
            self._instruction_subjects = {
                subject.subject_id: subject for subject in found
            }
            self._instruction_order = tuple(subject.subject_id for subject in found)
        except Exception:
            return
        try:
            if self._lens_name() != "notes":
                return
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

    # --- rendered now-bodies ------------------------------------------------

    def _ensure_instruction_body(self, key: tuple[str, str], node: Any) -> bool:
        """Fetch the rendered file at now off-thread; True when cached."""
        try:
            if key in self._instruction_bodies:
                return True
            if key in self._instruction_body_failed:
                return True
            if self._instruction_body_request == key:
                worker = self._instruction_body_worker
                if worker is not None and not worker.is_finished:
                    return True
        except Exception:
            pass
        try:
            from .memory_panel_history import selector_for_node
        except Exception:
            return False
        try:
            selector = selector_for_node(node)
        except Exception:
            return False
        if not selector:
            return False
        history = self._ace_history()
        if history is None:
            return False
        try:
            ring = self._ring
            ref = ring[self._scope_index]
            scope = history.scope_for_ref(ref)
        except Exception:
            return False
        if scope is None or str(getattr(ref, "key", "") or "") != key[0]:
            return False
        self._instruction_body_request = key
        worker = getattr(self, "_instruction_body_worker", None)
        try:
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass
        generation = int(getattr(self, "_instruction_generation", 0) or 0)

        def task() -> tuple[str, str, str | None, int]:
            try:
                wire = history.version_body(scope, selector, "now")
            except Exception:
                return (key[0], key[1], None, generation)
            try:
                body = wire.get("body", "") if isinstance(wire, dict) else ""
                text = str(body or "")
            except Exception:
                return (key[0], key[1], None, generation)
            return (key[0], key[1], text, generation)

        try:
            self._instruction_body_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-instruction-body",
                exit_on_error=False,
            )
        except Exception:
            return False
        return False

    def _on_instruction_body_state_changed(self, event: Worker.StateChanged) -> None:
        """Paint a landed now-body when its row is still selected."""
        if event.state != WorkerState.SUCCESS:
            if event.state != WorkerState.CANCELLED:
                try:
                    request = self._instruction_body_request
                    if request is not None:
                        self._instruction_body_failed.add(request)
                except Exception:
                    pass
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 4:
            return
        scope_key, selector, body, generation = result
        key = (str(scope_key), str(selector))
        try:
            self._instruction_body_request = None
        except Exception:
            pass
        try:
            if int(generation) != int(getattr(self, "_instruction_generation", 0) or 0):
                return
        except Exception:
            return
        if self._closed or not self.is_mounted:
            return
        if not isinstance(body, str):
            try:
                self._instruction_body_failed.add(key)
            except Exception:
                pass
            return
        try:
            self._instruction_bodies[key] = body
        except Exception:
            return
        try:
            current = self._time_key(self._selected_row())
        except Exception:
            current = None
        if current != key:
            return
        try:
            self._render_note_card()
        except Exception:
            pass


__all__ = ["MemoryPaneInstructionsMixin"]
