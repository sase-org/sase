"""Tests for the merged-config and mentor-profile caches.

The autouse ``_clear_config_caches`` fixture in conftest already drops both
caches before each test, so individual tests don't need to clear manually.
"""

from pathlib import Path
from unittest.mock import patch

import yaml
from sase.config import core as config_core
from sase.config import mentor as mentor_config
from sase.config.core import (
    clear_config_cache,
    load_merged_config,
    set_include_local_config,
)
from sase.config.mentor import _load_mentor_profiles


def _write_user_config(global_dir: Path, content: dict) -> None:
    global_dir.mkdir(exist_ok=True)
    (global_dir / "sase.yml").write_text(yaml.dump(content))


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


def test_load_merged_config_invalidates_on_file_mtime_change(tmp_path: Path) -> None:
    """Editing a layer file invalidates the cache and a fresh dict is returned."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "v1"})

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
    ):
        first = load_merged_config()
        assert first["key"] == "v1"

        # Bump mtime by rewriting the file with new content + a newer mtime.
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "v2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))

        second = load_merged_config()

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


def test_load_merged_config_caches_default_layer(tmp_path: Path) -> None:
    """The bundled default layer is loaded once and reused."""
    global_dir = tmp_path / "global"
    _write_user_config(global_dir, {"key": "user"})

    call_count = {"n": 0}
    real_loader = config_core._load_default_config

    def counting_loader() -> dict:
        call_count["n"] += 1
        return real_loader()

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_default_config", counting_loader),
    ):
        load_merged_config()
        # Force a different cache token by editing the user file.
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "user2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))
        load_merged_config()

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

    with (
        patch("sase.config.core.CONFIG_DIR", global_dir),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch("sase.config.core._load_plugin_configs", counting_loader),
    ):
        load_merged_config()
        sase_yml = global_dir / "sase.yml"
        sase_yml.write_text(yaml.dump({"key": "user2"}))
        new_mtime_ns = sase_yml.stat().st_mtime_ns + 10_000_000
        import os

        os.utime(sase_yml, ns=(new_mtime_ns, new_mtime_ns))
        load_merged_config()

    assert call_count["n"] == 1


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
        mentor_config.clear_mentor_profiles_cache()
        second = _load_mentor_profiles()

    assert first is not second
    assert first[0].profile_name == second[0].profile_name
