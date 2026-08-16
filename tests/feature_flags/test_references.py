"""Tests for feature-flag call-site discovery."""

from __future__ import annotations

from pathlib import Path

from sase.feature_flags.references import find_flag_call_sites


def test_find_flag_call_sites_locates_enum_and_enabled_uses(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from sase.feature_flags import FeatureFlag\n"
        "from sase.feature_flags.snapshot import current_flags\n"
        "\n"
        "def use_flag() -> bool:\n"
        "    return current_flags().enabled(FeatureFlag.demo_flag)\n",
        encoding="utf-8",
    )
    (tmp_path / "feature_flags").mkdir()
    (tmp_path / "feature_flags" / "registry.py").write_text(
        "class FeatureFlag:\n    demo_flag = 'demo_flag'\n",
        encoding="utf-8",
    )

    sites = find_flag_call_sites("demo_flag", root=tmp_path)

    assert any(site.path == "consumer.py" for site in sites)
    assert not any(site.path.endswith("registry.py") for site in sites)


def test_find_flag_call_sites_returns_empty_when_unused(tmp_path: Path) -> None:
    (tmp_path / "other.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert find_flag_call_sites("demo_flag", root=tmp_path) == ()
