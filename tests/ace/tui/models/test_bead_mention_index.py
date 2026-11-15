"""Unit tests for the prompt bead-mention index and resolution worker."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.models import bead_preview as bead_preview_models
from sase.ace.tui.models.bead_preview import (
    BeadMentionEntry,
    BeadMentionIndex,
    BeadMentionStorePlan,
    BeadStoreRef,
    resolve_bead_mention_updates,
)


def _store(tmp_path: Path, key: str = "sase") -> BeadStoreRef:
    beads_dir = tmp_path / key / "beads"
    return BeadStoreRef(
        project_key=key,
        project_label=key,
        beads_dir=beads_dir,
        primary_workspace=tmp_path / key,
    )


def test_index_lookup_refreshes_lru_order() -> None:
    index = BeadMentionIndex(bound=2)
    first = BeadMentionEntry("open", "s", "t1")
    second = BeadMentionEntry("closed", "s", "t1")
    index.store("sase-1", first)
    index.store("sase-2", second)
    assert index.lookup("sase-1") == first
    index.store("sase-3", BeadMentionEntry("open", "s", "t1"))
    assert len(index) == 2
    assert index.peek("sase-1") == first
    assert index.peek("sase-2") is None


def test_index_store_reports_change() -> None:
    index = BeadMentionIndex()
    entry = BeadMentionEntry("open", "key", "token")
    assert index.store("sase-1", entry) is True
    assert index.store("sase-1", entry) is False
    assert index.store("sase-1", BeadMentionEntry(None, "key", "token")) is True


def test_index_entries_for_store() -> None:
    index = BeadMentionIndex()
    index.store("sase-1", BeadMentionEntry("open", "a", "t"))
    index.store("sase-2", BeadMentionEntry("closed", "b", "t"))
    assert [bead_id for bead_id, _ in index.entries_for_store("a")] == ["sase-1"]


def _install_facade(
    monkeypatch: Any,
    *,
    tokens: dict[str, str | None],
    statuses: dict[str, dict[str, str]],
    calls: list[tuple[str, tuple[str, ...]]],
) -> None:
    def fake_fingerprint(beads_dir: Path | str) -> Any:
        key = str(beads_dir)
        for store_key, token in tokens.items():
            if key.endswith(store_key):
                return SimpleNamespace(token=token) if token is not None else None
        return None

    def fake_statuses(beads_dir: Path | str, ids: list[str]) -> dict[str, str]:
        calls.append((str(beads_dir), tuple(ids)))
        for store_key, table in statuses.items():
            if str(beads_dir).endswith(store_key):
                return {bead_id: table[bead_id] for bead_id in ids if bead_id in table}
        return {}

    monkeypatch.setattr(
        "sase.core.bead_read_facade.store_fingerprint", fake_fingerprint
    )
    monkeypatch.setattr("sase.core.bead_read_facade.statuses_for_ids", fake_statuses)


def test_worker_queries_unknown_ids_and_marks_missing(
    monkeypatch: Any, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    calls: list[tuple[str, tuple[str, ...]]] = []
    _install_facade(
        monkeypatch,
        tokens={"beads": "tok-1"},
        statuses={"beads": {"sase-1": "in_progress"}},
        calls=calls,
    )
    plan = (
        BeadMentionStorePlan(store=store, candidates=("sase-1", "sase-9"), known=()),
    )
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates["sase-1"] == BeadMentionEntry(
        "in_progress", str(store.beads_dir), "tok-1"
    )
    assert updates["sase-9"] == BeadMentionEntry(None, str(store.beads_dir), "tok-1")
    assert calls == [(str(store.beads_dir), ("sase-1", "sase-9"))]


def test_worker_skips_fresh_entries_and_revalidates_on_token_change(
    monkeypatch: Any, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    calls: list[tuple[str, tuple[str, ...]]] = []
    tokens = {"beads": "tok-1"}
    _install_facade(
        monkeypatch,
        tokens=tokens,
        statuses={"beads": {"sase-1": "in_progress"}},
        calls=calls,
    )
    known = (
        ("sase-1", BeadMentionEntry("in_progress", str(store.beads_dir), "tok-1")),
    )
    plan = (BeadMentionStorePlan(store=store, candidates=("sase-1",), known=known),)
    assert resolve_bead_mention_updates(plan) == []
    assert calls == []

    tokens["beads"] = "tok-2"
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates["sase-1"] == BeadMentionEntry(
        "in_progress", str(store.beads_dir), "tok-2"
    )
    assert calls == [(str(store.beads_dir), ("sase-1",))]


def test_worker_is_fail_open_per_store(monkeypatch: Any, tmp_path: Path) -> None:
    good = _store(tmp_path, "sase")
    bad = _store(tmp_path, "other")
    monkeypatch.setattr(
        bead_preview_models, "store_fingerprint_token", lambda _beads_dir: "tok"
    )

    def fake_statuses(beads_dir: Path | str, ids: list[str]) -> dict[str, str]:
        if str(beads_dir).endswith("other/beads"):
            raise RuntimeError("store exploded")
        return {"sase-1": "open"}

    monkeypatch.setattr("sase.core.bead_read_facade.statuses_for_ids", fake_statuses)
    plan = (
        BeadMentionStorePlan(store=good, candidates=("sase-1",), known=()),
        BeadMentionStorePlan(store=bad, candidates=("other-1",), known=()),
    )
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates == {"sase-1": BeadMentionEntry("open", str(good.beads_dir), "tok")}
