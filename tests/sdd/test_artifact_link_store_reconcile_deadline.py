"""Deadline-gated aggregate writes during cross-workspace reconcile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.sdd._artifact_link_store_reconcile import (
    AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row


def _single_store_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase", sidecar_roots={"plan": plans}
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda self: iter((self,)),
    )
    return store


def test_deferred_write_returns_on_disk_aggregate_and_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _single_store_reconcile(tmp_path, monkeypatch)
    store.upsert_row(_row(source="plan:202608/a.md", target="plan:202608/b.md"))
    before = store.load_aggregate()
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_aggregate.time.monotonic",
        lambda: clock["now"],
    )
    original_preview = ArtifactLinkStore.preview_reconciled_aggregate

    def slow_preview(
        self: ArtifactLinkStore, *, deadline: float | None = None
    ) -> dict[str, Any]:
        preview = original_preview(self, deadline=deadline)
        clock["now"] += 20.0  # the preview alone outruns the remaining budget
        preview["skip_diagnostics"] = (*preview["skip_diagnostics"], "scan note")
        return preview

    monkeypatch.setattr(ArtifactLinkStore, "preview_reconciled_aggregate", slow_preview)
    # A concurrent writer wins every compare-and-set.
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_write_aggregate_if_current",
        lambda self, document, *, force=False: None,
    )

    result = store.reconcile_aggregate(deadline=10.0)

    assert result["generation"] == before["generation"]
    assert result["rows"] == before["rows"]
    assert result["skip_diagnostics"] == (
        "scan note",
        AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC,
    )
    assert store.load_aggregate() == before


def test_reconcile_without_deadline_still_writes_after_lost_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _single_store_reconcile(tmp_path, monkeypatch)
    store.upsert_row(_row(source="plan:202608/a.md", target="plan:202608/b.md"))
    original_write = ArtifactLinkStore._write_aggregate_if_current
    attempts: list[bool] = []

    def lose_first_race(
        self: ArtifactLinkStore, document: Any, *, force: bool = False
    ) -> dict[str, Any] | None:
        attempts.append(force)
        if len(attempts) == 1:
            return None
        return original_write(self, document, force=force)

    monkeypatch.setattr(
        ArtifactLinkStore, "_write_aggregate_if_current", lose_first_race
    )

    result = store.reconcile_aggregate()

    assert attempts == [False, False]
    assert "skip_diagnostics" not in result
