"""Chip-cache, concurrency, and snapshot-identity tests for the link-graph index."""

from __future__ import annotations

import pytest

from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.relations.link_index import _build_link_index
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from tests.ace.tui._link_index_helpers import snapshot

__all__ = [
    "test_clear_epoch_fences_pending_generation_but_releases_its_caller",
    "test_concurrent_requests_for_one_snapshot_compile_once",
    "test_distinct_synthetic_snapshots_with_shared_keys_stay_separate",
    "test_evicted_scope_keeps_pending_generation_fence",
    "test_failed_build_unblocks_waiters_and_retry_succeeds",
    "test_requested_chip_cache_is_bounded_and_refills_after_eviction",
]


def test_requested_chip_cache_is_bounded_and_refills_after_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    calls: list[str] = []

    def query(_handle: object, ref: str) -> list[dict[str, object]]:
        calls.append(ref)
        return [
            {
                "relation": "related",
                "label": "related",
                "directed": False,
                "this_is_source": True,
                "neighbor_ref": "bead:neighbor",
                "neighbor_kind": "bead",
                "neighbor_target": None,
                "why": ref,
                "origin": "manual",
                "uses": 1,
                "created_by": "test",
                "created_at": "2026-10-13T00:00:00Z",
                "writable": True,
            }
        ]

    monkeypatch.setattr(index_facade, "index_chips", query)
    mapping = _ChipMapping(object(), (("__external__", "#FF5F5F", "•"),))
    mapping._max = 1
    mapping["agent:a"]
    mapping["agent:b"]
    assert mapping.cached("agent:a") is None
    assert mapping.cached("agent:b") is not None
    assert mapping["agent:a"][0].why == "agent:a"
    assert calls == ["agent:a", "agent:b", "agent:a"]


def test_concurrent_requests_for_one_snapshot_compile_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index
    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    snapshot_rows = snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    entered = 0
    entered_lock = threading.Lock()
    real_build = native_link_index.build_index
    builds = 0

    def gated_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        with entered_lock:
            builds += 1
        while True:
            with entered_lock:
                if entered >= 4:
                    break
            threading.Event().wait(0.001)
        return real_build(*args, **kwargs)

    def worker() -> object:
        nonlocal entered
        with entered_lock:
            entered += 1
        return link_index_for_snapshot(snapshot_rows)

    monkeypatch.setattr(native_link_index, "build_index", gated_build)
    with ThreadPoolExecutor(max_workers=4) as pool:
        indexes = list(pool.map(lambda _: worker(), range(4)))
    assert builds == 1
    assert all(index is indexes[0] for index in indexes)
    handles = {id(index.by_ref._handle) for index in indexes}  # type: ignore[union-attr]
    assert handles == {id(indexes[0].by_ref._handle)}  # type: ignore[union-attr]
    for index in indexes:
        assert index.chips_for("bead:sase-1")


def test_evicted_scope_keeps_pending_generation_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index

    identity = AgentIdentitySnapshot.current()
    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda _cls: identity)
    )
    monkeypatch.setattr(native_link_index, "_assembled_relations", lambda: [])
    monkeypatch.setattr(native_link_index, "_HANDLE_CACHE_MAX", 1)
    native_link_index.clear_native_link_index_cache()
    old = ArtifactLinksSnapshot(source_key=(("p", 1, 1),))
    newer = ArtifactLinksSnapshot(source_key=(("p", 2, 2),))
    other = ArtifactLinksSnapshot(source_key=(("q", 1, 1),))
    old_started = threading.Event()
    release_old = threading.Event()

    def compile(snapshot: ArtifactLinksSnapshot, *_args: object) -> object:
        if snapshot is old:
            old_started.set()
            assert release_old.wait(timeout=10)
        return tuple(snapshot.source_key)

    monkeypatch.setattr(native_link_index, "_compile", compile)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_old = pool.submit(native_link_index.native_handle_for_snapshot, old)
            assert old_started.wait(timeout=10)
            native_link_index.native_handle_for_snapshot(newer)
            native_link_index.native_handle_for_snapshot(other)
            release_old.set()
            assert pending_old.result(timeout=10) == old.source_key
        assert list(native_link_index._HANDLE_CACHE) == [("q",)]
        assert native_link_index._PENDING_BY_SLOT == {}
    finally:
        release_old.set()
        native_link_index.clear_native_link_index_cache()


