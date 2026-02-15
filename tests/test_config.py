"""Tests for the centralized config module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from sase.config import CONFIG_DIR, _deep_merge, load_merged_config


# --- _deep_merge tests ---


def test_deep_merge_empty_base() -> None:
    """Empty base returns override."""
    assert _deep_merge({}, {"a": 1}) == {"a": 1}


def test_deep_merge_empty_override() -> None:
    """Empty override returns base."""
    assert _deep_merge({"a": 1}, {}) == {"a": 1}


def test_deep_merge_both_empty() -> None:
    """Both empty returns empty dict."""
    assert _deep_merge({}, {}) == {}


def test_deep_merge_scalar_override() -> None:
    """Scalar in override replaces scalar in base."""
    assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_deep_merge_nested_dicts() -> None:
    """Nested dicts are merged recursively."""
    base = {"a": {"x": 1, "y": 2}}
    override = {"a": {"y": 3, "z": 4}}
    result = _deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 3, "z": 4}}


def test_deep_merge_list_concatenation() -> None:
    """Lists are concatenated (overlay appended to base)."""
    base = {"items": [1, 2]}
    override = {"items": [3, 4]}
    result = _deep_merge(base, override)
    assert result == {"items": [1, 2, 3, 4]}


def test_deep_merge_mixed_types_override_wins() -> None:
    """When types differ, overlay value wins."""
    # dict in base, scalar in override
    assert _deep_merge({"a": {"x": 1}}, {"a": 42}) == {"a": 42}
    # scalar in base, dict in override
    assert _deep_merge({"a": 42}, {"a": {"x": 1}}) == {"a": {"x": 1}}
    # list in base, scalar in override
    assert _deep_merge({"a": [1, 2]}, {"a": "hello"}) == {"a": "hello"}


def test_deep_merge_no_mutation() -> None:
    """Neither base nor override is mutated."""
    base = {"a": {"x": 1}, "items": [1]}
    override = {"a": {"y": 2}, "items": [2]}
    base_copy = {"a": {"x": 1}, "items": [1]}
    override_copy = {"a": {"y": 2}, "items": [2]}

    _deep_merge(base, override)

    assert base == base_copy
    assert override == override_copy


def test_deep_merge_new_keys_added() -> None:
    """Keys only in override are added to result."""
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_deeply_nested() -> None:
    """Three levels of nesting merge correctly."""
    base = {"a": {"b": {"c": 1, "d": 2}}}
    override = {"a": {"b": {"d": 3, "e": 4}}}
    result = _deep_merge(base, override)
    assert result == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}


# --- load_merged_config tests ---


def test_load_merged_config_no_files(tmp_path: Path) -> None:
    """No config files returns empty dict."""
    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()
    assert result == {}


def test_load_merged_config_base_only(tmp_path: Path) -> None:
    """Only base file returns its contents."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"axe": {"max_runners": 10}}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result == {"axe": {"max_runners": 10}}


def test_load_merged_config_base_plus_overlay(tmp_path: Path) -> None:
    """Overlay is deep-merged on top of base."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"axe": {"max_runners": 10}, "other": "value"}))

    overlay = tmp_path / "sase_work.yml"
    overlay.write_text(yaml.dump({"axe": {"max_runners": 20}}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["axe"]["max_runners"] == 20
    assert result["other"] == "value"


def test_load_merged_config_overlay_order(tmp_path: Path) -> None:
    """Overlays are applied in sorted alphabetical order."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    # sase_a.yml should be applied first, then sase_b.yml
    overlay_a = tmp_path / "sase_a.yml"
    overlay_a.write_text(yaml.dump({"key": "from_a", "only_a": True}))

    overlay_b = tmp_path / "sase_b.yml"
    overlay_b.write_text(yaml.dump({"key": "from_b", "only_b": True}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    # sase_b.yml applied last, so its 'key' wins
    assert result["key"] == "from_b"
    assert result["only_a"] is True
    assert result["only_b"] is True


def test_load_merged_config_list_concatenation(tmp_path: Path) -> None:
    """Lists in overlays are concatenated with base."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"metahooks": [{"name": "a"}]}))

    overlay = tmp_path / "sase_extra.yml"
    overlay.write_text(yaml.dump({"metahooks": [{"name": "b"}]}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["metahooks"] == [{"name": "a"}, {"name": "b"}]


def test_load_merged_config_invalid_yaml_skipped(tmp_path: Path) -> None:
    """Invalid YAML overlay files are skipped."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    bad_overlay = tmp_path / "sase_bad.yml"
    bad_overlay.write_text("invalid: yaml: [not closed")

    good_overlay = tmp_path / "sase_good.yml"
    good_overlay.write_text(yaml.dump({"extra": "value"}))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result["key"] == "base"
    assert result["extra"] == "value"


def test_load_merged_config_non_dict_yaml_skipped(tmp_path: Path) -> None:
    """YAML files containing non-dict top-level values are skipped."""
    base = tmp_path / "sase.yml"
    base.write_text(yaml.dump({"key": "base"}))

    list_overlay = tmp_path / "sase_list.yml"
    list_overlay.write_text(yaml.dump(["just", "a", "list"]))

    with patch("sase.config.CONFIG_DIR", tmp_path):
        result = load_merged_config()

    assert result == {"key": "base"}


def test_config_dir_is_correct() -> None:
    """CONFIG_DIR points to ~/.config/sase."""
    assert CONFIG_DIR == Path.home() / ".config" / "sase"
