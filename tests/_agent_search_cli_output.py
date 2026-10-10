from __future__ import annotations

import argparse
import json
from typing import Any

from sase.agents.cli_search import handle_agents_search
from tests._agent_search_cli_helpers import patch_sources, make_row, make_snapshot


def test_agent_search_pretty_output_smoke(monkeypatch: Any, capsys: Any) -> None:
    snapshot = make_snapshot(make_row("visible", status="RUNNING", model="gpt-5"))
    patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=False, limit=10, project=None, query=["status:RUNNING"])
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Agent Catalog Search" in output
    assert "visible" in output
    assert "RUNNING" in output


def test_agent_search_warns_when_catalog_enrichment_is_degraded(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    snapshot = make_snapshot(
        make_row("visible"),
        diagnostics=("agent artifact index schema 999 is unsupported",),
    )
    patch_sources(monkeypatch, snapshot)

    code = handle_agents_search(
        argparse.Namespace(json=True, limit=0, project=None, query=[])
    )

    captured = capsys.readouterr()
    stderr = " ".join(captured.err.split())
    assert code == 0
    assert json.loads(captured.out)[0]["name"] == "visible"
    assert "agent search enrichment degraded" in stderr
    assert "schema 999 is unsupported" in stderr
