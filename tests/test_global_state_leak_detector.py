"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import re
import threading

import pytest

from tests._global_state_leak_detector import (
    GlobalStateLeakDetector,
    _CacheFingerprint,
    _Snapshot,
    _ValueFingerprint,
    _cache_fingerprint,
    _combine_payloads,
    _diff_snapshots,
    _fingerprint_environment,
    _global_fingerprint,
)
from tests._global_state_leaks.fingerprints import (
    LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL,
    _fingerprint_list,
    _live_config_token_refresh_threads,
    _snapshot as capture_process_snapshot,
)


_ROOT = Path(__file__).resolve().parents[1]


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


def test_live_config_refresh_thread_is_poisoning_not_warming() -> None:
    """A leftover sase-config-token-refresh worker is a poisoning change."""
    live = _fingerprint_list(["123:sase-config-token-refresh"])
    appeared = _diff_snapshots(
        _snapshot(),
        _snapshot(globals={LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL: live}),
    )
    assert [change.name for change in appeared.poisoning] == [
        LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL
    ]
    assert appeared.poisoning[0].reason == "live-config-token-refresh-thread"
    assert appeared.warming_counts == {}

    cooled = _diff_snapshots(
        _snapshot(globals={LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL: live}),
        _snapshot(),
    )
    assert cooled.poisoning == ()
    assert cooled.cooling_counts == {"global": 1}


def test_snapshot_includes_live_config_token_refresh_threads() -> None:
    started = threading.Event()
    hold = threading.Event()

    def _run() -> None:
        started.set()
        hold.wait(timeout=2.0)

    from sase.config.core import CONFIG_TOKEN_REFRESH_THREAD_NAME

    thread = threading.Thread(target=_run, name=CONFIG_TOKEN_REFRESH_THREAD_NAME)
    thread.start()
    assert started.wait(timeout=1.0)
    try:
        assert _live_config_token_refresh_threads()
        snap = capture_process_snapshot()
        assert LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL in snap.globals
    finally:
        hold.set()
        thread.join(timeout=2.0)


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


def test_populated_global_reset_to_cold_state_is_cooling() -> None:
    pattern = _global_fingerprint(re.compile("^#git"))
    assert pattern is not None
    none_value = _global_fingerprint(None)
    assert none_value is not None

    diff = _diff_snapshots(
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": pattern}),
        _snapshot(globals={"sase.x._VCS_TAG_PATTERN": none_value}),
    )

    assert diff.poisoning == ()
    assert diff.cooling_counts == {"global": 1}


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
        _snapshot(globals={"sase.x._STATE": grown}),
        _snapshot(globals={"sase.x._STATE": changed}),
    )
    assert poisoned.poisoning[0].reason == "changed-value"


def test_cache_like_global_replacement_is_invalidation() -> None:
    first = _global_fingerprint({"cached": "first"})
    assert first is not None
    second = _global_fingerprint({"cached": "second"})
    assert second is not None

    diff = _diff_snapshots(
        _snapshot(globals={"sase.x._CACHE": first}),
        _snapshot(globals={"sase.x._CACHE": second}),
    )

    assert diff.poisoning == ()
    assert diff.invalidation_counts == {"global": 1}


def test_collection_reset_to_empty_is_cooling() -> None:
    populated = _global_fingerprint({"cached": "value"})
    assert populated is not None
    empty = _global_fingerprint({})
    assert empty is not None

    diff = _diff_snapshots(
        _snapshot(globals={"sase.x._CACHE": populated}),
        _snapshot(globals={"sase.x._CACHE": empty}),
    )

    assert diff.poisoning == ()
    assert diff.cooling_counts == {"global": 1}


