"""Persistent scope-key cache: stat fingerprints, fallback, and parity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.axe.run_agent_wait_deps import resolve_initial_wait_release
from sase.core.wait_dependency_resolution import (
    ScopeKeyCache,
    WaitDependencyIndex,
    resolve_wait_release,
    scope_cache_path,
)
from sase.core.wait_dependency_resolution._scope_cache import (
    keys_for_artifact_dir,
    select_dirs_with_cache,
)
from sase.scripts._chop_wait_checks_terminal import terminal_blockers
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks

_Row = tuple[Path, dict[str, Any], str]


def _read_meta(artifact_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((artifact_dir / "agent_meta.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _row(artifact_dir: Path, project: str = "proj") -> _Row:
    meta = _read_meta(artifact_dir)
    assert meta is not None
    return (artifact_dir, meta, project)


def _index(rows: list[_Row]) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(rows)
    return index


def _corpus(tmp_path: Path) -> tuple[list[Path], Path]:
    lane = make_agent(
        tmp_path, "proj", "20261011010101", "lane", done=True, outcome="completed"
    )
    other = make_agent(
        tmp_path, "proj", "20261011010102", "other", done=True, outcome="completed"
    )
    waiter = make_agent(tmp_path, "proj", "20261011010103", "consumer")
    return [lane, other, waiter], waiter


def test_cache_hit_avoids_meta_reads_and_miss_reads_once(
    tmp_path: Path,
) -> None:
    dirs, waiter = _corpus(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache = ScopeKeyCache.load(cache_path)
    reads = [0]

    def counting_read(artifact_dir: Path) -> dict[str, Any] | None:
        reads[0] += 1
        return _read_meta(artifact_dir)

    cold = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=cache,
        read_meta=counting_read,
        update_cache=True,
    )
    assert list(cold) == [dirs[0], waiter]
    assert reads[0] == 2
    assert cache.save_if_changed(cache_path) is True

    warm_cache = ScopeKeyCache.load(cache_path)
    reads[0] = 0
    warm = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=warm_cache,
        read_meta=counting_read,
        update_cache=True,
    )
    assert list(warm) == [dirs[0], waiter]
    # The unrelated artifact costs one stat, not one JSON read.
    assert reads[0] == 0
    assert warm_cache.save_if_changed(cache_path) is False


def test_meta_rewrite_invalidates_fingerprint_and_reselects(
    tmp_path: Path,
) -> None:
    dirs, waiter = _corpus(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache = ScopeKeyCache.load(cache_path)
    select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=cache,
        read_meta=_read_meta,
        update_cache=True,
    )
    assert cache.save_if_changed(cache_path) is True

    (dirs[1] / "agent_meta.json").write_text(
        json.dumps({"name": "lane", "model": "test"}),
        encoding="utf-8",
    )
    stale = ScopeKeyCache.load(cache_path)
    reselected = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=stale,
        read_meta=_read_meta,
        update_cache=True,
    )
    assert list(reselected) == [dirs[0], dirs[1], waiter]
    assert stale.save_if_changed(cache_path) is True


def test_corrupt_cache_falls_back_to_reads(tmp_path: Path) -> None:
    dirs, waiter = _corpus(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{not json", encoding="utf-8")
    cache = ScopeKeyCache.load(cache_path)
    assert cache.snapshot() == {}

    selected = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=cache,
        read_meta=_read_meta,
        update_cache=True,
    )
    assert list(selected) == [dirs[0], waiter]

    cache_path.write_text(
        json.dumps({"schema_version": 999, "entries": {}}), encoding="utf-8"
    )
    assert ScopeKeyCache.load(cache_path).snapshot() == {}


def test_removed_dirs_are_dropped_on_save(tmp_path: Path) -> None:
    dirs, waiter = _corpus(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache = ScopeKeyCache.load(cache_path)
    for artifact_dir in dirs:
        keys = keys_for_artifact_dir(
            cache, artifact_dir, read_meta=_read_meta, update_cache=True
        )
        assert keys is not None
    assert cache.save_if_changed(cache_path) is True

    doomed = dirs[1]
    for child in doomed.iterdir():
        child.unlink()
    doomed.rmdir()

    reloaded = ScopeKeyCache.load(cache_path)
    assert (
        keys_for_artifact_dir(reloaded, doomed, read_meta=_read_meta, update_cache=True)
        is None
    )
    reloaded.drop_missing([dirs[0], waiter])
    assert reloaded.save_if_changed(cache_path) is True
    pruned = ScopeKeyCache.load(cache_path)
    assert len(pruned.snapshot()) == 2
    assert all("20261011010102" not in dir_key for dir_key in pruned.snapshot())
    assert pruned.save_if_changed(cache_path) is False


def test_scoped_decisions_match_full_view_cold_and_warm(
    tmp_path: Path,
) -> None:
    lane = make_agent(
        tmp_path, "proj", "20261011020101", "lane", done=True, outcome="completed"
    )
    make_agent(
        tmp_path, "proj", "20261011020102", "unrelated", done=True, outcome="completed"
    )
    waiter = make_agent(tmp_path, "proj", "20261011020103", "consumer")
    dirs = [lane, waiter]
    marker: dict[str, Any] = {"waiting_for": ["lane"]}
    full_rows = [_row(lane), _row(waiter)]

    def decide(rows: list[_Row]) -> tuple[Any, ...]:
        index = _index(rows)
        decision = resolve_wait_release(
            index,
            marker,
            waiter_dir=waiter,
            closed_bead_ids=frozenset(),
            now=1_800_000_000.0,
            fresh_index=lambda: _index(rows),
        )
        member_dirs = index.dependency_member_dirs(["lane"], self_artifact_dir=waiter)
        blockers = terminal_blockers(
            index,
            ["lane"],
            [],
            [],
            decision.status.blocked_on,
            self_artifact_dir=waiter,
        )
        return (
            decision.status.resolved,
            decision.status.blocked_on,
            decision.releasable,
            decision.confirmation_failed,
            member_dirs,
            blockers,
        )

    expected = decide(full_rows)

    cache_path = tmp_path / "cache.json"
    cold_cache = ScopeKeyCache.load(cache_path)
    cold_dirs = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=cold_cache,
        read_meta=_read_meta,
        update_cache=True,
    )
    assert decide([_row(path) for path in cold_dirs]) == expected
    assert cold_cache.save_if_changed(cache_path) is True

    warm_cache = ScopeKeyCache.load(cache_path)
    warm_dirs = select_dirs_with_cache(
        dirs,
        {"lane"},
        include_dirs=(waiter,),
        cache=warm_cache,
        read_meta=_read_meta,
        update_cache=False,
    )
    assert decide([_row(path) for path in warm_dirs]) == expected


def test_runner_read_only_use_never_writes_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "lane")
    make_agent(
        tmp_path, "proj", "20261011030101", "lane", done=True, outcome="completed"
    )
    make_agent(
        tmp_path, "proj", "20261011030102", "unrelated", done=True, outcome="completed"
    )

    assert not scope_cache_path().exists()
    decision = resolve_initial_wait_release(
        ["lane"], [], project_name="proj", artifacts_dir=str(waiter_dir)
    )
    assert decision.releasable
    assert not scope_cache_path().exists()


def test_wait_checks_tick_writes_cache_and_warm_tick_agrees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.scripts._chop_wait_checks_run as wait_checks

    waiter_dir = make_waiting_agent(tmp_path, "lane")
    make_agent(
        tmp_path, "proj", "20261011040101", "lane", done=True, outcome="completed"
    )
    make_agent(
        tmp_path, "proj", "20261011040102", "unrelated", done=True, outcome="completed"
    )

    original_read = wait_checks._read_json_dict
    reads = [0]

    def counting_read(path: Path) -> dict[str, Any] | None:
        if path.name == "agent_meta.json":
            reads[0] += 1
        return original_read(path)

    monkeypatch.setattr(wait_checks, "_read_json_dict", counting_read)
    run_wait_checks(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "scoped_waiters=1" in out
    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["lane"],
        "released_by": "wait_checks",
    }
    cold_reads = reads[0]
    assert scope_cache_path().exists()

    (waiter_dir / "ready.json").unlink()
    reads[0] = 0
    run_wait_checks(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "scoped_waiters=1" in out
    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["lane"],
        "released_by": "wait_checks",
    }
    assert reads[0] < cold_reads