def test_clear_epoch_fences_pending_generation_but_releases_its_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index

    identity = AgentIdentitySnapshot.current()
    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda _cls: identity)
    )
    monkeypatch.setattr(native_link_index, "_assembled_relations", lambda: [])
    native_link_index.clear_native_link_index_cache()
    old = ArtifactLinksSnapshot(source_key=(("p", 1, 1),))
    current = ArtifactLinksSnapshot(source_key=(("p", 2, 2),))
    old_started = threading.Event()
    release_old = threading.Event()

    def compile(snapshot: ArtifactLinksSnapshot, *_args: object) -> object:
        if snapshot is old:
            old_started.set()
            assert release_old.wait(timeout=10)
        return tuple(snapshot.source_key)

    monkeypatch.setattr(native_link_index, "_compile", compile)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_old = pool.submit(native_link_index.native_handle_for_snapshot, old)
            assert old_started.wait(timeout=10)
            native_link_index.clear_native_link_index_cache()
            assert (
                native_link_index.native_handle_for_snapshot(current)
                == current.source_key
            )
            release_old.set()
            assert pending_old.result(timeout=10) == old.source_key
        cached = native_link_index._HANDLE_CACHE[("p",)]
        assert cached.source_key == current.source_key
        assert native_link_index._PENDING_BY_SLOT == {}
    finally:
        release_old.set()
        native_link_index.clear_native_link_index_cache()


def test_failed_build_unblocks_waiters_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sase.ace.tui.relations._native_link_index as native_link_index
    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    snapshot_rows = snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    release = threading.Event()
    build_lock = threading.Lock()
    real_build = native_link_index.build_index
    builds = 0
    fail_open = True

    def flaky_build(*args: object, **kwargs: object) -> object:
        nonlocal builds
        with build_lock:
            builds += 1
        assert release.wait(timeout=60)
        if fail_open:
            raise RuntimeError("boom")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(native_link_index, "build_index", flaky_build)
    # The main thread joins as a guaranteed waiter: the owner is already
    # inside its build (or fails first and the main thread's own build
    # fails the same way), so every interleaving raises instead of hanging.
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(link_index_for_snapshot, snapshot_rows)
        while True:
            with build_lock:
                if builds >= 1:
                    break
            threading.Event().wait(0.001)
        timer = threading.Timer(2.0, release.set)
        timer.start()
        try:
            with pytest.raises(RuntimeError, match="boom"):
                link_index_for_snapshot(snapshot_rows)
            with pytest.raises(RuntimeError, match="boom"):
                owner.result(timeout=60)
        finally:
            timer.join(timeout=60)
    assert builds >= 1
    fail_open = False
    release.set()
    before = builds
    index = link_index_for_snapshot(snapshot_rows)
    assert builds == before + 1
    assert index.chips_for("bead:sase-1")


def test_distinct_synthetic_snapshots_with_shared_keys_stay_separate() -> None:
    first = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
            )
        )
    )
    second = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:sase-9",
                    "relation": "related",
                    "target_ref": "bead:sase-8",
                    "uses": 1,
                },
            )
        )
    )
    assert first.chips_for("bead:sase-1")
    assert first.chips_for("bead:sase-9") == ()
    assert second.chips_for("bead:sase-9")
    assert second.chips_for("bead:sase-1") == ()

    from sase.ace.tui.relations.link_index import link_index_for_snapshot

    shared_a = snapshot(
        (
            {
                "source_ref": "bead:sase-1",
                "relation": "related",
                "target_ref": "bead:sase-2",
                "uses": 1,
            },
        )
    )
    shared_b = snapshot(
        (
            {
                "source_ref": "bead:sase-9",
                "relation": "related",
                "target_ref": "bead:sase-8",
                "uses": 1,
            },
        )
    )
    cached_a = link_index_for_snapshot(shared_a)
    assert cached_a.chips_for("bead:sase-1")
    assert cached_a.chips_for("bead:sase-9") == ()
    cached_b = link_index_for_snapshot(shared_b)
    assert cached_b.chips_for("bead:sase-9")
    assert cached_b.chips_for("bead:sase-1") == ()
