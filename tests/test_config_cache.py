"""Tests for the merged-config cache.

The autouse ``_clear_config_caches`` fixture isolates the config caches
around each test (setup after ``CONFIG_DIR`` redirect, teardown drain before
monkeypatch restore), so individual tests don't need to clear manually.

Sibling modules cover the rest of the config caches:
``test_config_cache_token.py`` (freshness token and its refresh worker),
``test_config_cache_selector.py`` (machine-name overlay selection and the
owner snapshot), ``test_config_cache_teardown.py`` (the isolation fixture's
drain/reset helpers), and ``test_mentor_config_cache.py`` (mentor profiles).
"""

from pathlib import Path
from unittest.mock import patch

import yaml
from sase import _yaml_safe
from sase.config import core as config_core
from sase.config.core import (
    clear_config_cache,
    load_merged_config,
    set_include_local_config,
)
from tests._config_cache_helpers import (
    _wait_for_new_merged_config,
    _write_user_config,
)


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
