"""Host-owned query-history navigation for Artifacts panes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ..tab_order import ARTIFACTS_TAB

if TYPE_CHECKING:
    from ...query_history import QueryHistoryStacks
    from ...query_record import QueryRecord
    from .._artifact_tab_model import ArtifactsPaneContract
    from ..widgets.artifacts import ArtifactEntryNavigator

log = logging.getLogger(__name__)


class ArtifactsQueryHistoryActionsMixin:
    """Coordinate pane-local Artifacts query-history stacks."""

    current_tab: Any
    query_string: str
    _query_history: dict[str, QueryHistoryStacks]
    _query_selections: dict[str, dict[str, str]]
    _query_history_persist_running: bool
    _query_history_persist_pending: bool
    _query_selection_persist_running: bool
    _query_selection_persist_pending: bool

    def action_prev_query(self) -> None:
        """Navigate to the active Artifacts pane's previous committed query."""

        self._navigate_artifacts_query_history("prev")

    def action_next_query(self) -> None:
        """Navigate to the active Artifacts pane's next committed query."""

        self._navigate_artifacts_query_history("next")

    def _navigate_artifacts_query_history(self, direction: str) -> None:
        from ...query_history import (
            QueryHistoryStacks,
            copy_query_history_stacks,
            navigate_next,
            navigate_prev,
        )

        contract = self._active_query_history_contract()
        if contract is None:
            return
        pane_id = contract.id
        current = self._active_artifacts_query_record(contract)
        if current is None:
            return

        stacks = copy_query_history_stacks(
            self._query_history.setdefault(
                pane_id,
                QueryHistoryStacks(prev=[], next=[]),
            )
        )
        if direction == "prev":
            target = navigate_prev(current, stacks)
            empty_message = "No previous query"
        else:
            target = navigate_next(current, stacks)
            empty_message = "No next query"
        if target is None:
            self.notify(empty_message, severity="warning")  # type: ignore[attr-defined]
            return

        if not self._apply_artifacts_query_record(contract, target):
            return
        self._query_history[pane_id] = stacks
        self._schedule_query_history_persist()

    def _active_query_history_contract(self) -> ArtifactsPaneContract | None:
        if self.current_tab != ARTIFACTS_TAB:
            return None
        from ..artifact_tabs import PaneCapability, artifacts_pane_contract

        pane_id = str(getattr(self, "current_artifacts_pane_key", "patches"))
        contract = getattr(self, "active_artifacts_contract", None)
        if contract is None or getattr(contract, "id", pane_id) != pane_id:
            contract = artifacts_pane_contract(pane_id)
        if contract is None or not contract.has(PaneCapability.QUERY_HISTORY):
            return None
        return contract

    def _active_artifacts_query_record(
        self,
        contract: ArtifactsPaneContract,
    ) -> QueryRecord | None:
        from ...query_record import QueryRecord

        pane_id = contract.id
        if pane_id == "patches":
            return QueryRecord(
                source=self.query_string,
                canonical=self.canonical_query_string,  # type: ignore[attr-defined]
                profile_digest=self._query_profile_digest(contract=contract),
            )
        pane = self._query_history_pane(contract)
        record = getattr(pane, "query_history_record", None)
        if not callable(record):
            return None
        value = record()
        return value if isinstance(value, QueryRecord) else None

    def _apply_artifacts_query_record(
        self,
        contract: ArtifactsPaneContract,
        record: QueryRecord,
    ) -> bool:
        pane_id = contract.id
        pane = self._query_history_pane(contract)
        digest = self._query_profile_digest(contract=contract, pane=pane)
        if (
            record.profile_digest is not None
            and digest is not None
            and record.profile_digest != digest
        ):
            self.notify(  # type: ignore[attr-defined]
                "Stored query no longer matches this pane's query dialect",
                severity="error",
            )
            return False

        if pane_id == "patches":
            applied = self._apply_patch_query_history_record(record)
        else:
            apply = getattr(pane, "apply_query_history_record", None)
            if not callable(apply):
                return False
            try:
                applied = bool(apply(record))
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    f"Error loading query: {exc}",
                    severity="error",
                )
                return False
            if not applied:
                self.notify(  # type: ignore[attr-defined]
                    "Stored query no longer matches this pane's query dialect",
                    severity="error",
                )

        if not applied:
            return False
        self._restore_artifacts_query_selection(pane_id, record.canonical, pane)
        return True

    def _apply_patch_query_history_record(self, record: QueryRecord) -> bool:
        try:
            new_parsed = self._parse_patch_query(record.source)  # type: ignore[attr-defined]
            new_canonical = self._canonical_patch_query(  # type: ignore[attr-defined]
                record.source,
                new_parsed,
            )
        except Exception as exc:
            self.notify(f"Error loading query: {exc}", severity="error")  # type: ignore[attr-defined]
            return False
        if new_canonical != record.canonical:
            self.notify(  # type: ignore[attr-defined]
                "Stored query no longer matches this pane's query dialect",
                severity="error",
            )
            return False

        self.parsed_query = new_parsed
        self.query_string = record.source
        self._load_query_patches()  # type: ignore[attr-defined]
        pane = self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
        if pane is not None and getattr(pane, "_patch_filter_session_open", False):
            from ..widgets.artifacts.patch_filter_bar import PatchFilterBar

            try:
                pane.query_one(PatchFilterBar).set_query(record.source)
            except Exception:
                pass
        self._save_current_query()  # type: ignore[attr-defined]
        return True

    def _query_history_pane(
        self,
        contract: ArtifactsPaneContract,
    ) -> ArtifactEntryNavigator | Any | None:
        pane_id = contract.id
        if pane_id == "patches":
            return self._artifacts_entry_navigator("patches")  # type: ignore[attr-defined]
        if pane_id == "stitches":
            return self._commits_pane()  # type: ignore[attr-defined]
        if pane_id == "beads":
            return self._beads_pane()  # type: ignore[attr-defined]
        if pane_id == "files":
            return self._files_pane()  # type: ignore[attr-defined]
        if contract.is_document_provider():
            return self._active_documents_pane()  # type: ignore[attr-defined]
        return self._artifacts_entry_navigator(pane_id)  # type: ignore[attr-defined]

    def _query_profile_digest(
        self,
        *,
        contract: ArtifactsPaneContract,
        pane: Any | None = None,
    ) -> str | None:
        profile = getattr(pane, "_query_profile", None)
        if profile is None:
            profile = getattr(contract, "query_profile", None)
        return getattr(profile, "digest", None)

    def _record_artifacts_query_transition(
        self,
        pane_id: str,
        *,
        old_source: str,
        old_canonical: str,
        old_profile_digest: str | None,
        new_canonical: str,
        selected_target: Any | None = None,
    ) -> bool:
        """Record a committed pane query replacement in memory."""
        if old_canonical == new_canonical:
            return False

        from ...query_history import QueryHistoryStacks, push_to_prev_stack
        from ...query_record import QueryRecord

        if selected_target is not None:
            self._remember_artifacts_query_selection(
                pane_id,
                old_canonical,
                selected_target,
            )
        current_record = QueryRecord(
            source=old_source,
            canonical=old_canonical,
            profile_digest=old_profile_digest,
        )
        stacks = self._query_history.setdefault(
            pane_id,
            QueryHistoryStacks(prev=[], next=[]),
        )
        push_to_prev_stack(current_record, stacks)
        self._schedule_query_history_persist()
        return True

    def _remember_artifacts_query_selection(
        self,
        pane_id: str,
        canonical: str,
        target: Any,
    ) -> None:
        token = getattr(target, "to_token", None)
        if not callable(token):
            return
        selections = dict(self._query_selections.get(pane_id, {}))
        selections.pop(canonical, None)
        selections[canonical] = token()
        self._query_selections[pane_id] = selections
        self._schedule_query_selection_persist()

    def _restore_artifacts_query_selection(
        self,
        pane_id: str,
        canonical: str,
        pane: Any | None,
    ) -> None:
        if pane is None:
            return
        token = self._query_selections.get(pane_id, {}).get(canonical)
        if token is None:
            return
        from ..widgets.artifacts.entry_navigation import (
            ArtifactEntryTarget,
            LinkRequestState,
        )

        try:
            target = ArtifactEntryTarget.from_token(token)
        except ValueError:
            return
        request = getattr(pane, "request_entry_target", None)
        if callable(request) and request(target) is LinkRequestState.SELECTED:
            return
        select = getattr(pane, "select_entry_target", None)
        if callable(select):
            select(target)

    def _query_history_help_context(
        self,
    ) -> tuple[str | None, QueryHistoryStacks | None, bool]:
        contract = self._active_query_history_contract()
        active_query = self.canonical_query_string  # type: ignore[attr-defined]
        if contract is None:
            return active_query, None, False
        record = self._active_artifacts_query_record(contract)
        if record is not None:
            active_query = record.canonical
        from ...query_history import QueryHistoryStacks, copy_query_history_stacks

        stacks = copy_query_history_stacks(
            self._query_history.setdefault(
                contract.id,
                QueryHistoryStacks(prev=[], next=[]),
            )
        )
        return active_query, stacks, True

    def _schedule_query_history_persist(self) -> None:
        from ...query_history import save_all_query_history, snapshot_query_history

        def write_snapshot() -> bool:
            return save_all_query_history(snapshot)

        if getattr(self, "_query_history_persist_running", False):
            self._query_history_persist_pending = True
            return
        self._query_history_persist_running = True
        snapshot = snapshot_query_history(self._query_history)

        async def runner() -> None:
            try:
                await asyncio.to_thread(write_snapshot)
            finally:
                self._query_history_persist_running = False
                if getattr(self, "_query_history_persist_pending", False):
                    self._query_history_persist_pending = False
                    self._schedule_query_history_persist()

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            runner(),
            name="sase-artifacts-query-history-save",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            try:
                write_snapshot()
            finally:
                self._query_history_persist_running = False

    def _schedule_query_selection_persist(self) -> None:
        from ...query_selection import (
            save_all_query_selections,
            snapshot_query_selections,
        )

        def write_snapshot() -> bool:
            return save_all_query_selections(snapshot)

        if getattr(self, "_query_selection_persist_running", False):
            self._query_selection_persist_pending = True
            return
        self._query_selection_persist_running = True
        snapshot = snapshot_query_selections(self._query_selections)

        async def runner() -> None:
            try:
                await asyncio.to_thread(write_snapshot)
            finally:
                self._query_selection_persist_running = False
                if getattr(self, "_query_selection_persist_pending", False):
                    self._query_selection_persist_pending = False
                    self._schedule_query_selection_persist()

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            runner(),
            name="sase-artifacts-query-selection-save",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            try:
                write_snapshot()
            finally:
                self._query_selection_persist_running = False


__all__ = ["ArtifactsQueryHistoryActionsMixin"]
