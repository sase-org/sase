"""Contract tests for the replay tool's archive-source selection."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from sase.core.prompt_prediction_wire import PromptPredictionRow

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


def test_percentile_indexes_sorted_samples() -> None:
    module = _load()
    samples = [float(value) for value in range(1, 101)]
    assert module._percentile(samples, 50) == 51.0
    assert module._percentile(samples, 95) == 96.0
    assert module._percentile([], 95) == 0.0


def test_bench_prints_aggregates_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    rows = [
        PromptPredictionRow(
            text=f"please look at the parser and fix bench{index} today",
            epoch_seconds=100 + index,
            project="sase",
            origin="typed",
        )
        for index in range(8)
    ]
    monkeypatch.setattr(
        module,
        "build_prompt_prediction_project_resolver",
        lambda: SimpleNamespace(resolve=lambda _cwd: None),
    )
    monkeypatch.setattr(module, "build_prompt_prediction_rows", lambda **_kwargs: rows)
    monkeypatch.setattr(module, "load_deleted_prompt_words", lambda: set())

    assert module.main(["--bench", "--bench-samples", "8"]) == 0

    out = capsys.readouterr().out
    assert "rows_total=8 rows_used=8" in out
    assert "sampled=8 blocked=0" in out
    assert "predict_p95_ms=" in out
    assert "ghost_p95_ms=" in out
    assert "rank_p95_ms=" in out
    assert "parser" not in out
