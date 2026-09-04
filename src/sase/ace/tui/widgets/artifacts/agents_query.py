"""Inline query session for the Artifacts Agent pane."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import TYPE_CHECKING, Any

from textual.message import Message
from textual.worker import Worker, WorkerState

from sase.ace.query.limit_token import LimitTokenError, apply_limit, extract_limit
from sase.ace.query.profile_reference import canonical_query_for_profile
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.ace.query_profile import (
    CompiledQueryProfile,
    compiled_profile_for_builtin_pane,
)
from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
    evaluate_artifact_query_many,
)
from sase.project_display_names import ProjectRefDisplaySnapshot

from .agents_data import AgentsSnapshot
from .entry_navigation import ArtifactEntryTarget
from .query_rows import agent_query_row_id, build_agents_query_index
from .query_session import ArtifactQuerySession
from .types import ARTIFACTS_ACCENTS

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from .agents_navigation import AgentsOptionList
else:
    _MixinBase = object


_SAVE_QUERY_RE = re.compile(r"^#(\d)?(.*)$")


@dataclass(frozen=True, slots=True)
class _AgentsQueryIndexResult:
    """One completed Agent query-index rebuild."""

    generation: int
    display_generation: int
    query_index: ArtifactQueryIndex


class AgentFilterBar(FilterBar):
    """Persistent Agent catalog query editor driven by the compiled profile."""

    ACCENT = ARTIFACTS_ACCENTS["agents"]
    ROW_ID = "agent-filter-row"
    SIGIL_ID = "agent-filter-sigil"
    INPUT_ID = "agent-filter-input"
    STATUS_ID = "agent-filter-status"
    COMPLETION_ID = "agent-filter-completion"
    CANDIDATE_ID_PREFIX = "agent-filter-candidate"
    DISPLAY_ID = "agent-filter-display"
    PERSISTENT = True

    class QueryChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        pass


class AgentsQueryMixin(_MixinBase):
    """Own Agent filter state, Rust query evaluation, and history hooks."""

    contract: Any
    project_scope: str | None
    query_source: str
    _filter_session_open: bool
    _filter_restore_query: str | None
    _filter_restore_selection: ArtifactEntryTarget | None
    _live_query_source: str | None
    _filter_query_error: ProfileQueryError | None
    _filtered_count: int | None
    _display_count: int | None
    _display_total_count: int | None
    _display_truncated: bool
    _query_profile: CompiledQueryProfile
    _query_session: ArtifactQuerySession
    _query_index: ArtifactQueryIndex | None
    _query_index_worker: Worker[Any] | None
    _project_ref_display: ProjectRefDisplaySnapshot
    _project_ref_display_generation: int
    _load_generation: int

    if TYPE_CHECKING:

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def focus_list(self) -> None: ...

        def _current_snapshot(self) -> AgentsSnapshot | None: ...

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
        ) -> None: ...

        def _request_load(self, *, force: bool, full: bool = False) -> None: ...

    def _init_agents_query(self) -> None:
        from sase.ace.config import get_ace_page_size
        from sase.ace.query.limit_token import ensure_limit

        profile = (
            self.contract.query_profile
            if self.contract is not None
            else compiled_profile_for_builtin_pane("agents")
        )
        assert profile is not None
        self._query_profile = profile
        self.query_source = ensure_limit("", get_ace_page_size())
        self._live_query_source = None
        self._filter_session_open = False
        self._filter_restore_query = None
        self._filter_restore_selection = None
        self._filter_query_error = None
        self._filtered_count = None
        self._display_count = None
        self._display_total_count = None
        self._display_truncated = False
        self._query_index = None
        self._query_index_worker = None
        self._project_ref_display = ProjectRefDisplaySnapshot()
        self._project_ref_display_generation = 0
        self._query_session = ArtifactQuerySession(
            self,
            group="artifacts-agents-query",
            on_current_result=lambda _result: self._refresh_options(
                preferred_target=self.selected_entry_target()
            ),
        )

    def _build_agents_query_index(
        self,
        snapshot: AgentsSnapshot,
        *,
        generation: int,
    ) -> ArtifactQueryIndex:
        return build_agents_query_index(
            snapshot,
            pane_id=self._query_profile.pane_id,
            generation=generation,
            profile=self._query_profile,
            project_ref_display=self._project_ref_display,
        )

    def _initial_agents_query_result(
        self,
        query_index: ArtifactQueryIndex,
    ) -> ArtifactQueryResult | None:
        try:
            remainder, _cap = extract_limit(self.query_source)
        except LimitTokenError:
            return None
        if not remainder.strip():
            return None
        try:
            return evaluate_artifact_query_many(self.query_source, query_index)
        except ProfileQueryError:
            return None

    def _handle_agents_query_worker(self, event: Worker.StateChanged) -> bool:
        if event.worker is self._query_index_worker:
            self._on_agents_query_index_worker_changed(event)
            return True
        return self._query_session.handle_worker_state_changed(event)

    def _cancel_agents_query_workers(self) -> None:
        self._query_session.clear()
        worker = self._query_index_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        self._query_index_worker = None

    def _request_agents_query_index_rebuild(self) -> None:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return
        if not snapshot.complete:
            self._request_full_agents_snapshot()
            return
        self._cancel_agents_query_workers()
        generation = self._load_generation
        display_generation = self._project_ref_display_generation

        def task() -> _AgentsQueryIndexResult:
            return _AgentsQueryIndexResult(
                generation=generation,
                display_generation=display_generation,
                query_index=self._build_agents_query_index(
                    snapshot,
                    generation=generation,
                ),
            )

        self._query_index = None
        self._query_index_worker = self.run_worker(
            task,
            thread=True,
            group="artifacts-agents-query-index",
            exclusive=True,
            exit_on_error=False,
        )

    def _on_agents_query_index_worker_changed(self, event: Worker.StateChanged) -> None:
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        self._query_index_worker = None
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, _AgentsQueryIndexResult):
            return
        if (
            result.generation != self._load_generation
            or result.display_generation != self._project_ref_display_generation
        ):
            return
        self._query_index = result.query_index
        self._set_agent_filter_completion_sources()
        self._refresh_options(preferred_target=self.selected_entry_target())

    def set_project_ref_display(
        self,
        project_ref_display: ProjectRefDisplaySnapshot,
    ) -> None:
        """Adopt the already-loaded project label projection."""

        preferred = self.selected_entry_target()
        self._project_ref_display = project_ref_display
        self._project_ref_display_generation += 1
        self._request_agents_query_index_rebuild()
        self._refresh_options(preferred_target=preferred)

    def query_history_record(self) -> object:
        """Return the committed Agent query-history record."""

        from sase.ace.query_record import QueryRecord

        canonical = self._canonical_agents_query(self.query_source)
        return QueryRecord(
            source=self.query_source,
            canonical=canonical,
            profile_digest=getattr(self._query_profile, "digest", None),
        )

    def apply_query_history_record(self, record: object) -> bool:
        """Apply a validated query-history record to the Agent pane."""

        source = getattr(record, "source", "")
        try:
            canonical = self._canonical_agents_query(source)
        except ProfileQueryError:
            return False
        if canonical != getattr(record, "canonical", None):
            return False
        self._commit_agents_query(source, record_history=False)
        return True

    def apply_saved_query_record(self, record: object) -> bool:
        """Apply a saved slot and record the replaced query in history."""

        source = getattr(record, "source", "")
        try:
            canonical = self._canonical_agents_query(source)
        except ProfileQueryError:
            return False
        if canonical != getattr(record, "canonical", None):
            return False
        self._commit_agents_query(source, record_history=True)
        return True

    def host_limit_query(self) -> str:
        """Return the live or committed Agent query for host limit paging."""

        return self._display_query_source()

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        """Commit a host-limit rewrite and keep the visible selection stable."""

        from sase.ace.tui.actions.artifacts_limit import restore_selection_after_limit

        try:
            self._canonical_agents_query(query)
        except ProfileQueryError:
            return
        preferred = self.selected_entry_target()
        self._commit_agents_query(query, preferred_target=preferred)
        if grow:
            self._maybe_grow_agents_snapshot(query)
        restore_selection_after_limit(self, preferred)  # type: ignore[arg-type]

    def on_filter_bar_clicked(self, event: FilterBar.Clicked) -> None:
        event.stop()
        self.show_filters()

    def show_filters(self) -> None:
        """Open and focus the inline Agent filter bar."""

        bar = self.query_one(AgentFilterBar)
        if self._filter_session_open:
            bar.focus_editor()
            return
        self._filter_session_open = True
        self._filter_restore_query = self.query_source
        self._filter_restore_selection = self.selected_entry_target()
        self._live_query_source = self.query_source
        self._filter_query_error = None
        self._set_agent_filter_completion_sources()
        bar.open(self.query_source)
        self._refresh_options(preferred_target=self._filter_restore_selection)

    def on_agent_filter_bar_query_changed(
        self,
        event: AgentFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        bar = self.query_one(AgentFilterBar)
        if _SAVE_QUERY_RE.match(event.text.strip()):
            bar.set_status(None, exact=False, error=None, coverage_label="save")
            return
        try:
            self._canonical_agents_query(event.text)
        except ProfileQueryError as exc:
            self._filter_query_error = exc
            bar.set_status(None, exact=False, error=exc)
            return
        self._filter_query_error = None
        self._live_query_source = event.text
        self._cancel_jump_mode_for_filter_change()
        self._maybe_grow_agents_snapshot(event.text)
        self._refresh_options()

    def on_agent_filter_bar_submitted(self, event: AgentFilterBar.Submitted) -> None:
        event.stop()
        if _SAVE_QUERY_RE.match(event.text.strip()):
            self._save_agents_query_slot(event.text)
            return
        try:
            self._canonical_agents_query(event.text)
        except ProfileQueryError as exc:
            self._filter_query_error = exc
            self.query_one(AgentFilterBar).set_status(None, exact=False, error=exc)
            self.notify(f"Invalid query: {exc}", severity="error")
            return
        preferred = self.selected_entry_target()
        self._commit_agents_query(event.text, preferred_target=preferred)
        self._close_agent_filter_session()
        self.focus_list()

    def on_agent_filter_bar_dismissed(self, event: AgentFilterBar.Dismissed) -> None:
        event.stop()
        restore = self._filter_restore_query
        preferred = self._filter_restore_selection
        if restore is not None:
            self.query_source = restore
        self._close_agent_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_target=preferred)
        self.focus_list()

    def _display_query_source(self) -> str:
        if self._filter_session_open and self._live_query_source is not None:
            return self._live_query_source
        return self.query_source

    def _commit_agents_query(
        self,
        source: str,
        *,
        preferred_target: ArtifactEntryTarget | None = None,
        record_history: bool = True,
    ) -> None:
        new_canonical = self._canonical_agents_query(source)
        if record_history:
            self._record_query_history_transition(self.query_source, new_canonical)
        self.query_source = source
        self._live_query_source = source
        self._filter_query_error = None
        if self._filter_session_open:
            self.query_one(AgentFilterBar).set_query(source)
        self._cancel_jump_mode_for_filter_change()
        self._maybe_grow_agents_snapshot(source)
        self._refresh_options(preferred_target=preferred_target)

    def _record_query_history_transition(
        self,
        old_source: str,
        new_canonical: str,
    ) -> None:
        recorder = getattr(
            getattr(self, "app", None),
            "_record_artifacts_query_transition",
            None,
        )
        if not callable(recorder):
            return
        try:
            old_canonical = self._canonical_agents_query(old_source)
        except ProfileQueryError:
            old_canonical = old_source
        recorder(
            "agents",
            old_source=old_source,
            old_canonical=old_canonical,
            old_profile_digest=getattr(self._query_profile, "digest", None),
            new_canonical=new_canonical,
            selected_target=self.selected_entry_target(),
        )

    def _filtered_agents_snapshot(
        self,
    ) -> tuple[AgentsSnapshot | None, bool, bool, bool, int | None]:
        snapshot = self._current_snapshot()
        if snapshot is None:
            return None, True, False, False, None
        query = self._display_query_source()
        try:
            remainder, cap = extract_limit(query)
        except LimitTokenError as exc:
            self._filter_query_error = ProfileQueryError(exc.message, exc.start)
            return snapshot, False, False, False, len(snapshot.rows)

        if not remainder.strip():
            matched_rows = snapshot.rows
            match_count = snapshot.total_row_count if not snapshot.complete else None
        else:
            query_index = self._query_index
            if query_index is None:
                if not snapshot.complete:
                    self._request_full_agents_snapshot()
                elif self._query_index_worker is None:
                    self._request_agents_query_index_rebuild()
                return snapshot, False, True, False, None
            try:
                result = self._query_session.result(query, query_index)
            except ProfileQueryError as exc:
                self._filter_query_error = exc
                return snapshot, False, False, False, len(snapshot.rows)
            if result is None:
                return snapshot, False, True, False, None
            if (
                result.cache_key.generation != self._load_generation
                or result.cache_key.profile_digest != self._query_profile.digest
            ):
                return snapshot, False, True, False, None
            matched_ids = frozenset(result.matched_row_ids)
            matched_rows = tuple(
                row for row in snapshot.rows if agent_query_row_id(row) in matched_ids
            )
            match_count = None

        if match_count is None:
            match_count = len(matched_rows)
        capped_rows, truncated = apply_limit(matched_rows, cap)
        if truncated or matched_rows != snapshot.rows:
            snapshot = replace(
                snapshot,
                rows=capped_rows,
                total_row_count=match_count,
                truncated=truncated,
            )
        return snapshot, True, False, truncated, match_count

    def _maybe_grow_agents_snapshot(self, query: str) -> None:
        snapshot = self._current_snapshot()
        if snapshot is None or snapshot.complete:
            return
        try:
            remainder, cap = extract_limit(query)
        except LimitTokenError:
            return
        if remainder.strip() or cap is None or cap > len(snapshot.rows):
            self._request_full_agents_snapshot()

    def _request_full_agents_snapshot(self) -> None:
        if not getattr(self, "artifacts_active", False):
            return
        if getattr(self, "_loading_full", False):
            return
        if getattr(self, "_loading", False) and getattr(self, "_full_pending", False):
            return
        self._request_load(force=False, full=True)

    def _sync_agent_query_bar(
        self,
        match_count: int | None,
        *,
        exact: bool,
        blank: bool = False,
        coverage_label: str | None = None,
        lower_bound: bool = False,
    ) -> None:
        bar = self.query_one(AgentFilterBar)
        if not self._filter_session_open:
            bar.set_query(self.query_source)
        if self._filter_query_error is not None:
            bar.set_status(None, exact=False, error=self._filter_query_error)
            return
        if blank:
            bar.clear_status()
        else:
            bar.set_status(
                match_count,
                exact=exact,
                error=None,
                coverage_label=coverage_label,
                lower_bound=lower_bound,
            )

    def _query_has_active_filter(self) -> bool:
        try:
            remainder, _cap = extract_limit(self._display_query_source())
        except LimitTokenError:
            return True
        return bool(remainder.strip())

    def _set_agent_filter_completion_sources(self) -> None:
        if not self.is_mounted:
            return
        bar = self.query_one(AgentFilterBar)
        if self._query_index is None:
            bar.set_observed_facets({})
            return
        bar.set_observed_facets(self._query_index.facets)

    def _canonical_agents_query(self, source: str) -> str:
        try:
            remainder, cap = extract_limit(source)
        except LimitTokenError as exc:
            raise ProfileQueryError(exc.message, exc.start) from exc
        body = (
            ""
            if not remainder.strip()
            else canonical_query_for_profile(remainder, self._query_profile)
        )
        if cap is None:
            return body
        from sase.ace.query.limit_token import replace_limit

        return replace_limit(body, cap)

    def _save_agents_query_slot(self, text: str) -> None:
        from sase.ace.saved_queries import (
            delete_query,
            find_slot_for_query,
            get_next_available_slot,
            load_saved_queries,
            save_query,
        )

        match = _SAVE_QUERY_RE.match(text.strip())
        if match is None:
            return
        pane_id = "agents"
        slot_specified = match.group(1)
        query_part = match.group(2).strip()
        if not query_part:
            if slot_specified:
                if delete_query(pane_id, slot_specified):
                    self._invalidate_saved_query_cache()
                    self.notify(f"Deleted query from slot {slot_specified}")
                else:
                    self.notify("Failed to delete query", severity="error")
            else:
                self.notify("No slot specified to delete", severity="warning")
            return

        try:
            canonical = self._canonical_agents_query(query_part)
        except ProfileQueryError as exc:
            self.notify(f"Invalid query: {exc}", severity="error")
            return

        existing_slot = find_slot_for_query(pane_id, canonical)
        if slot_specified:
            slot = slot_specified
        else:
            if existing_slot is not None:
                self.notify(f"Query already saved in slot {existing_slot}")
                return
            slot = get_next_available_slot(load_saved_queries(pane_id))
            if slot is None:
                self.notify("All 10 slots are full", severity="warning")
                return

        if save_query(pane_id, slot, query_part, canonical):
            self._invalidate_saved_query_cache()
            if existing_slot is not None and existing_slot != slot:
                self.notify(f"Moved query from slot {existing_slot} to slot {slot}")
            else:
                self.notify(f"Saved to slot {slot}: {canonical}")
        else:
            self.notify("Failed to save query", severity="error")

    def _invalidate_saved_query_cache(self) -> None:
        invalidate = getattr(
            getattr(self, "app", None),
            "_invalidate_saved_queries_cache",
            None,
        )
        if callable(invalidate):
            invalidate()

    def _close_agent_filter_session(self) -> None:
        self.query_one(AgentFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_query = None
        self._filter_restore_selection = None
        self._live_query_source = None
        self._filter_query_error = None

    def close_host_filter_session(self) -> None:
        """Close the inline Agent filter editor before a host query rewrite."""
        if self._filter_session_open:
            self._close_agent_filter_session()

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("agents")


__all__ = ["AgentFilterBar", "AgentsQueryMixin"]
