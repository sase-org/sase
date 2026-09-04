"""ProcObserver store-token gating tests."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import ProcObserver
from sase.feature_flags import override_flags
from sase.procs import Proc


def test_proc_actions_import_does_not_cycle_through_refresh_mixins() -> None:
    """Token probes must not import EventRefreshMixin while proc_actions loads."""
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion

    assert TrackedProcCompletion.__name__ == "TrackedProcCompletion"


def _stub_context(monkeypatch) -> None:
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset())


def _counting_read(monkeypatch, rows: list[Proc] | None = None) -> dict[str, int]:
    calls = {"n": 0}

    def fake_read() -> list[Proc]:
        calls["n"] += 1
        return list(rows or [])

    monkeypatch.setattr(po, "read_procs", fake_read)
    return calls


def test_unchanged_proc_token_skips_read_procs(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    with override_flags(ace_refresh_tokens=True):
        observer.poll_once()
        observer.poll_once()
    assert calls["n"] == 1


def test_changed_proc_token_reads_immediately(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    with override_flags(ace_refresh_tokens=True):
        observer.poll_once()
        store.write_text("{}\n{}\n", encoding="utf-8")
        observer.poll_once()
    assert calls["n"] == 2


def test_request_poll_forces_full_read(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    with override_flags(ace_refresh_tokens=True):
        observer.poll_once()
        observer.request_poll()
        observer.poll_once()
    assert calls["n"] == 2


def test_sanity_due_rereads_unchanged_store(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    with override_flags(ace_refresh_tokens=True):
        observer.poll_once()
        observer._last_proc_store_sanity_mono = 0.0
        observer.poll_once()
    assert calls["n"] == 2


def test_indeterminate_token_reads_immediately(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    real_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> object:
        if self == store:
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    with override_flags(ace_refresh_tokens=True):
        observer.poll_once()
        monkeypatch.setattr(Path, "stat", fake_stat)
        observer.poll_once()
    assert calls["n"] == 2


def test_disabled_flag_parses_every_poll(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    with override_flags(ace_refresh_tokens=False):
        observer.poll_once()
        observer.poll_once()
    assert calls["n"] == 2


def test_cached_rows_still_refresh_selected_log(monkeypatch, tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    store.write_text("{}\n", encoding="utf-8")
    log_path = tmp_path / "out.log"
    log_path.write_text("one\n", encoding="utf-8")
    proc = Proc(
        proc_id="p1",
        label="p1",
        kind="command",
        status="running",
        command=["true"],
        cwd="/tmp",
        origin="ace",
        created_at="2026-08-15T12:00:00Z",
        started_at="2026-08-15T12:00:00Z",
        log_path=str(log_path),
    )
    monkeypatch.setattr(po, "proc_store_path", lambda: store)
    _stub_context(monkeypatch)
    calls = _counting_read(monkeypatch, [proc])
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.set_detail_proc("p1")
    with override_flags(ace_refresh_tokens=True):
        first = observer.poll_once()
        log_path.write_text("one\ntwo\n", encoding="utf-8")
        second = observer.poll_once()
    assert calls["n"] == 1
    assert first is not None
    assert second is not None
    assert first.projection.rows[0].output == "one\n"
    assert second.projection.rows[0].output == "one\ntwo\n"
