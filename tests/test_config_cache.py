"""Tests for the merged-config and mentor-profile caches.

The autouse ``_clear_config_caches`` fixture in conftest already drops both
caches before each test, so individual tests don't need to clear manually.
"""

import threading
import time
from pathlib import Path
from unittest.mock import patch

import yaml
from sase import _yaml_safe
from sase.config import core as config_core
from sase.config import mentor as mentor_config
from sase.config.core import (
    clear_config_cache,
    current_config_token,
    load_merged_config,
    set_include_local_config,
)
from sase.config.mentor import _load_mentor_profiles
from sase.core.paths import machine_name_path


def _write_user_config(global_dir: Path, content: dict) -> None:
    global_dir.mkdir(exist_ok=True)
    (global_dir / "sase.yml").write_text(yaml.dump(content))


def _wait_for_new_merged_config(previous: dict) -> dict:
    """Wait for a background token refresh to invalidate *previous*."""
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        current = load_merged_config()
        if current is not previous:
            return current
        time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
    raise AssertionError("config-token refresh did not publish before timeout")


def _wait_for_config_token(expected: tuple) -> None:
    """Wait for the background worker to publish *expected*."""
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if current_config_token() == expected:
            return
        time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
    raise AssertionError(f"config token {expected!r} was not published before timeout")


def test_load_merged_config_returns_cached_object(tmp_path: Path) -> None:
    """Repeated calls with no file changes return the same dict object."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        first = load_merged_config()
        second = load_merged_config()

    assert first is second


def test_load_merged_config_eventually_invalidates_on_file_mtime_change(
    tmp_path: Path,
) -> None:
    """External edits publish a fresh config after stale-while-revalidate."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "v1"})

    now = [10.0]
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
    ):
        first = load_merged_config()
        assert first["key"] == "v1"

        # Bump mtime by rewriting the file with new content + a newer mtime.
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "v2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01

        stale = load_merged_config()
        assert stale is first
        second = _wait_for_new_merged_config(first)

    assert second["key"] == "v2"
    assert first is not second


def test_load_merged_config_invalidates_on_include_local_toggle(tmp_path: Path) -> None:
    """Flipping ``set_include_local_config`` busts the cache key."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "global"})

    local_dir = tmp_path / "local"
    local_dir.mkdir()
    (local_dir / "sase.yml").write_text(yaml.dump({"key": "local"}))

    try:
        with (
            patch("sase.config.core.CONFIG_DIR", global_dir),
            patch("sase.config.core.Path.cwd", return_value=local_dir),
        ):
            set_include_local_config(True)
            with_local = load_merged_config()
            assert with_local["key"] == "local"

            set_include_local_config(False)
            without_local = load_merged_config()
            assert without_local["key"] == "global"
            assert with_local is not without_local
    finally:
        set_include_local_config(True)


def test_clear_config_cache_forces_reload(tmp_path: Path) -> None:
    """After ``clear_config_cache``, the next call re-reads from disk."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "v1"})

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        first = load_merged_config()
        clear_config_cache()
        second = load_merged_config()

    # Distinct dicts because the cache was dropped between calls.
    assert first is not second
    assert first == second


def test_yaml_content_cache_survives_config_cache_clear(tmp_path: Path) -> None:
    """Clearing merged config does not reparse identical config bytes."""
    global_dir = tmp_path / "global"
    content = {"key": f"user-{tmp_path.name}"}
    _write_user_config(global_dir, content)
    calls = {"n": 0}
    real_loader = _yaml_safe.yaml_safe_load

    def counting_loader(stream: object) -> object:
        calls["n"] += 1
        return real_loader(stream)  # type: ignore[arg-type]

    _yaml_safe._cached_yaml_safe_load_text.cache_clear()
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", return_value={}),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
        patch("sase._yaml_safe.yaml_safe_load", counting_loader),
    ):
        first = load_merged_config()
        clear_config_cache()
        second = load_merged_config()

    assert first == second == content
    assert calls["n"] == 1


def test_yaml_content_cache_returns_fresh_objects(tmp_path: Path) -> None:
    """Content-cache hits cannot leak caller mutations into later loads."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"nested": {"key": f"user-{tmp_path.name}"}})

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", return_value={}),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        first = load_merged_config()
        first["nested"]["key"] = "mutated"
        clear_config_cache()
        second = load_merged_config()

    assert second["nested"]["key"] == f"user-{tmp_path.name}"


def test_selector_stat_participates_in_config_freshness_token(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nvalue: selected\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        before = config_core._compute_current_config_token()
        machine_name_path().write_text("athena\n", encoding="utf-8")
        after = config_core._compute_current_config_token()

    assert before != after
    assert any(
        isinstance(part, tuple) and part and part[0] == str(machine_name_path())
        for part in after
    )


def test_selector_change_eventually_invalidates_merged_config(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "sase_athena.yml").write_text(
        "id:\n  username: alice\n  machine_name: athena\nvalue: first\n",
        encoding="utf-8",
    )
    (global_dir / "sase_zeus.yml").write_text(
        "id:\n  username: alice\n  machine_name: zeus\nvalue: second\n",
        encoding="utf-8",
    )
    selector = machine_name_path()
    selector.write_text("athena\n", encoding="utf-8")

    now = [10.0]
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
    ):
        first = load_merged_config()
        assert first["value"] == "first"

        selector.write_text("zeus\n", encoding="utf-8")
        new_mtime_ns = selector.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(selector, ns=(new_mtime_ns, new_mtime_ns))
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01

        assert load_merged_config() is first
        second = _wait_for_new_merged_config(first)

    assert second["id"]["machine_name"] == "zeus"
    assert second["value"] == "second"


def test_owner_snapshot_reuses_parsed_overlay_until_token_changes(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    overlay = global_dir / "sase_athena.yml"
    overlay.write_text(
        "id:\n  username: alice\n  machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")
    calls = {"count": 0}
    real_loader = config_core._load_yaml_file

    def counting_loader(path: Path) -> dict | None:
        calls["count"] += 1
        return real_loader(path)

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_yaml_file", side_effect=counting_loader),
    ):
        first = config_core.get_agent_owner_config_snapshot()
        second = config_core.get_agent_owner_config_snapshot()

    assert first is second
    assert first.owner is not None
    assert calls["count"] == 1


def test_load_merged_config_caches_default_layer(tmp_path: Path) -> None:
    """The bundled default layer is loaded once and reused."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})

    call_count = {"n": 0}
    real_loader = config_core._load_default_config

    def counting_loader() -> dict:
        call_count["n"] += 1
        return real_loader()

    now = [10.0]
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", counting_loader),
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
    ):
        first = load_merged_config()
        # Force a different cache token by editing the user file.
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "user2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert load_merged_config() is first
        _wait_for_new_merged_config(first)

    # Default layer loaded exactly once even though merged-config was rebuilt.
    assert call_count["n"] == 1


