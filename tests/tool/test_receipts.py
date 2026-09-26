"""E4 receipt-execution-cli: mint on both execution paths plus receipt query."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list, tool_run_receipt_settle
from sase.tool.adopt import execute_adopted_run
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.handoff import reserve_handoff_run
from sase.tool.receipt_query import ToolReceiptCliRequest, handle_receipt
from sase.tool.receipts import settle_receipt_for_run


def _receipt_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Create an isolated git project with a tiny receipt-policy tool.

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
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    clear_config_cache()
    return repo


def _run_tiny() -> int:
    return execute_tool_run(
        ToolRunCliRequest(
            quiet=True,
            verbose=False,
            tail_lines=200,
            words=("tiny",),
        )
    )


def test_foreground_pass_mints_and_query_covers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A passing foreground run mints; the query exits 0 with proof fields."""

    _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 0
    captured = capsys.readouterr()
    assert "covered: tiny" in captured.out
    assert "receipt:" in captured.out
    assert "run:" in captured.out
    assert "verdict: pass" in captured.out
    assert "age:" in captured.out


def test_query_json_is_versioned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Covered JSON carries schema_version 1 and the receipt proof."""

    _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny", json=True)) == 0
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert envelope["schema_version"] == 1
    assert envelope["outcome"] == "covered"
    assert envelope["receipt"]["verdict"] == "pass"
    assert envelope["receipt"]["receipt_id"]
    assert envelope["receipt"]["source_run_id"]
    assert isinstance(envelope["age_seconds"], int)


def test_no_new_accept_still_covers_pass_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`-a no-new` accepts the pass receipt (pass is always acceptable)."""

    _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny", accept="no-new")) == 0
    capsys.readouterr()


def test_tree_drift_refuses_with_changed_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Touching a tracked tree refuses with `fingerprint_changed: <path>`."""

    repo = _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    (repo / "drift.txt").write_text("drift", encoding="utf-8")
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 1
    captured = capsys.readouterr()
    assert "fingerprint_changed" in captured.out
    assert "drift.txt" in captured.out


def test_query_json_refusal_is_versioned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Refusal JSON carries schema_version 1 and the typed refusal."""

    repo = _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    (repo / "drift.txt").write_text("drift", encoding="utf-8")
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny", json=True)) == 1
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert envelope["schema_version"] == 1
    assert envelope["outcome"] == "refused"
    assert envelope["refusal"] == "fingerprint_changed"
    assert any("drift.txt" in path for path in envelope["changed_paths"])


def test_handoff_worker_mints_like_foreground(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The claimed hand-off worker settles the same receipt as foreground."""

    _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 0
    capsys.readouterr()
    resolved = resolve_run_argv(["tiny"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved, reservation.error
    monkeypatch.setenv("SASE_PROC_ID", "proc-1")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", str(tmp_path / "owner.log"))
    assert execute_adopted_run(reservation.run_id) == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 0
    captured = capsys.readouterr()
    assert "covered: tiny" in captured.out


def test_every_run_still_spawns_despite_covering_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A covering receipt never skips the child: the marker proves execution."""

    repo = _receipt_project(monkeypatch, tmp_path)
    marker = tmp_path / "ran.marker"
    (repo / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "tiny": {
                        "argv": [
                            "sh",
                            "-c",
                            f"echo ran >> {marker}; exit 0",
                        ],
                        "args": "deny",
                        "receipt": {"accept": ["pass"], "ttl": "2h"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "marker tool"], cwd=repo, check=True)
    clear_config_cache()
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 0
    capsys.readouterr()
    assert _run_tiny() == 0
    assert marker.read_text(encoding="utf-8").count("ran") == 2


def test_adhoc_run_mints_no_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ad-hoc runs leave no receipt row behind."""

    _receipt_project(monkeypatch, tmp_path)
    adhoc_code = execute_tool_run(
        ToolRunCliRequest(
            quiet=True,
            verbose=False,
            tail_lines=200,
            words=("--", "true"),
        )
    )
    assert adhoc_code == 0
    resolved = resolve_run_argv(["--", "true"])
    assert resolved.adhoc is True
    newest = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]
    result = settle_receipt_for_run(newest["run_id"], resolved)
    direct = tool_run_receipt_settle(
        {
            "run_id": newest["run_id"],
            "policy": {
                "schema_version": 1,
                "accept": ["pass"],
                "ttl": "2h",
            },
            "bypassed": False,
        }
    )
    assert result is not None
    assert result["minted"] is False
    assert direct["minted"] is False
    assert direct["reason"] == "ad-hoc run"


def test_bypassed_run_mints_no_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bypassed invocation executes but never mints."""

    _receipt_project(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_TOOL_BYPASS", "manual bypass probe")
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 1
    captured = capsys.readouterr()
    assert "no_receipt" in captured.out


def test_partial_ledger_write_fails_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unwritable store never raises out of receipt settlement."""

    _receipt_project(monkeypatch, tmp_path)
    resolved = resolve_run_argv(["tiny"])
    assert (
        settle_receipt_for_run("missing-run", resolved, store_path=str(tmp_path))
        is None
    )


def test_missing_binding_fails_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale wheel without the receipt binding never breaks execution."""

    _receipt_project(monkeypatch, tmp_path)
    resolved = resolve_run_argv(["tiny"])

    def _stale(*args: object, **kwargs: object) -> object:
        raise AttributeError("no binding tool_run_receipt_settle")

    monkeypatch.setattr("sase.tool.receipts.tool_run_receipt_settle", _stale)
    assert settle_receipt_for_run("any-run", resolved) is None


def test_query_unknown_tool_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown tool name is a usage error, not a refusal."""

    _receipt_project(monkeypatch, tmp_path)
    assert handle_receipt(ToolReceiptCliRequest(tool="nope")) == 2
    capsys.readouterr()


def test_query_names_no_landing_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The query never claims the landing gate is satisfied."""

    _receipt_project(monkeypatch, tmp_path)
    assert _run_tiny() == 0
    capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny")) == 0
    covered = capsys.readouterr()
    assert handle_receipt(ToolReceiptCliRequest(tool="tiny", json=True)) == 0
    covered_json = capsys.readouterr()
    blob = covered.out + covered_json.out
    assert "landing" not in blob.lower()
    assert "satisf" not in blob.lower()


def test_receipt_settle_request_rejects_empty_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Rust contract validates the settle wire before touching the store."""

    _receipt_project(monkeypatch, tmp_path)
    with pytest.raises(Exception, match="run_id must not be empty"):
        tool_run_receipt_settle({"run_id": "   ", "bypassed": False})
