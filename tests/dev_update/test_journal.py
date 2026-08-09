"""Tests for dev-update execution journaling."""

from __future__ import annotations

import json
from pathlib import Path

from sase.dev_update.journal import (
    ENV_MAX_BYTES,
    _dev_update_journal_record,
    append_dev_update_journal,
)
from sase.dev_update.models import (
    DevExecutedCommand,
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.axe.process import AxeStartAttempt
from sase.main.update_types import RestartInfo
from sase.version._models import VersionPackageRecord


def _record() -> VersionPackageRecord:
    return VersionPackageRecord(
        name="sase",
        role="host",
        display_version="0.5.0+1.gaaaaaaaaa",
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root="/repo/sase",
        distribution_location=None,
        install_type="editable",
        git=None,
    )


def _plan() -> DevUpdatePlan:
    record = _record()
    package = DevUpdatePackagePlan(
        record=record,
        status="actionable",
        reason="behind upstream by 1 commit(s)",
        current_version="0.5.0+1.gaaaaaaaaa",
        latest_version="0.5.0+2.gbbbbbbbbb",
        git_root="/repo/sase",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        ahead=0,
        behind=1,
        fetch_error="network down",
    )
    return DevUpdatePlan(
        packages=(package,),
        roots=(
            DevUpdateRootPlan(
                git_root="/repo/sase",
                status="actionable",
                reason=package.reason,
                upstream="origin/main",
                remote="origin",
                remote_branch="main",
                packages=("sase",),
                fetch_error="network down",
            ),
        ),
        reconcile_steps=(
            DevReconcileStep(
                kind="rust_health_check",
                label="Verify sase-core-rs imports in the uv-tool venv",
                command=("/tool/bin/python", "-c", "import sase_core_rs"),
                repair_command=(
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    "/tool/bin/python",
                    "--force-reinstall",
                    "sase-core-rs<0.4.0,>=0.3.2",
                ),
                repair_label="Restore published sase-core-rs wheel",
            ),
        ),
    )


def _result(plan: DevUpdatePlan) -> DevUpdateResult:
    package = plan.packages[0]
    return DevUpdateResult(
        changed=True,
        outcomes=(
            DevUpdateOutcome(
                record=package.record,
                status="failed",
                reason="environment restored to published sase-core-rs 0.3.7",
                old_version=package.current_version,
                new_version=package.latest_version,
                git_root=package.git_root,
            ),
        ),
        commands=(
            DevExecutedCommand(
                label="Restore published sase-core-rs wheel",
                command=("uv", "pip", "install", "sase-core-rs"),
                cwd=None,
                returncode=0,
                duration_seconds=294.25,
                stdout="x" * 13_000,
                stderr="",
            ),
        ),
        duration_seconds=301.5,
    )


def test_dev_update_journal_record_summarizes_plan_result_and_command_tails() -> None:
    plan = _plan()
    record = _dev_update_journal_record(plan, _result(plan))

    assert record["schema_version"] == 2
    assert record["plan"]["packages"][0]["fetch_error"] == "network down"
    assert record["plan"]["roots"][0]["fetch_error"] == "network down"
    assert record["plan"]["reconcile_steps"][0]["kind"] == "rust_health_check"
    assert record["plan"]["reconcile_steps"][0]["repair_command"][-1] == (
        "sase-core-rs<0.4.0,>=0.3.2"
    )
    assert record["result"]["status"] == "failed"
    assert record["result"]["duration_seconds"] == 301.5
    assert record["result"]["counts"] == {"updated": 0, "skipped": 0, "failed": 1}
    assert record["commands"][0]["duration_seconds"] == 294.25
    assert len(record["commands"][0]["stdout_tail"]) == 12_000


def test_append_dev_update_journal_writes_jsonl(tmp_path: Path) -> None:
    plan = _plan()
    path = tmp_path / "logs" / "dev_update.jsonl"

    restart = RestartInfo(
        attempted=True,
        status="restarted",
        pid=2468,
        message="Axe restarted (pid 2468)",
        verified=True,
        attempts=(
            AxeStartAttempt(
                number=1,
                status="started",
                pid=2468,
                message="started",
                verified=True,
            ),
        ),
    )

    written = append_dev_update_journal(
        plan,
        _result(plan),
        restart=restart,
        path=path,
    )

    assert written == path
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["result"]["outcomes"][0]["name"] == "sase"
    assert payload["restart"]["status"] == "restarted"
    assert payload["restart"]["verified"] is True
    assert payload["restart"]["attempts"][0]["pid"] == 2468


def test_append_dev_update_journal_rotates_existing_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "logs" / "dev_update.jsonl"
    path.parent.mkdir()
    path.write_text('{"generation":"current"}\n', encoding="utf-8")
    rotated = path.with_name(f"{path.name}.1")
    rotated.write_text('{"generation":"stale-backup"}\n', encoding="utf-8")
    monkeypatch.setenv(ENV_MAX_BYTES, "1")

    assert append_dev_update_journal(_plan(), _result(_plan()), path=path) == path

    assert json.loads(rotated.read_text(encoding="utf-8")) == {"generation": "current"}
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    assert not path.with_name(f"{path.name}.2").exists()
