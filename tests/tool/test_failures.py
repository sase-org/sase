"""DoD-9 tests for ``sase tool failures``."""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_failures,
    tool_run_finish,
    tool_run_observe,
    tool_run_triage_settle,
)
from sase.tool.failures import ToolFailuresCliRequest, handle_failures


pytestmark = pytest.mark.skipif(
    not hasattr(__import__("sase_core_rs"), "tool_run_failures"),
    reason="tool_run_failures binding is not in this wheel",
)

_DEFINITION = {
    "schema_version": 1,
    "name": "check",
    "argv": ["just", "check"],
    "description": "check",
    "stages": "run_silent",
    "inputs": ["Justfile"],
    "env": [],
    "args": "deny",
    "fingerprint": {"repos": [], "toolchain": {}},
}


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr("sase.tool.failures.tool_project_identity", lambda: "sase")


def _seed_run(
    *,
    project: str,
    tool: str = "check",
    now_ts: int,
    output: str,
    stage_key: str = "lint (mypy)",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    agent: str | None = "agent-1",
) -> str:
    request: dict[str, object] = {
        "schema_version": 1,
        "tool_name": tool,
        "definition": {**_DEFINITION, "name": tool},
        "display_argv": ["just", tool],
        "project": project,
        "workspace": f"{project}-workspace",
        "now_ts": now_ts,
        "commit_running": True,
    }
    if agent:
        request["agent"] = agent
    if owner_kind and owner_id:
        request["owner_kind"] = owner_kind
        request["owner_id"] = owner_id
    run_id = tool_run_begin(request)["run"]["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": project,
                "repos": [
                    {
                        "identity": project,
                        "head": f"{project}-head",
                        "dirty_paths": [],
                    }
                ],
                "completeness": {"complete": True},
            },
        }
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 1,
            "duration_ms": 1,
            "now_ts": now_ts + 1,
        }
    )
    settled = tool_run_triage_settle(
        {
            "run_id": run_id,
            "stages": [
                {
                    "stage_key": stage_key,
                    "stage_id": "stage-1",
                    "output": output,
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": "/tmp/proj",
            "workspace_roots": [],
            "ancestry": [f"{project}-head"],
            "flake_baseline": [],
            "selection_records": [],
            "owner_candidates": [],
            "knobs": {
                "min_witnesses": 1,
                "touched_requires_clean_witness": False,
            },
            "continuation_mode": "never",
            "recipe_finished_ts": now_ts + 2,
            "now_ts": now_ts + 2,
        }
    )
    assert settled["triaged"] is True
    return run_id


def test_failures_json_matches_direct_store_query_and_isolates_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    now = int(time.time())
    _seed_run(
        project="sase",
        now_ts=now - 30,
        output="src/foo.py:10:5: error: Bad thing  [attr-defined]\n",
    )
    _seed_run(
        project="linked-repo",
        now_ts=now - 20,
        output="src/bar.py:1:1: error: Other  [attr-defined]\n",
    )

    code = handle_failures(
        ToolFailuresCliRequest(
            include_all=False,
            class_name=None,
            days=7,
            json=True,
            limit=50,
            tool="check",
        )
    )
    assert code == 0
    envelope = json.loads(capsys.readouterr().out)
    direct = tool_run_failures(
        {
            "project": "sase",
            "tool": "check",
            "days": 7,
            "limit": 50,
            "now_ts": now,
        }
    )
    assert envelope["schema_version"] == 1
    assert [group["signature"] for group in envelope["groups"]] == [
        group["signature"] for group in direct["groups"]
    ]
    assert envelope["groups"]
    assert all(group["project"] == "sase" for group in envelope["groups"])
    assert all(group["tool"] == "check" for group in envelope["groups"])


def test_failures_empty_human_exits_0(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    code = handle_failures(
        ToolFailuresCliRequest(
            include_all=False,
            class_name=None,
            days=7,
            json=False,
            limit=50,
            tool=None,
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "no recorded failures"


def test_failures_human_table_and_class_filter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _home(monkeypatch, tmp_path)
    _seed_run(
        project="sase",
        now_ts=int(time.time()) - 30,
        output="src/foo.py:10:5: error: Bad thing  [attr-defined]\n",
    )
    assert (
        handle_failures(
            ToolFailuresCliRequest(
                include_all=False,
                class_name="unknown",
                days=7,
                json=False,
                limit=50,
                tool=None,
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "CLASS" in output
    assert "UNKNOWN" in output
    assert "check / lint (mypy)" in " ".join(output.split())
    assert "src/foo.py" in output

    assert (
        handle_failures(
            ToolFailuresCliRequest(
                include_all=False,
                class_name="new",
                days=7,
                json=False,
                limit=50,
                tool=None,
            )
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == "no recorded failures"


def test_failures_limit_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = handle_failures(
        ToolFailuresCliRequest(
            include_all=False,
            class_name=None,
            days=7,
            json=False,
            limit=0,
            tool=None,
        )
    )
    assert code == 2
    assert "limit" in capsys.readouterr().err
