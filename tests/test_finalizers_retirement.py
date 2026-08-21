"""Absence coverage for the retired pluggable_finalizers Off path."""

from __future__ import annotations

from pathlib import Path

from sase.feature_flags import FeatureFlag
from sase.feature_flags.registry import feature_flag_definitions


def test_pluggable_finalizers_flag_is_unregistered() -> None:
    assert "pluggable_finalizers" not in FeatureFlag.__members__
    assert "pluggable_finalizers" not in feature_flag_definitions()


def test_source_tree_has_no_pluggable_finalizers_definition() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sase"
    matches: list[str] = []
    for path in root.rglob("*"):
        if path.suffix not in {".py", ".yml", ".yaml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "pluggable_finalizers" in text:
            matches.append(str(path.relative_to(root.parents[1])))
    assert matches == []
