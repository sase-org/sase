"""E4 opportunity-report: receipts list plus content-equivalent repeats."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.feature_flags import override_flags
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.receipt_report import ToolReceiptsCliRequest, handle_receipts


def _report_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Create an isolated git project with receipt-policy tools.

    ``SASE_HOME`` lives outside the repo so store writes never dirty the
    fingerprinted tree between the before/after observations of one run.
    """

    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_BYPASS",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(repo))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.example"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "sase").mkdir()
    (repo / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "tiny": {
                        "argv": ["true"],
                        "args": "deny",
                        "receipt": {"accept": ["pass"], "ttl": "2h"},
                    },
                    "brokentc": {
                        "argv": ["true"],
                        "args": "deny",
                        "fingerprint": {
                            "toolchain": {"absent": ["definitely-absent-probe-xyz"]}
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    clear_config_cache()
    return repo


def _run(name: str) -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=True,
            verbose=False,
            tail_lines=200,
            words=(name,),
        )
    )


def _report_json(
    capsys: pytest.CaptureFixture[str],
    **kwargs: object,
) -> dict[str, object]:
    params = {"days": 7, "json": True}
    params.update(kwargs)
    assert handle_receipts(ToolReceiptsCliRequest(**params)) == 0  # type: ignore[arg-type]
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_empty_store_reports_zero_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No runs yet: exit 0 with empty receipts and no opportunities."""

    _report_project(monkeypatch, tmp_path)
    assert handle_receipts(ToolReceiptsCliRequest(days=7, json=False)) == 0
    captured = capsys.readouterr()
    assert "no recorded receipts" in captured.out
    assert "no content-equivalent repeats" in captured.out
    assert "still\nexecutes" in captured.out or "still executes" in captured.out


def test_negative_days_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Negative --days exits 2 without touching the ledger."""

    _report_project(monkeypatch, tmp_path)
    assert handle_receipts(ToolReceiptsCliRequest(days=-1, json=False)) == 2
    captured = capsys.readouterr()
    assert "-d/--days must be >= 0" in captured.err


def test_identical_repeats_group_together(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two runs on the same tree form one group with one repeat."""

    _report_project(monkeypatch, tmp_path)
    with override_flags(tool_receipts=True):
        assert _run("tiny") == 0
        assert _run("tiny") == 0
        capsys.readouterr()
        assert handle_receipts(ToolReceiptsCliRequest(days=7, json=False)) == 0
        human = capsys.readouterr().out
        envelope = _report_json(capsys)
    assert "1 groups" in human
    assert "1 repeat runs" in human
    assert envelope["schema_version"] == 1
    receipts = envelope["receipts"]
    assert isinstance(receipts, dict) and receipts["count"] >= 1
    opportunities = envelope["opportunities"]
    assert isinstance(opportunities, dict)
    assert opportunities["group_count"] == 1
    assert opportunities["repeat_runs"] == 1
    assert opportunities["repeat_duration_ms"] >= 0
    groups = opportunities["groups"]
    assert isinstance(groups, list) and len(groups) == 1
    assert groups[0]["tool"] == "tiny"
    assert groups[0]["runs"] == 2
    assert groups[0]["spans_commits"] is False
    top_tools = opportunities["top_tools"]
    assert isinstance(top_tools, list) and top_tools[0]["tool"] == "tiny"
    assert top_tools[0]["repeat_runs"] == 1
    uncomparable = envelope["uncomparable"]
    assert isinstance(uncomparable, dict) and uncomparable["count"] == 0
    assert "measurement only" in str(envelope["note"])


def test_dirty_tree_committed_counts_as_opportunity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dirty run committed and rechecked at a new HEAD is equivalent."""

    repo = _report_project(monkeypatch, tmp_path)
    with override_flags(tool_receipts=True):
        (repo / "tracked.txt").write_text("v2\n", encoding="utf-8")
        assert _run("tiny") == 0
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "v2"], cwd=repo, check=True)
        assert _run("tiny") == 0
        capsys.readouterr()
        envelope = _report_json(capsys)
    opportunities = envelope["opportunities"]
    assert isinstance(opportunities, dict)
    assert opportunities["group_count"] == 1
    assert opportunities["repeat_runs"] == 1
    groups = opportunities["groups"]
    assert isinstance(groups, list) and len(groups) == 1
    assert groups[0]["spans_commits"] is True


def test_incomplete_fingerprint_is_uncomparable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run with a failed toolchain probe is reported, never guessed."""

    _report_project(monkeypatch, tmp_path)
    with override_flags(tool_receipts=True):
        assert _run("brokentc") == 0
        capsys.readouterr()
        envelope = _report_json(capsys)
    uncomparable = envelope["uncomparable"]
    assert isinstance(uncomparable, dict) and uncomparable["count"] == 1
    runs = uncomparable["runs"]
    assert isinstance(runs, list) and runs[0]["tool"] == "brokentc"
    assert "incomplete fingerprint" in runs[0]["reason"]
    opportunities = envelope["opportunities"]
    assert isinstance(opportunities, dict) and opportunities["group_count"] == 0
