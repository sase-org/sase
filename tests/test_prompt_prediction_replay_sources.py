"""Contract tests for the replay tool's archive-source selection."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    script = ROOT / "tools" / "prompt_prediction_replay"
    loader = SourceFileLoader("prompt_prediction_replay_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "prompt_prediction_replay_tool", script, loader=loader
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_sources_history_only() -> None:
    module = _load()
    assert module._check_sources("history") == ["history"]


def test_sources_history_and_archive() -> None:
    module = _load()
    assert module._check_sources("history,archive") == ["history", "archive"]


def test_sources_rejects_unknown_and_archive_only() -> None:
    module = _load()
    with pytest.raises(SystemExit) as unknown:
        module._check_sources("history,common-sense")
    assert unknown.value.code == 2
    with pytest.raises(SystemExit) as solo:
        module._check_sources("archive")
    assert solo.value.code == 2


def test_score_every_defaults_to_every_row() -> None:
    module = _load()
    assert module._parse_args([]).score_every == 1
    assert module._parse_args(["--score-every", "6"]).score_every == 6
