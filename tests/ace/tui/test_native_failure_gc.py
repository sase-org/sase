"""SAVEALL regressions for failed single-flight payloads and traceback state."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sase.ace.tui.relations import _native_link_index as native_link_index
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from tests.ace.tui._gc_cycles import collect_cyclic_garbage

_REAL_ROWS = tuple(
    {
        "source_ref": f"bead:sase-{i}",
        "relation": "related",
        "target_ref": "bead:sase-0",
        "uses": 1,
    }
    for i in range(1011)
)


@pytest.fixture(autouse=True)
def _isolated_native_index(monkeypatch: pytest.MonkeyPatch):
    identity = AgentIdentitySnapshot.current()
    monkeypatch.setattr(
        AgentIdentitySnapshot, "current", classmethod(lambda _cls: identity)
    )
    monkeypatch.setattr(native_link_index, "_assembled_relations", lambda: [])
    native_link_index.clear_native_link_index_cache()
    yield
    native_link_index.clear_native_link_index_cache()


def _synthetic_snapshot() -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(rows=_REAL_ROWS, source_key=())


def _failure_counts(counts) -> dict[str, int]:
    wanted = (
        "sase.ace.tui.relations._native_link_index._Inflight",
        "sase.ace.tui.relations.artifact_links.ArtifactLinksSnapshot",
        "sase.ace.tui.relations.link_index._ChipRequest",
        "builtins.traceback",
        "builtins.frame",
        "builtins.RuntimeError",
    )
    return {name: counts.get(name, 0) for name in wanted}


def test_failed_native_build_releases_snapshot_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        native_link_index,
        "_compile",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("boom-controlled")),
    )

    def attempt() -> None:
        snapshot = _synthetic_snapshot()
        try:
            native_link_index.native_handle_for_snapshot(snapshot)
        except RuntimeError as exc:
            assert str(exc) == "boom-controlled"
        finally:
            del snapshot

    counts = collect_cyclic_garbage(attempt, repeat=3)
    observed = _failure_counts(counts)
    assert observed["sase.ace.tui.relations._native_link_index._Inflight"] == 0
    assert observed["builtins.traceback"] == 0
    assert observed["builtins.frame"] == 0
    # The snapshot pin is released on failure; no snapshot survives via garbage.
    assert observed["sase.ace.tui.relations.artifact_links.ArtifactLinksSnapshot"] == 0

    # Retry with a real build succeeds after the detached failure.
    monkeypatch.undo()
    snapshot = _synthetic_snapshot()
    try:
        handle = native_link_index.native_handle_for_snapshot(snapshot)
    finally:
        del snapshot
    assert handle is not None


def test_concurrent_failed_native_build_delivers_to_all_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_compile = native_link_index._compile
    entered = 0
    entered_lock = threading.Lock()

    def flaky_compile(*args: object, **kwargs: object) -> object:
        while True:
            with entered_lock:
                if entered >= 4:
                    break
            threading.Event().wait(0.001)
        raise RuntimeError("boom-concurrent")

    monkeypatch.setattr(native_link_index, "_compile", flaky_compile)

    def attempt() -> None:
        nonlocal entered
        snapshot = _synthetic_snapshot()

        def worker() -> None:
            nonlocal entered
            with entered_lock:
                entered += 1
            try:
                native_link_index.native_handle_for_snapshot(snapshot)
            except RuntimeError as exc:
                assert str(exc) == "boom-concurrent"
                # Each waiter raises a fresh detached copy.
                assert exc.__cause__ is None
            else:
                raise AssertionError("expected concurrent failure")

        with entered_lock:
            entered = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            for future in futures:
                future.result(timeout=60)
        del snapshot

    counts = collect_cyclic_garbage(attempt, repeat=2, warmup=0)
    observed = _failure_counts(counts)
    assert observed["sase.ace.tui.relations._native_link_index._Inflight"] == 0
    assert observed["builtins.traceback"] == 0
    assert observed["builtins.frame"] == 0

    # A later generation retries successfully once the failure is gone.
    monkeypatch.setattr(native_link_index, "_compile", real_compile)
    native_link_index.clear_native_link_index_cache()
    retried = _synthetic_snapshot()
    try:
        assert native_link_index.native_handle_for_snapshot(retried) is not None
    finally:
        del retried


def test_failed_chip_request_releases_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    def failing_chips(_handle: object, ref: str) -> list[dict[str, object]]:
        raise RuntimeError("chip-boom")

    monkeypatch.setattr(index_facade, "index_chips", failing_chips)

    def attempt() -> None:
        mapping = _ChipMapping(object(), (("__external__", "#FF5F55", "•"),))
        try:
            mapping["bead:missing"]
        except RuntimeError as exc:
            assert str(exc) == "chip-boom"
        finally:
            del mapping

    counts = collect_cyclic_garbage(attempt, repeat=3)
    observed = _failure_counts(counts)
    assert observed["sase.ace.tui.relations.link_index._ChipRequest"] == 0
    assert observed["builtins.traceback"] == 0
    assert observed["builtins.frame"] == 0


def test_concurrent_failed_chip_requests_each_raise_fresh_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    entered = 0
    entered_lock = threading.Lock()

    def flaky_chips(_handle: object, ref: str) -> list[dict[str, object]]:
        while True:
            with entered_lock:
                if entered >= 4:
                    break
            threading.Event().wait(0.001)
        raise ValueError("chip-concurrent")

    monkeypatch.setattr(index_facade, "index_chips", flaky_chips)

    def attempt() -> None:
        nonlocal entered
        mapping = _ChipMapping(object(), (("__external__", "#FF5F5F", "•"),))
        traceback_ids: list[int] = []
        traceback_lock = threading.Lock()

        def worker() -> None:
            nonlocal entered
            with entered_lock:
                entered += 1
            try:
                mapping["bead:x"]
            except ValueError as exc:
                assert str(exc) == "chip-concurrent"
                assert exc.__cause__ is None
                with traceback_lock:
                    traceback_ids.append(id(exc.__traceback__))
            else:
                raise AssertionError("expected chip failure")

        with entered_lock:
            entered = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            for future in futures:
                future.result(timeout=60)
        assert len(traceback_ids) == 4
        # Fresh copies never share one traceback object.
        assert len(set(traceback_ids)) == 4
        del mapping
        del traceback_ids

    counts = collect_cyclic_garbage(attempt, repeat=2, warmup=0)
    observed = _failure_counts(counts)
    assert observed["sase.ace.tui.relations.link_index._ChipRequest"] == 0
    assert observed["builtins.traceback"] == 0
    assert observed["builtins.frame"] == 0


def test_failure_preserves_cancelled_and_keyboard_interrupt_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for exc_type, message in [
        (KeyboardInterrupt, "stop-now"),
        (asyncio.CancelledError, "cancel-now"),
        (ValueError, "bad-value"),
    ]:

        def raising(
            *_args: object,
            _exc_type: type[BaseException] = exc_type,
            _message: str = message,
            **_kwargs: object,
        ) -> object:
            raise _exc_type(_message)

        monkeypatch.setattr(native_link_index, "_compile", raising)
        snapshot = _synthetic_snapshot()
        try:
            with pytest.raises(exc_type, match=message):
                native_link_index.native_handle_for_snapshot(snapshot)
        finally:
            del snapshot
            native_link_index.clear_native_link_index_cache()