def test_list_prefix_growth_is_warming_but_rewrite_is_poisoning() -> None:
    base = _global_fingerprint(["/repo"])
    assert base is not None
    grown = _global_fingerprint(["/repo", "/repo/src"])
    assert grown is not None
    rewritten = _global_fingerprint(["/tmp", "/repo"])
    assert rewritten is not None

    warm = _diff_snapshots(
        _snapshot(globals={"sase.x._PATHS": base}),
        _snapshot(globals={"sase.x._PATHS": grown}),
    )
    assert warm.poisoning == ()
    assert warm.warming_counts == {"global": 1}

    poisoned = _diff_snapshots(
        _snapshot(globals={"sase.x._PATHS": base}),
        _snapshot(globals={"sase.x._PATHS": rewritten}),
    )
    assert poisoned.poisoning[0].reason == "changed-value"


def test_cache_growth_is_warming_but_cache_clear_is_cooling() -> None:
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
    assert poisoned.poisoning == ()
    assert poisoned.cooling_counts == {"cache": 1}


def test_live_cache_replacement_is_invalidation() -> None:
    diff = _diff_snapshots(
        _snapshot(
            caches={
                "sase.x.cached": _CacheFingerprint(
                    hits=4, misses=4, maxsize=16, currsize=4
                )
            }
        ),
        _snapshot(
            caches={
                "sase.x.cached": _CacheFingerprint(
                    hits=0, misses=1, maxsize=8, currsize=1
                )
            }
        ),
    )

    assert diff.poisoning == ()
    assert diff.invalidation_counts == {"cache": 1}


def test_cache_disappearance_is_invalidation() -> None:
    diff = _diff_snapshots(
        _snapshot(
            caches={
                "sase.x.cached": _CacheFingerprint(
                    hits=1, misses=1, maxsize=1, currsize=1
                )
            }
        ),
        _snapshot(caches={}),
    )

    assert diff.poisoning == ()
    assert diff.invalidation_counts == {"cache": 1}


def test_environment_delta_names_keys_without_values() -> None:
    before = _snapshot()
    after = _snapshot()
    before = _Snapshot(
        globals=before.globals,
        caches=before.caches,
        environ=_fingerprint_environment(
            {
                "STABLE": "one",
                "CHANGED": "VALUE_BEFORE_SECRET",
                "REMOVED": "REMOVED_SECRET",
            }
        ),
        sys_path=before.sys_path,
        cwd=before.cwd,
    )
    after = _Snapshot(
        globals=after.globals,
        caches=after.caches,
        environ=_fingerprint_environment(
            {"STABLE": "one", "CHANGED": "VALUE_AFTER_SECRET", "ADDED": "ADDED_SECRET"}
        ),
        sys_path=after.sys_path,
        cwd=after.cwd,
    )

    diff = _diff_snapshots(before, after)

    change = diff.poisoning[0].public()
    assert change["details"] == {
        "added_keys": ["ADDED"],
        "removed_keys": ["REMOVED"],
        "changed_keys": ["CHANGED"],
    }
    serialized = json.dumps(change, sort_keys=True)
    assert "SECRET" not in serialized


def test_sys_path_append_is_warming_but_rewrite_is_poisoning() -> None:
    before = _snapshot()
    base_path = _global_fingerprint(["/repo", "/repo/src"])
    assert base_path is not None
    appended_path = _global_fingerprint(["/repo", "/repo/src", "/repo/tests"])
    assert appended_path is not None
    rewritten_path = _global_fingerprint(["/tmp", "/repo/src"])
    assert rewritten_path is not None

    warm = _diff_snapshots(
        _Snapshot(
            globals=before.globals,
            caches=before.caches,
            environ=before.environ,
            sys_path=base_path,
            cwd=before.cwd,
        ),
        _Snapshot(
            globals=before.globals,
            caches=before.caches,
            environ=before.environ,
            sys_path=appended_path,
            cwd=before.cwd,
        ),
    )
    assert warm.poisoning == ()
    assert warm.warming_counts == {"sys_path": 1}

    poisoned = _diff_snapshots(
        _Snapshot(
            globals=before.globals,
            caches=before.caches,
            environ=before.environ,
            sys_path=base_path,
            cwd=before.cwd,
        ),
        _Snapshot(
            globals=before.globals,
            caches=before.caches,
            environ=before.environ,
            sys_path=rewritten_path,
            cwd=before.cwd,
        ),
    )
    assert poisoned.poisoning[0].kind == "sys_path"


