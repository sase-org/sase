"""Absence coverage for the abandoned coder_inherits_planner_chat beta."""

from __future__ import annotations

from pathlib import Path

from sase.feature_flags import FeatureFlag
from sase.feature_flags.registry import feature_flag_definitions


def test_coder_inherits_planner_chat_flag_is_unregistered() -> None:
    assert "coder_inherits_planner_chat" not in FeatureFlag.__members__
    assert "coder_inherits_planner_chat" not in feature_flag_definitions()


def test_source_tree_has_no_coder_inherits_planner_chat_definition() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "sase"
    matches: list[str] = []
    for path in root.rglob("*"):
        if path.suffix not in {".py", ".yml", ".yaml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "coder_inherits_planner_chat" in text:
            matches.append(str(path.relative_to(root.parents[1])))
    assert matches == []
