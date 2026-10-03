"""Tests for the app-scoped ACE memory-history service (phase `history-service`).

Covers the timeline memo, stale-while-revalidate, single-flight
queries, the body/comparison LRUs (including the never-cache-now
rule), stat-only change tokens, explicit invalidation, the shared
service singleton, the pager factory sharing, and the quiet-time
warm-up. All service IO runs through a fake service and a fake
clock; no git or Rust core is touched.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.memory_history import (
    AceMemoryHistory,
    ace_memory_history,
    schedule_history_warmup,
)


def _timeline_wire(**override):
    versions = [
        {
            "ordinal": 1,
            "commit": "a" * 40,
            "class": "authored",
            "blob_oid": "blob-v1",
            "path": "sase/memory/gotchas.md",
        },
        {
            "ordinal": 2,
            "commit": "b" * 40,
            "class": "authored",
            "blob_oid": "blob-v2",
            "path": "sase/memory/gotchas.md",
        },
    ]
    wire = {
        "state": "tracked",
        "tip": "b" * 40,
        "versions": versions,
    }
    wire.update(override)
    return wire


class _FakeScope:
    def __init__(self, key="project:sase", repo_root="/tmp/repo"):
        self.scope_key = key
        self.repo_root = repo_root


class _FakeService:
    """Counting fake standing in for ``HistoryService``."""

    def __init__(self):
        self.calls: dict[str, int] = {
            "timeline": 0,
            "version": 0,
            "compare": 0,
            "subjects": 0,
            "feed": 0,
            "sync": 0,
        }
        self.timeline_wire = _timeline_wire()
        self.delay_s = 0.0

    def timeline(self, scope, selector, *, include_hidden=False):
        self.calls["timeline"] += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return dict(self.timeline_wire)

    def version(self, scope, selector, version, *, include_body=False):
        self.calls["version"] += 1
        return {
            "body": f"body of {version}",
            "blob_oid": f"blob-{version}",
            "version": {"ordinal": version, "blob_oid": f"blob-{version}"},
        }

    def compare(self, scope, base_selector, base, target_selector, target):
        self.calls["compare"] += 1
        return {"comparison": {"base": base, "target": target, "ops": []}}

    def subjects(self, scope):
        self.calls["subjects"] += 1
        return {"subjects": ["gotchas"]}

    def feed(self, scopes, *, since=None, limit=None, include_hidden=False):
        self.calls["feed"] += 1
        return {"changesets": []}

    def sync(self, scope):
        self.calls["sync"] += 1
        return {"tip": "abc"}

    def forget_scopes(self):
        return None


def _history(service=None, now=1000.0):
    clock_value = [now]
    history = AceMemoryHistory(
        service if service is not None else _FakeService(),
        _clock=lambda: clock_value[0],
    )
    return history, clock_value


def test_timeline_memo_hits_without_requery() -> None:
    service = _FakeService()
    history, _ = _history(service)
    scope = _FakeScope()

    first = history.timeline(scope, "sase/memory/gotchas.md", include_hidden=True)
    second = history.timeline(scope, "sase/memory/gotchas.md", include_hidden=True)

    assert service.calls["timeline"] == 1
    assert first == second


def test_timeline_stale_entry_renders_then_revalidates() -> None:
    service = _FakeService()
    history, clock_value = _history(service)
    scope = _FakeScope()

    stale = history.timeline(scope, "sase/memory/gotchas.md")
    assert service.calls["timeline"] == 1

    service.timeline_wire = _timeline_wire(tip="c" * 40)
    clock_value[0] += 5.0  # past the ~2 s stale threshold

    # The stale snapshot still renders immediately on the memo hit.
    assert history.timeline(scope, "sase/memory/gotchas.md") == stale

    deadline = time.monotonic() + 10.0
    fresh = stale
    while fresh.get("tip") != "c" * 40 and time.monotonic() < deadline:
        time.sleep(0.01)  # sase-test-wait: poll until SWR revalidation lands
        fresh = history.timeline(scope, "sase/memory/gotchas.md")
    assert fresh["tip"] == "c" * 40
    assert service.calls["timeline"] >= 2


def test_timeline_single_flight_shares_one_call() -> None:
    service = _FakeService()
    service.delay_s = 0.2
    history, _ = _history(service)
    scope = _FakeScope()
    barrier = threading.Barrier(8)
    results: list[dict] = []

    def _call() -> None:
        barrier.wait()
        results.append(history.timeline(scope, "sase/memory/gotchas.md"))

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert all(not thread.is_alive() for thread in threads)
    assert service.calls["timeline"] == 1
    assert len(results) == 8
    assert all(result == results[0] for result in results)


def test_version_body_caches_committed_never_now() -> None:
    service = _FakeService()
    history, _ = _history(service)
    scope = _FakeScope()

    first = history.version_body(scope, "sase/memory/gotchas.md", "v2")
    second = history.version_body(scope, "sase/memory/gotchas.md", "v2")
    assert service.calls["version"] == 1
    assert first == second

    history.version_body(scope, "sase/memory/gotchas.md", "now")
    history.version_body(scope, "sase/memory/gotchas.md", "now")
    assert service.calls["version"] == 3


def test_comparison_caches_committed_pairs_never_now() -> None:
    service = _FakeService()
    history, _ = _history(service)
    scope = _FakeScope()

    first = history.comparison(scope, "sase/memory/gotchas.md", "v1", "v2")
    second = history.comparison(scope, "sase/memory/gotchas.md", "v1", "v2")
    assert service.calls["compare"] == 1
    assert first == second

    history.comparison(scope, "sase/memory/gotchas.md", "v2", "now")
    history.comparison(scope, "sase/memory/gotchas.md", "v2", "now")
    assert service.calls["compare"] == 3


def test_change_token_drifts_on_git_and_subject_stats(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    (git_dir / "packed-refs").write_text("")
    (git_dir / "index").write_text("")
    subject = tmp_path / "sase" / "memory" / "gotchas.md"
    subject.parent.mkdir(parents=True)
    subject.write_text("hello\n")

    history, _ = _history()
    scope = _FakeScope(repo_root=str(tmp_path))

    baseline = history.change_token(scope, "sase/memory/gotchas.md")
    assert history.change_token(scope, "sase/memory/gotchas.md") == baseline

    # A subject rewrite drifts the token.
    subject.write_text("hello world\n")
    os.utime(subject, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_001))
    assert history.change_token(scope, "sase/memory/gotchas.md") != baseline

    # A ref advance drifts the token even with the subject untouched.
    mid = history.change_token(scope)
    (git_dir / "refs" / "heads" / "main").write_text("c" * 40 + "\n")
    os.utime(
        git_dir / "refs" / "heads" / "main",
        ns=(1_700_000_001_000_000_000, 1_700_000_001_000_000_000),
    )
    assert history.change_token(scope) != mid


def test_change_token_resolves_gitdir_files(tmp_path: Path) -> None:
    """Worktree ``.git`` files resolve to the real git dir."""
    real_git = tmp_path / "real.git"
    real_git.mkdir()
    (real_git / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".git").write_text("gitdir: real.git\n")

    history, _ = _history()
    scope = _FakeScope(repo_root=str(tmp_path))
    token = history.change_token(scope)
    assert token != (None,)


def test_poll_changed_baselines_then_reports_drift(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    subject = tmp_path / "note.md"
    subject.write_text("v1\n")

    history, _ = _history()
    scope = _FakeScope(repo_root=str(tmp_path))

    assert history.poll_changed(scope, "note.md") is False
    assert history.poll_changed(scope, "note.md") is False

    subject.write_text("v2\n")
    os.utime(subject, ns=(1_700_000_002_000_000_000, 1_700_000_002_000_000_000))
    assert history.poll_changed(scope, "note.md") is True
    assert history.poll_changed(scope, "note.md") is False


def test_invalidation_drops_subject_and_scope_memos() -> None:
    service = _FakeService()
    history, _ = _history(service)
    scope = _FakeScope()
    selector = "sase/memory/gotchas.md"

    history.timeline(scope, selector)
    assert service.calls["timeline"] == 1
    history.timeline(scope, selector)
    assert service.calls["timeline"] == 1

    history.invalidate_subject(scope.scope_key, selector)
    history.timeline(scope, selector)
    assert service.calls["timeline"] == 2

    history.subjects(scope)
    history.feed([scope])
    subject_calls = service.calls["subjects"]
    feed_calls = service.calls["feed"]
    history.invalidate_scope(scope.scope_key)
    history.subjects(scope)
    history.feed([scope])
    assert service.calls["subjects"] == subject_calls + 1
    assert service.calls["feed"] == feed_calls + 1
    # The timeline memo for the scope is gone too.
    history.timeline(scope, selector)
    assert service.calls["timeline"] == 3


def test_scope_for_ref_uses_content_root_never_cwd(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    class _Service:
        def project_scope(self, root):
            seen["root"] = str(root)
            return SimpleNamespace(scope_key="project:sase")

        def home_scope(self):
            return SimpleNamespace(scope_key="home")

    history = AceMemoryHistory(_Service())
    ref = SimpleNamespace(kind="project", content_root=str(tmp_path))
    assert history.scope_for_ref(ref) is not None
    assert seen["root"] == str(tmp_path)
    home_ref = SimpleNamespace(kind="home", content_root="")
    assert history.scope_for_ref(home_ref).scope_key == "home"
    assert history.scope_for_ref(SimpleNamespace(kind="project")) is None


def test_shared_service_is_singleton_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.memory.history.service as service_module

    saved = service_module._SHARED_SERVICE
    service_module._SHARED_SERVICE = None
    try:
        real = service_module.HistoryService
        attempts = {"count": 0}

        def _flaky():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("construction down")
            return real()

        monkeypatch.setattr(service_module, "HistoryService", _flaky)
        with pytest.raises(RuntimeError, match="construction down"):
            service_module.shared_history_service()
        first = service_module.shared_history_service()
        assert isinstance(first, real)
        assert service_module.shared_history_service() is first
        assert attempts["count"] == 2
    finally:
        service_module._SHARED_SERVICE = saved


def test_pager_factory_shares_one_service() -> None:
    from sase.memory.history.pager_provider_core import (
        memory_history_provider_factory,
    )

    first = memory_history_provider_factory()
    second = memory_history_provider_factory()
    assert first._service is second._service


class _FakeApp:
    def __init__(self):
        self.workers: list[tuple] = []

    def run_worker(self, task, **kwargs):
        self.workers.append((task, kwargs))
        return object()


def test_warmup_runs_off_thread_after_scheduling() -> None:
    service = _FakeService()
    app = _FakeApp()
    app._ace_memory_history = AceMemoryHistory(service)
    scopes = [_FakeScope("project:sase"), _FakeScope("home")]

    assert schedule_history_warmup(app, scopes=scopes) is True
    # Scheduling never blocks on IO: no sync ran yet.
    assert service.calls["sync"] == 0
    assert len(app.workers) == 1
    task, kwargs = app.workers[0]
    assert kwargs.get("thread") is True

    task()
    assert service.calls["sync"] == 2

    # Once per app: the second schedule is a no-op.
    assert schedule_history_warmup(app, scopes=scopes) is False
    assert len(app.workers) == 1


def test_ace_memory_history_is_app_scoped() -> None:
    first_app = SimpleNamespace()
    second_app = SimpleNamespace()
    assert ace_memory_history(first_app) is ace_memory_history(first_app)
    assert ace_memory_history(first_app) is not ace_memory_history(second_app)


def _blob_timeline_wire():
    blob_a = "a" * 40
    blob_b = "b" * 40
    return {
        "state": "tracked",
        "tip": "b" * 40,
        "worktree_oid": blob_b,
        "head_oid": blob_b,
        "versions": [
            {
                "ordinal": 2,
                "commit": "b" * 40,
                "class": "authored",
                "kind": "edited",
                "blob_oid": blob_b,
                "path": "sase/memory/gotchas.md",
            },
            {
                "ordinal": 1,
                "commit": "a" * 40,
                "class": "authored",
                "kind": "edited",
                "blob_oid": blob_a,
                "path": "sase/memory/gotchas.md",
            },
        ],
    }


def test_version_for_blob_resolves_newest_match() -> None:
    service = _FakeService()
    service.timeline_wire = _blob_timeline_wire()
    history, _ = _history(service)
    scope = _FakeScope()

    result = history.version_for_blob(scope, "gotchas.md", "a" * 40)
    assert result["ordinal"] == 1
    assert result["newest"] == 2
    assert result["newer_count"] == 1
    assert result["now_matches"] is False


def test_version_for_blob_now_matches_newest_clean() -> None:
    service = _FakeService()
    service.timeline_wire = _blob_timeline_wire()
    history, _ = _history(service)
    scope = _FakeScope()

    result = history.version_for_blob(scope, "gotchas.md", "b" * 40)
    assert result["ordinal"] == 2
    assert result["newer_count"] == 0
    # The fake wire names no pseudo rows and the kit moment reads now.
    assert result["now_matches"] is True


def test_version_for_blob_missing_blob_is_lookup_error() -> None:
    service = _FakeService()
    service.timeline_wire = _blob_timeline_wire()
    history, _ = _history(service)
    scope = _FakeScope()

    with pytest.raises(LookupError, match="blob:"):
        history.version_for_blob(scope, "gotchas.md", "d" * 40)


def test_version_for_blob_short_prefix_is_value_error() -> None:
    service = _FakeService()
    history, _ = _history(service)
    scope = _FakeScope()

    with pytest.raises(ValueError, match="invalid version selector"):
        history.version_for_blob(scope, "gotchas.md", "abc")


def test_version_for_blob_memoizes_by_fingerprint() -> None:
    service = _FakeService()
    service.timeline_wire = _blob_timeline_wire()
    history, clock_value = _history(service)
    scope = _FakeScope()

    first = history.version_for_blob(scope, "gotchas.md", "a" * 40)
    second = history.version_for_blob(scope, "gotchas.md", "a" * 40)
    assert first == second
    assert service.calls["timeline"] == 1

    # A changed timeline fingerprint re-resolves instead of reusing the memo.
    clock_value[0] += 5.0
    service.timeline_wire = _blob_timeline_wire()
    service.timeline_wire["tip"] = "c" * 40
    third = history.version_for_blob(scope, "gotchas.md", "a" * 40)
    assert third["ordinal"] == 1
    assert service.calls["timeline"] == 2


def test_version_for_blob_skips_tombstone_blob() -> None:
    service = _FakeService()
    wire = _blob_timeline_wire()
    wire["versions"] = [
        {
            "ordinal": 3,
            "commit": "c" * 40,
            "class": "authored",
            "kind": "deleted",
            "blob_oid": "a" * 40,
            "path": "sase/memory/gotchas.md",
        },
        *wire["versions"],
    ]
    service.timeline_wire = wire
    history, _ = _history(service)
    scope = _FakeScope()

    result = history.version_for_blob(scope, "gotchas.md", "a" * 40)
    assert result["ordinal"] == 1
