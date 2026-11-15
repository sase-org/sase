"""Unit tests for the prompt bead-mention index and resolution worker."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.models import bead_preview as bead_preview_models
from sase.ace.tui.models.bead_preview import (
    BeadMentionEntry,
    BeadMentionIndex,
    BeadMentionRequest,
    BeadMentionResolutionPlan,
    BeadRouteFound,
    BeadRouteUnavailable,
    BeadStoreRef,
    BeadStoreDirectory,
    route_bead_mention,
    resolve_bead_mention_updates,
)
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot


def _store(tmp_path: Path, key: str = "sase") -> BeadStoreRef:
    beads_dir = tmp_path / key / "beads"
    return BeadStoreRef(
        project_key=key,
        project_label=key,
        beads_dir=beads_dir,
        primary_workspace=tmp_path / key,
    )


def _directory(*stores: BeadStoreRef) -> BeadStoreDirectory:
    return BeadStoreDirectory(
        snapshots=tuple(
            BeadStoreSnapshot(
                origin=BeadStoreOrigin(
                    project_key=store.project_key,
                    project_label=store.project_label,
                    primary_workspace=store.primary_workspace,
                    beads_dir=store.beads_dir,
                ),
                store_key=store.project_key,
                issue_ids=frozenset(),
                issue_prefix=store.project_key,
                project_refs=frozenset({store.project_key}),
            )
            for store in stores
        )
    )


def _shared_prefix_directory(
    first: BeadStoreRef,
    second: BeadStoreRef,
    *,
    first_ids: frozenset[str],
    second_ids: frozenset[str],
) -> BeadStoreDirectory:
    snapshots = []
    for store, issue_ids in ((first, first_ids), (second, second_ids)):
        snapshots.append(
            BeadStoreSnapshot(
                origin=BeadStoreOrigin(
                    project_key=store.project_key,
                    project_label=store.project_label,
                    primary_workspace=store.primary_workspace,
                    beads_dir=store.beads_dir,
                ),
                store_key=store.project_key,
                issue_ids=issue_ids,
                issue_prefix="sase",
                project_refs=frozenset({store.project_key}),
            )
        )
    return BeadStoreDirectory(snapshots=tuple(snapshots))


def _plan(
    directory: BeadStoreDirectory,
    requests: tuple[BeadMentionRequest, ...],
    known: tuple[tuple[BeadMentionRequest, BeadMentionEntry], ...] = (),
) -> BeadMentionResolutionPlan:
    return BeadMentionResolutionPlan(directory, requests, known)


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
    assert [target.bead_id for target, _ in index.entries_for_store("a")] == ["sase-1"]


def test_index_scopes_entries_by_project_context() -> None:
    index = BeadMentionIndex()
    index.store("sase-1", BeadMentionEntry("open", "a", "t"), "alpha")
    index.store("sase-1", BeadMentionEntry("closed", "b", "t"), "beta")

    assert index.peek("sase-1", "alpha").status == "open"  # type: ignore[union-attr]
    assert index.peek("sase-1", "beta").status == "closed"  # type: ignore[union-attr]
    assert index.peek("sase-1") is None


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
    request1 = BeadMentionRequest("sase-1")
    request9 = BeadMentionRequest("sase-9")
    monkeypatch.setattr(
        bead_preview_models,
        "route_bead_mention",
        lambda bead_id, _directory, **_kwargs: BeadRouteFound(bead_id, store),
    )
    plan = _plan(_directory(store), (request1, request9))
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates[request1] == BeadMentionEntry(
        "in_progress", str(store.beads_dir), "tok-1"
    )
    assert updates[request9] == BeadMentionEntry(None, str(store.beads_dir), "tok-1")
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
    request = BeadMentionRequest("sase-1")
    known = ((request, BeadMentionEntry("in_progress", str(store.beads_dir), "tok-1")),)
    monkeypatch.setattr(
        bead_preview_models,
        "route_bead_mention",
        lambda bead_id, _directory, **_kwargs: BeadRouteFound(bead_id, store),
    )
    plan = _plan(_directory(store), (request,), known)
    assert resolve_bead_mention_updates(plan) == []
    assert calls == []

    tokens["beads"] = "tok-2"
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates[request] == BeadMentionEntry(
        "in_progress", str(store.beads_dir), "tok-2"
    )
    assert calls == [(str(store.beads_dir), ("sase-1",))]


def test_worker_is_fail_open_per_store(monkeypatch: Any, tmp_path: Path) -> None:
    good = _store(tmp_path, "sase")
    bad = _store(tmp_path, "other")
    monkeypatch.setattr(
        bead_preview_models, "_store_fingerprint_token", lambda _beads_dir: "tok"
    )

    def fake_statuses(beads_dir: Path | str, ids: list[str]) -> dict[str, str]:
        if str(beads_dir).endswith("other/beads"):
            raise RuntimeError("store exploded")
        return {"sase-1": "open"}

    monkeypatch.setattr("sase.core.bead_read_facade.statuses_for_ids", fake_statuses)
    good_request = BeadMentionRequest("sase-1")
    bad_request = BeadMentionRequest("other-1")
    routes = {"sase-1": good, "other-1": bad}
    monkeypatch.setattr(
        bead_preview_models,
        "route_bead_mention",
        lambda bead_id, _directory, **_kwargs: BeadRouteFound(bead_id, routes[bead_id]),
    )
    plan = _plan(_directory(good, bad), (good_request, bad_request))
    updates = dict(resolve_bead_mention_updates(plan))
    assert updates == {
        good_request: BeadMentionEntry("open", str(good.beads_dir), "tok"),
        bad_request: BeadMentionEntry(None, str(bad.beads_dir), None),
    }


def test_worker_retries_status_when_fingerprint_unavailable(
    monkeypatch: Any, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    request = BeadMentionRequest("sase-1")
    calls: list[str] = []
    monkeypatch.setattr(
        bead_preview_models, "_store_fingerprint_token", lambda _d: None
    )
    monkeypatch.setattr(
        "sase.core.bead_read_facade.statuses_for_ids",
        lambda _directory, ids: calls.extend(ids) or {"sase-1": "open"},
    )
    monkeypatch.setattr(
        bead_preview_models,
        "route_bead_mention",
        lambda bead_id, _directory, **_kwargs: BeadRouteFound(bead_id, store),
    )
    cached = BeadMentionEntry("closed", str(store.beads_dir), None)
    plan = _plan(_directory(store), (request,), ((request, cached),))

    result = dict(resolve_bead_mention_updates(plan))
    assert result[request] == BeadMentionEntry("open", str(store.beads_dir), None)
    assert calls == ["sase-1"]


def test_worker_marks_unavailable_owner_unstyled(
    monkeypatch: Any, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    request = BeadMentionRequest("sase-1")
    monkeypatch.setattr(
        bead_preview_models,
        "route_bead_mention",
        lambda bead_id, _directory, **_kwargs: BeadRouteUnavailable(
            bead_id,
            "sase",
            "locked",
        ),
    )
    monkeypatch.setattr(
        "sase.core.bead_read_facade.statuses_for_ids",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("unavailable owner must not query statuses")
        ),
    )

    updates = dict(resolve_bead_mention_updates(_plan(_directory(store), (request,))))

    assert updates[request] == BeadMentionEntry(None, "", None)


def test_worker_uses_actual_owner_for_shared_prefix(
    monkeypatch: Any, tmp_path: Path
) -> None:
    first = _store(tmp_path, "first")
    second = _store(tmp_path, "second")
    bead_id = "sase-1aa"
    directory = _shared_prefix_directory(
        first,
        second,
        first_ids=frozenset(),
        second_ids=frozenset({bead_id}),
    )
    monkeypatch.setattr(
        bead_preview_models,
        "_store_fingerprint_token",
        lambda beads_dir: f"token:{beads_dir}",
    )
    monkeypatch.setattr(
        "sase.core.bead_read_facade.statuses_for_ids",
        lambda beads_dir, ids: {
            item: "closed" if str(beads_dir) == str(second.beads_dir) else "open"
            for item in ids
            if item == bead_id
        },
    )

    request = BeadMentionRequest(bead_id)
    updates = dict(resolve_bead_mention_updates(_plan(directory, (request,))))

    assert route_bead_mention(bead_id, directory) == BeadRouteFound(bead_id, second)
    assert updates[request] == BeadMentionEntry(
        "closed", str(second.beads_dir), f"token:{second.beads_dir}"
    )


def test_worker_keeps_ambiguous_shared_prefix_unstyled_and_honors_project(
    monkeypatch: Any, tmp_path: Path
) -> None:
    first = _store(tmp_path, "first")
    second = _store(tmp_path, "second")
    bead_id = "sase-1aa"
    directory = _shared_prefix_directory(
        first,
        second,
        first_ids=frozenset({bead_id}),
        second_ids=frozenset({bead_id}),
    )
    monkeypatch.setattr(
        bead_preview_models,
        "probe_bead_target_owner",
        lambda *_args: ("hit", bead_id),
    )
    monkeypatch.setattr(
        bead_preview_models,
        "_store_fingerprint_token",
        lambda beads_dir: f"token:{beads_dir}",
    )
    monkeypatch.setattr(
        "sase.core.bead_read_facade.statuses_for_ids",
        lambda beads_dir, ids: {
            item: "closed" if str(beads_dir) == str(second.beads_dir) else "open"
            for item in ids
            if item == bead_id
        },
    )
    unqualified = BeadMentionRequest(bead_id)
    qualified = BeadMentionRequest(bead_id, "second")

    updates = dict(
        resolve_bead_mention_updates(_plan(directory, (unqualified, qualified)))
    )

    assert updates[unqualified].status is None
    assert updates[qualified] == BeadMentionEntry(
        "closed", str(second.beads_dir), f"token:{second.beads_dir}"
    )
