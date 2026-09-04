"""Unit coverage for host-owned Artifacts query history."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.query_history import QueryHistoryStacks
from sase.ace.query_record import QueryRecord
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.actions.artifacts_query_history import (
    ArtifactsQueryHistoryActionsMixin,
)
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    LinkRequestState,
)


class _Pane:
    def __init__(self, record: QueryRecord, digest: str) -> None:
        self.record = record
        self.digest = digest
        self.selected = ArtifactEntryTarget("beads", ("task", "one"))
        self.restored: list[ArtifactEntryTarget] = []

    @property
    def _query_profile(self) -> object:
        return SimpleNamespace(digest=self.digest)

    def query_history_record(self) -> QueryRecord:
        return self.record

    def apply_query_history_record(self, record: QueryRecord) -> bool:
        if record.source == "invalid":
            return False
        self.record = record
        return True

    def selected_entry_target(self) -> ArtifactEntryTarget:
        return self.selected

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        del generation
        self.restored.append(target)
        return LinkRequestState.SELECTED


class _App(ArtifactsQueryHistoryActionsMixin):
    def __init__(self) -> None:
        self.current_tab = "artifacts"
        self.active_artifacts_contract = compile_builtin_contract(
            "beads",
            label="Beads",
            icon="b",
            accent="#00D7AF",
        )
        digest = self.active_artifacts_contract.query_profile.digest
        self.current_artifacts_pane_key = "beads"
        self.pane = _Pane(
            QueryRecord(
                source="status:open",
                canonical="status:open",
                profile_digest=digest,
            ),
            digest,
        )
        self._query_history = {
            "beads": QueryHistoryStacks(
                prev=[
                    QueryRecord(
                        source="status:closed",
                        canonical="status:closed",
                        profile_digest=digest,
                    )
                ],
                next=[],
            )
        }
        self._query_selections = {
            "beads": {"status:closed": self.pane.selected.to_token()}
        }
        self.saved_history = 0
        self.saved_selections = 0
        self.notifications: list[tuple[str, str | None]] = []

    @property
    def canonical_query_string(self) -> str:
        return "patch-query"

    def _beads_pane(self) -> _Pane:
        return self.pane

    def notify(self, message: str, *, severity: str | None = None, **_: Any) -> None:
        self.notifications.append((message, severity))

    def _schedule_query_history_persist(self) -> None:
        self.saved_history += 1

    def _schedule_query_selection_persist(self) -> None:
        self.saved_selections += 1


def test_prev_query_replays_active_non_patch_pane_history() -> None:
    app = _App()

    app.action_prev_query()

    assert app.pane.record.canonical == "status:closed"
    assert app._query_history["beads"].prev == []
    assert [record.canonical for record in app._query_history["beads"].next] == [
        "status:open"
    ]
    assert app.pane.restored == [app.pane.selected]
    assert app.saved_history == 1
    assert app.notifications == []


def test_stale_query_record_does_not_mutate_stacks() -> None:
    app = _App()
    stale = QueryRecord(
        source="status:closed",
        canonical="status:closed",
        profile_digest="stale",
    )
    app._query_history["beads"] = QueryHistoryStacks(prev=[stale], next=[])

    app.action_prev_query()

    assert app.pane.record.canonical == "status:open"
    assert app._query_history["beads"].prev == [stale]
    assert app._query_history["beads"].next == []
    assert app.saved_history == 0
    assert app.notifications == [
        ("Stored query no longer matches this pane's query dialect", "error")
    ]


def test_committed_transition_records_selection_and_clears_forward() -> None:
    app = _App()
    app._query_history["beads"] = QueryHistoryStacks(
        prev=[],
        next=[QueryRecord(source="future", canonical="future")],
    )

    changed = app._record_artifacts_query_transition(
        "beads",
        old_source="status:open",
        old_canonical="status:open",
        old_profile_digest=app.active_artifacts_contract.query_profile.digest,
        new_canonical="status:closed",
        selected_target=app.pane.selected,
    )

    assert changed is True
    assert [record.canonical for record in app._query_history["beads"].prev] == [
        "status:open"
    ]
    assert app._query_history["beads"].next == []
    assert app._query_selections["beads"]["status:open"] == app.pane.selected.to_token()
    assert app.saved_history == 1
    assert app.saved_selections == 1
