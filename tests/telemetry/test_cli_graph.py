"""Tests for ``sase telemetry graph``."""

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser
from sase.telemetry.cli_graph import handle_telemetry_graph
from tests.telemetry.conftest import record_samples, use_store


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "metric": "sase_llm_input_tokens_total",
        "aggregation": "sum",
        "group_by": "provider",
        "no_color": True,
        "range": "15m",
        "width": 70,
    }
    values.update(overrides)
    return Namespace(**values)


def test_graph_renders_grouped_local_series(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    use_store(store_path)
    record_samples(
        store_path,
        [
            {
                "ts": 100,
                "metric": "sase_llm_input_tokens_total",
                "kind": "counter",
                "labels": {"provider": "codex"},
                "source": "runner-1",
                "value": 100,
            },
            {
                "ts": 160,
                "metric": "sase_llm_input_tokens_total",
                "kind": "counter",
                "labels": {"provider": "codex"},
                "source": "runner-1",
                "value": 200,
            },
        ],
        now_ts=200,
    )

    with patch("sase.telemetry.cli_graph.time.time", return_value=200):
        handle_telemetry_graph(_args())

    output = capsys.readouterr().out
    assert "sase_llm_input_tokens_total · sum" in output
    assert "provider=codex" in output
    assert "\x1b[" not in output


def test_graph_accepts_catalog_attribute_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    use_store(tmp_path / "metrics.sqlite")

    with patch("sase.telemetry.cli_graph.time.time", return_value=200):
        handle_telemetry_graph(_args(metric="LLM_INPUT_TOKENS"))

    assert "sase_llm_input_tokens_total" in capsys.readouterr().out


def test_graph_rejects_unknown_metric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    use_store(tmp_path / "metrics.sqlite")

    with pytest.raises(SystemExit, match="2"):
        handle_telemetry_graph(_args(metric="does_not_exist"))

    assert "Unknown telemetry metric" in capsys.readouterr().out


def test_graph_parser_exposes_new_options_and_removes_dashboard_sources() -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "telemetry",
            "graph",
            "sase_agent_runs_total",
            "-a",
            "rate",
            "-g",
            "status",
            "-n",
            "-r",
            "6h",
            "-w",
            "100",
        ]
    )

    assert args.telemetry_subcommand == "graph"
    assert args.aggregation == "rate"
    assert args.group_by == "status"
    assert args.no_color is True
    assert args.range == "6h"
    assert args.width == 100

    dashboard = parser.parse_args(["telemetry", "dashboard"])
    assert not hasattr(dashboard, "charts")
    assert not hasattr(dashboard, "source")
