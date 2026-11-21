"""Tree-size cache that keeps hourly ACE-run previews from re-walking runs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sase.core.agent_artifact_run_size_cache import AceRunSizeCache


def _run_dir(root: Path, name: str, payload: str = "x" * 10) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "output.log").write_text(payload, encoding="utf-8")
    return run


class _Measure:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> int:
        self.calls.append(path)
        return sum(child.stat().st_size for child in path.iterdir())


def test_unchanged_run_dirs_reuse_the_last_measurement(tmp_path: Path) -> None:
    cache_path = tmp_path / "state" / "sizes.json"
    run = _run_dir(tmp_path / "runs", "20260801120000")
    measure = _Measure()

    first = AceRunSizeCache(cache_path)
    assert first.size(run, measure) == 10
    first.save()
    second = AceRunSizeCache(cache_path)
    assert second.size(run, measure) == 10

    assert measure.calls == [run]
    assert (second.hits, second.misses) == (1, 0)


def test_a_changed_run_dir_is_measured_again(tmp_path: Path) -> None:
    cache_path = tmp_path / "sizes.json"
    run = _run_dir(tmp_path / "runs", "20260801120000")
    measure = _Measure()
    cache = AceRunSizeCache(cache_path)
    cache.size(run, measure)
    cache.save()

    (run / "late.txt").write_text("y" * 5, encoding="utf-8")
    stat = run.stat()
    os.utime(run, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert AceRunSizeCache(cache_path).size(run, measure) == 15
    assert len(measure.calls) == 2


def test_save_keeps_only_this_passes_runs(tmp_path: Path) -> None:
    cache_path = tmp_path / "sizes.json"
    kept = _run_dir(tmp_path / "runs", "20260801120000")
    dropped = _run_dir(tmp_path / "runs", "20260802120000")
    measure = _Measure()
    cache = AceRunSizeCache(cache_path)
    cache.size(kept, measure)
    cache.size(dropped, measure)
    cache.save()

    next_pass = AceRunSizeCache(cache_path)
    next_pass.size(kept, measure)
    next_pass.save()

    sizes = json.loads(cache_path.read_text(encoding="utf-8"))["sizes"]
    assert set(sizes) == {str(kept)}


def test_unreadable_cache_reads_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "sizes.json"
    run = _run_dir(tmp_path / "runs", "20260801120000")
    measure = _Measure()
    for payload in ("{nope", "[]", json.dumps({"schema_version": 9, "sizes": {}})):
        cache_path.write_text(payload, encoding="utf-8")
        assert AceRunSizeCache(cache_path).size(run, measure) == 10
    assert len(measure.calls) == 3
