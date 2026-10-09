"""PyPI-run lifecycle tests (scheduler, quiet/JSON, no-op, force).

Split from ``tests.sase_install.test_run_pypi``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tests.sase_install._run_pypi_harness import Harness, install_run


def test_scheduler_restart_runs_when_scheduler_is_live(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    axe_dir = harness.sase_home / "axe"
    axe_dir.mkdir(parents=True, exist_ok=True)
    (axe_dir / "orchestrator.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert install_run.scheduler_running(harness.sase_home) is True

    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "✓ Restart the scheduler — scheduler restarted" in err
    capture = Path(harness.env["SASE_CAPTURE"])
    assert capture.is_file() and "scheduler-restart" in capture.read_text()


def test_scheduler_restart_skipped_when_idle(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    assert install_run.scheduler_running(harness.sase_home) is False
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "scheduler was not running" in err
    assert not Path(harness.env["SASE_CAPTURE"]).exists()


def test_scheduler_restart_failure_warns_without_failing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    axe_dir = harness.sase_home / "axe"
    axe_dir.mkdir(parents=True, exist_ok=True)
    (axe_dir / "orchestrator.pid").write_text(str(os.getpid()), encoding="utf-8")
    harness.env["FAKE_RESTART_EXIT"] = "1"
    exit_code, _, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "scheduler restart failed" in err


def test_quiet_prints_only_the_summary(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["pypi", "-y", "-q"])
    assert exit_code == 0
    assert err == ""
    assert len(out.splitlines()) == 1
    assert out.startswith("just install: ")


def test_json_reports_success_with_log_path(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["pypi", "-y", "-j"])
    assert exit_code == 0
    assert err == ""
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["dry_run"] is False
    assert doc["outcome"] == "success"
    assert doc["log_path"].endswith(".log")
    assert Path(doc["log_path"]).is_file()
    assert doc["steps"] == [
        "preflight",
        "plan",
        "confirm",
        "lock",
        "swap",
        "verify",
        "restart",
        "summary",
    ]


def test_json_reports_failure_with_error(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["UV_EXIT"] = "3"
    exit_code, out, err = harness.run(["pypi", "-y", "-j"])
    assert exit_code == 1
    doc = json.loads(out)
    assert doc["outcome"] == "failed"
    assert "Swap" in (doc["error"] or "")
    assert doc["log_path"].endswith(".log")
    assert "✗ Swap failed" in err


def test_noop_when_current_and_healthy(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    exit_code, out, err = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert (
        "✓ sase 0.17.1 from PyPI is already installed — nothing to do "
        "(--force reinstalls)" in out
    )
    assert harness.swap_argvs() == []  # no swap ran
    assert harness.log_files() != []  # the run is still logged


def test_noop_skipped_when_health_fails(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    harness.env["FAKE_HEALTH_EXIT"] = "1"
    # The reinstall heals the install: the fake uv drops this marker on a
    # successful swap, and the fake sase answers healthy once it exists.
    harness.env["HEALTH_MARKER"] = str(tmp_path / "health-marker")
    exit_code, out, _ = harness.run(["pypi", "-y"])
    assert exit_code == 0
    assert "is installed" in out  # full pipeline ran instead of the no-op
    assert len(harness.swap_argvs()) == 1


def test_force_reinstalls_when_current(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness._write_tool_env(host=("pypi", "0.17.1"), core=("pypi", "0.35.4"))
    exit_code, _, _ = harness.run(["pypi", "-y", "--force"])
    assert exit_code == 0
    assert len(harness.swap_argvs()) == 1
