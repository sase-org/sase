"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from tests._global_state_leak_detector import (
    GlobalStateLeakDetector,
    _CacheFingerprint,
    _Snapshot,
    _ValueFingerprint,
    _cache_fingerprint,
    _combine_payloads,
    _diff_snapshots,
    _global_fingerprint,
)


def _snapshot(
    *,
    globals: dict[str, _ValueFingerprint] | None = None,
    caches: dict[str, _CacheFingerprint] | None = None,
) -> _Snapshot:
    return _Snapshot(
        globals=globals or {},
        caches=caches or {},
        environ=_global_fingerprint({}) or _missing_fingerprint(),
        sys_path=_global_fingerprint([]) or _missing_fingerprint(),
        cwd="/repo",
    )


def _missing_fingerprint() -> _ValueFingerprint:
    return _ValueFingerprint("missing", None, "missing", "missing")


def test_none_to_pattern_is_warming_but_pattern_change_is_poisoning() -> None:
    none_pattern = _global_fingerprint(None)
    assert none_pattern is not None
    git_pattern = _global_fingerprint(re.compile("^#git"))
    assert git_pattern is not None
    spy_pattern = _global_fingerprint(re.compile("^#spy"))
    assert spy_pattern is not None

    warm = _diff_snapshots(
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": none_pattern}),
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": git_pattern}),
    )
    assert warm.poisoning == ()
    assert warm.warming_counts == {"global": 1}

    poisoned = _diff_snapshots(
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": git_pattern}),
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": spy_pattern}),
    )
    assert [change.name for change in poisoned.poisoning] == ["sase.x._VCS_TAG_PATTERN"]
    assert poisoned.poisoning[0].reason == "changed-value"


def test_collection_growth_is_warming_but_existing_value_change_is_poisoning() -> None:
    empty = _global_fingerprint({})
    assert empty is not None
    grown = _global_fingerprint({"cached": "value"})
    assert grown is not None
    changed = _global_fingerprint({"cached": "poisoned"})
    assert changed is not None

    warm = _diff_snapshots(
        _snapshot(globals={"sase.x._CACHE": empty}),
        _snapshot(globals={"sase.x._CACHE": grown}),
    )
    assert warm.poisoning == ()
    assert warm.warming_counts == {"global": 1}

    poisoned = _diff_snapshots(
        _snapshot(globals={"sase.x._CACHE": grown}),
        _snapshot(globals={"sase.x._CACHE": changed}),
    )
    assert poisoned.poisoning[0].reason == "changed-value"


def test_cache_growth_is_warming_but_cache_clear_is_poisoning() -> None:
    @lru_cache(maxsize=4)
    def cached(value: int) -> int:
        return value

    empty = _cache_fingerprint(cached)
    assert empty is not None
    cached(1)
    grown = _cache_fingerprint(cached)
    assert grown is not None

    warm = _diff_snapshots(
        _snapshot(caches={"sase.x.cached": empty}),
        _snapshot(caches={"sase.x.cached": grown}),
    )
    assert warm.poisoning == ()
    assert warm.warming_counts == {"cache": 1}

    cached.cache_clear()
    cleared = _cache_fingerprint(cached)
    assert cleared is not None
    poisoned = _diff_snapshots(
        _snapshot(caches={"sase.x.cached": grown}),
        _snapshot(caches={"sase.x.cached": cleared}),
    )
    assert poisoned.poisoning[0].reason == "cache-shrank-or-cleared"


def test_combined_report_counts_poisoning_and_warming() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "warming_counts": {"global": 3},
                "records": [
                    {
                        "nodeid": "tests/test_a.py::test_a",
                        "changes": [{"kind": "global"}, {"kind": "cache"}],
                    }
                ],
            },
            {
                "observed_tests": 1,
                "warming_counts": {"cache": 4},
                "records": [],
            },
        ]
    )

    assert report["summary"] == {
        "observed_tests": 3,
        "tests_with_poisoning": 1,
        "poisoning_changes": 2,
        "warming_changes_filtered": 7,
        "warming_by_kind": {"cache": 4, "global": 3},
    }


def test_worker_payload_is_written_to_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    detector = GlobalStateLeakDetector(
        tmp_path / "report.json",
        worker_dir=tmp_path / "workers",
    )

    detector._write_worker_payload(
        {
            "observed_tests": 1,
            "warming_counts": {},
            "records": [],
        }
    )

    assert (tmp_path / "workers" / "gw7.json").is_file()
