"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

import json
from functools import lru_cache
import re
import threading

import pytest

from tests._global_state_leak_detector import (
    _CacheFingerprint,
    _Snapshot,
    _ValueFingerprint,
    _cache_fingerprint,
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
        hold.wait(timeout=30.0)

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


def test_known_snapshot_cache_replacement_is_invalidation() -> None:
    first = _global_fingerprint({"generated_at": 1.0, "providers": []})
    assert first is not None
    second = _global_fingerprint({"generated_at": 2.0, "providers": []})
    assert second is not None

    diff = _diff_snapshots(
        _snapshot(globals={"sase.llm_provider.usage.peek._peek_snapshot": first}),
        _snapshot(globals={"sase.llm_provider.usage.peek._peek_snapshot": second}),
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


def test_process_snapshot_ignores_harness_git_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_env = {
        "GIT_AUTHOR_EMAIL": "sase-test@example.invalid",
        "GIT_AUTHOR_NAME": "SASE Test",
        "GIT_COMMITTER_EMAIL": "sase-test@example.invalid",
        "GIT_COMMITTER_NAME": "SASE Test",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_GLOBAL": "/tmp/gitconfig",
        "GIT_CONFIG_KEY_0": "user.name",
        "GIT_CONFIG_SYSTEM": "/tmp/gitconfig",
        "GIT_CONFIG_VALUE_0": "SASE Test",
    }
    for key, value in git_env.items():
        monkeypatch.setenv(key, value)

    snap = capture_process_snapshot()

    assert not any(
        entry.split("=", maxsplit=1)[0] in git_env for entry in snap.environ.entries
    )


def test_process_snapshot_ignores_session_detach_scope_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_env = {
        "SASE_AXE_DISABLE_SYSTEMD_SCOPE": "1",
        "SASE_DETACH_SCOPE_DISABLE": "1",
    }
    for key, value in session_env.items():
        monkeypatch.setenv(key, value)

    snap = capture_process_snapshot()

    assert not any(
        entry.split("=", maxsplit=1)[0] in session_env for entry in snap.environ.entries
    )


def test_process_snapshot_uses_isolation_env_ignore_list() -> None:
    from tests._global_state_leaks.fingerprints import (
        _ENV_KEYS_TO_IGNORE as snapshot_keys,
    )
    from tests._sase_global_state_isolation import (
        _ENV_KEYS_TO_IGNORE as isolation_keys,
    )

    assert snapshot_keys == isolation_keys
    assert "SASE_AXE_DISABLE_SYSTEMD_SCOPE" in snapshot_keys
    assert "SASE_DETACH_SCOPE_DISABLE" in snapshot_keys
    assert "HOME" in snapshot_keys
    assert "SASE_HOME" in snapshot_keys
    assert "TERM" in snapshot_keys


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