def test_load_merged_config_caches_plugin_layer(tmp_path: Path) -> None:
    """Plugin default configs are loaded once and reused across cache misses."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})

    call_count = {"n": 0}
    real_loader = config_core._load_plugin_configs

    def counting_loader() -> list:
        call_count["n"] += 1
        return real_loader()

    now = [10.0]
    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", counting_loader),
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
    ):
        first = load_merged_config()
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "user2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert load_merged_config() is first
        _wait_for_new_merged_config(first)

    assert call_count["n"] == 1


def test_current_config_token_serves_stale_while_refreshing() -> None:
    """An expired token returns immediately while freshness I/O runs off-thread."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        first = current_config_token()
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS / 2
        assert current_config_token() is first
        assert calls == 1

        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
        assert current_config_token() is first
        assert refresh_started.wait(timeout=1.0)
        assert current_config_token() is first
        assert calls == 2

        release_refresh.set()
        _wait_for_config_token(("token", 2))


def test_current_config_token_refresh_is_single_flight() -> None:
    """Concurrent expired reads coalesce behind one daemon recompute."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        first = current_config_token()
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert current_config_token() is first
        assert refresh_started.wait(timeout=1.0)

        results: list[tuple] = []
        readers = [
            threading.Thread(target=lambda: results.append(current_config_token()))
            for _ in range(12)
        ]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(timeout=1.0)

        assert len(results) == len(readers)
        assert all(token is first for token in results)
        assert calls == 2

        release_refresh.set()
        _wait_for_config_token(("token", 2))


def test_first_config_token_read_does_not_start_worker() -> None:
    """A one-shot CLI lookup computes inline without creating a thread."""
    with patch(
        "sase.config.core._compute_current_config_token",
        return_value=("token", 1),
    ):
        assert current_config_token() == ("token", 1)

    assert config_core._current_config_token_refresh_thread is None


def test_clear_config_cache_resets_config_token_time_gate() -> None:
    """An explicit clear forces immediate token recomputation within the window."""
    with patch(
        "sase.config.core._compute_current_config_token",
        side_effect=[("token", 1), ("token", 2)],
    ) as compute:
        assert current_config_token() == ("token", 1)
        clear_config_cache()
        assert current_config_token() == ("token", 2)

    assert compute.call_count == 2


def test_explicit_invalidation_wins_race_with_background_refresh() -> None:
    """A stale worker cannot overwrite an inline post-clear token swap."""
    now = [10.0]
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def compute() -> tuple[str, int]:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 2:
            refresh_started.set()
            assert release_refresh.wait(timeout=2.0)
        return ("token", call_number)

    with (
        patch("sase.config.core.time.monotonic", side_effect=lambda: now[0]),
        patch("sase.config.core._compute_current_config_token", side_effect=compute),
    ):
        assert current_config_token() == ("token", 1)
        now[0] += config_core._CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS + 0.01
        assert current_config_token() == ("token", 1)
        assert refresh_started.wait(timeout=1.0)

        clear_config_cache()
        assert current_config_token() == ("token", 3)

        release_refresh.set()
        deadline = time.perf_counter() + 2.0
        while config_core._current_config_token_refresh_thread is not None:
            assert time.perf_counter() < deadline
            time.sleep(min(0.01, max(0.0, deadline - time.perf_counter())))
        assert current_config_token() == ("token", 3)


def test_mentor_profiles_cache_returns_same_list() -> None:
    """Repeat calls to ``_load_mentor_profiles`` return the same list object."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "reviewer"
        focus_areas:
          - focus_name: comments
            description: "Doc the public API"
    file_globs:
      - "**/*.py"
"""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        first = _load_mentor_profiles()
        second = _load_mentor_profiles()

    assert first is second
    assert len(first) == 1
    assert first[0].profile_name == "code"


def test_mentor_profiles_cache_invalidates_after_clear() -> None:
    """``clear_mentor_profiles_cache`` forces re-parse on the next call."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "reviewer"
        focus_areas:
          - focus_name: comments
            description: "Doc the public API"
    file_globs:
      - "**/*.py"
"""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        first = _load_mentor_profiles()
        mentor_config._mentor_profiles_cache_token = None
        mentor_config._mentor_profiles_cache_value = None
        mentor_config._local_profile_names_cache_token = None
        mentor_config._local_profile_names_cache_value = None
        second = _load_mentor_profiles()

    assert first is not second
    assert first[0].profile_name == second[0].profile_name