def test_combined_report_counts_poisoning_and_warming() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "warming_counts": {"global": 3},
                "cooling_counts": {"cache": 1},
                "invalidation_counts": {"global": 2},
                "records": [
                    {
                        "worker_id": "gw1",
                        "worker_order": 2,
                        "nodeid": "tests/test_a.py::test_a",
                        "changes": [{"kind": "global"}, {"kind": "cache"}],
                    }
                ],
            },
            {
                "observed_tests": 1,
                "warming_counts": {"cache": 4},
                "cooling_counts": {"global": 5},
                "invalidation_counts": {"cache": 6},
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
        "cooling_changes_filtered": 6,
        "cooling_by_kind": {"cache": 1, "global": 5},
        "invalidation_changes_filtered": 8,
        "invalidation_by_kind": {"cache": 6, "global": 2},
    }


def test_combined_report_sorts_by_worker_execution_order() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "records": [
                    {
                        "worker_id": "gw1",
                        "worker_order": 2,
                        "nodeid": "tests/test_b.py::test_b",
                        "changes": [{"kind": "global"}],
                    },
                    {
                        "worker_id": "gw1",
                        "worker_order": 1,
                        "nodeid": "tests/test_a.py::test_a",
                        "changes": [{"kind": "global"}],
                    },
                ],
            },
            {
                "observed_tests": 1,
                "records": [
                    {
                        "worker_id": "gw0",
                        "worker_order": 1,
                        "nodeid": "tests/test_c.py::test_c",
                        "changes": [{"kind": "global"}],
                    }
                ],
            },
        ]
    )

    assert [
        (record["worker_id"], record["worker_order"], record["nodeid"])
        for record in report["poisoning"]
    ] == [
        ("gw0", 1, "tests/test_c.py::test_c"),
        ("gw1", 1, "tests/test_a.py::test_a"),
        ("gw1", 2, "tests/test_b.py::test_b"),
    ]


def test_combined_report_carries_worker_errors() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 1,
                "records": [],
                "errors": ["worker gw0 could not write payload"],
            }
        ]
    )

    assert report["errors"] == ["worker gw0 could not write payload"]


def test_worker_payload_is_written_to_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    detector = GlobalStateLeakDetector(
        tmp_path / "report.json",
        worker_dir=tmp_path / "workers",
    )

    assert detector._write_worker_payload() is None

    assert (tmp_path / "workers" / "gw7.json").is_file()


def test_report_only_mode_keeps_pytest_green_on_poison(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    pytester.makepyfile(
        """
        import sase

        sase._LEAK_FOR_TEST = {"value": "before"}

        def test_poison_global_state():
            sase._LEAK_FOR_TEST["value"] = "after"
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        timeout=60,
    )

    result.assert_outcomes(passed=1)


def test_fail_on_poison_mode_fails_pytest_on_poison(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_GLOBAL_LEAK_WORKER_DIR", raising=False)
    report_path = pytester.path / "leaks.json"
    pytester.makepyfile(
        """
        import sase

        sase._LEAK_FOR_TEST = {"value": "before"}

        def test_poison_global_state():
            sase._LEAK_FOR_TEST["value"] = "after"
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._global_state_leak_detector",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-global-leaks",
        "--sase-fail-on-global-leaks",
        f"--sase-global-leak-report={report_path}",
        timeout=60,
    )

    assert result.ret != 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["poisoning_changes"] == 1
    assert report["poisoning"][0]["worker_id"] == "controller"
    assert report["poisoning"][0]["worker_order"] == 1
