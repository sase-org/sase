"""Identity-checked, handoff-aware VCS workspace release."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.pending_handoff import PENDING_HANDOFF_MARKERS
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.scripts import git_release
from sase.workspace_provider.occupant import (
    new_occupant_record,
    read_occupant_record,
    write_occupant_record,
)
from sase.workspace_provider.vcs_release import (
    SKIP_HANDOFF,
    SKIP_NO_MATCHING_CLAIM,
    SKIP_PID_MISMATCH,
    VcsReleaseResult,
    release_vcs_workspace,
)
from tests._running_field_helpers import create_project_file_with_running

_WORKFLOW = "gh-acme/widget"
_CALLER = "gh-release"


def _isolate_ledger(tmp_path: Path) -> object:
    return patch(
        "sase.logs.workspace_claim_ledger.LEDGER_FILE",
        str(tmp_path / "workspace_claims.jsonl"),
    )


def _claim(*, pid: int, workspace_num: int = 23) -> WorkspaceClaim:
    return WorkspaceClaim(workspace_num, _WORKFLOW, None, pid=pid)


def _write_occupant(checkout: Path, pid: int, workspace_num: int = 23) -> None:
    write_occupant_record(
        str(checkout),
        new_occupant_record(
            pid=pid,
            workflow=_WORKFLOW,
            project="widget",
            workspace_num=workspace_num,
        ),
    )


def _release(
    project_file: str,
    checkout: Path,
    *,
    runner_pid: int,
    artifacts_dir: str | None = None,
    caller_tag: str = _CALLER,
) -> VcsReleaseResult:
    return release_vcs_workspace(
        project_file=project_file,
        workspace_num=23,
        workspace_dir=str(checkout),
        workflow_name=_WORKFLOW,
        cl_name=None,
        caller_tag=caller_tag,
        runner_pid=runner_pid,
        artifacts_dir=artifacts_dir,
    )


class TestHandoffSkipsRelease:
    @pytest.mark.parametrize("marker", PENDING_HANDOFF_MARKERS)
    def test_each_handoff_kind_skips_release_and_occupant(
        self, tmp_path: Path, marker: str
    ) -> None:
        runner_pid = os.getpid()
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[_claim(pid=runner_pid)]
        )
        checkout = tmp_path / "ws_23"
        checkout.mkdir()
        _write_occupant(checkout, runner_pid)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        (artifacts / marker).write_text("{}", encoding="utf-8")
        ledger_file = str(tmp_path / "workspace_claims.jsonl")

        with _isolate_ledger(tmp_path):
            result = _release(
                project_file,
                checkout,
                runner_pid=runner_pid,
                artifacts_dir=str(artifacts),
            )
            records = read_ledger_records(ledger_file=ledger_file)

        assert result.released is False
        assert result.occupant_cleared is False
        assert result.skip_reason == SKIP_HANDOFF
        assert [c.workspace_num for c in get_claimed_workspaces(project_file)] == [23]
        occupant = read_occupant_record(str(checkout))
        assert occupant is not None
        assert occupant.pid == runner_pid
        assert records
        assert all(record["success"] is False for record in records)
        assert all(record["caller_tag"] == _CALLER for record in records)
        assert any("handed off" in (record["error"] or "") for record in records)

    def test_no_handoff_releases_exactly_once(self, tmp_path: Path) -> None:
        runner_pid = os.getpid()
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[_claim(pid=runner_pid)]
        )
        checkout = tmp_path / "ws_23"
        checkout.mkdir()
        _write_occupant(checkout, runner_pid)
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        ledger_file = str(tmp_path / "workspace_claims.jsonl")

        with _isolate_ledger(tmp_path):
            first = _release(
                project_file,
                checkout,
                runner_pid=runner_pid,
                artifacts_dir=str(artifacts),
            )
            second = _release(
                project_file,
                checkout,
                runner_pid=runner_pid,
                artifacts_dir=str(artifacts),
            )
            records = read_ledger_records(ledger_file=ledger_file)

        assert first.released is True
        assert first.occupant_cleared is True
        assert first.skip_reason is None
        assert second.released is False
        assert second.skip_reason == SKIP_NO_MATCHING_CLAIM
        assert get_claimed_workspaces(project_file) == []
        assert read_occupant_record(str(checkout)) is None
        successes = [record for record in records if record["success"] is True]
        assert len(successes) == 1
        assert successes[0]["operation"] == "release"
        assert successes[0]["caller_tag"] == _CALLER


class TestIdentityChecks:
    def test_foreign_running_pid_leaves_claim(self, tmp_path: Path) -> None:
        runner_pid = os.getpid()
        foreign_pid = runner_pid + 1
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[_claim(pid=foreign_pid)]
        )
        checkout = tmp_path / "ws_23"
        checkout.mkdir()
        _write_occupant(checkout, runner_pid)
        ledger_file = str(tmp_path / "workspace_claims.jsonl")

        with _isolate_ledger(tmp_path):
            result = _release(project_file, checkout, runner_pid=runner_pid)
            records = read_ledger_records(ledger_file=ledger_file)

        assert result.released is False
        assert result.skip_reason == SKIP_PID_MISMATCH
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == foreign_pid
        assert read_occupant_record(str(checkout)) is None
        assert any(
            record["success"] is False and "pid mismatch" in (record["error"] or "")
            for record in records
        )

    def test_foreign_occupant_pid_leaves_marker(self, tmp_path: Path) -> None:
        runner_pid = os.getpid()
        foreign_pid = runner_pid + 1
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[_claim(pid=runner_pid)]
        )
        checkout = tmp_path / "ws_23"
        checkout.mkdir()
        _write_occupant(checkout, foreign_pid)
        ledger_file = str(tmp_path / "workspace_claims.jsonl")

        with _isolate_ledger(tmp_path):
            result = _release(project_file, checkout, runner_pid=runner_pid)
            records = read_ledger_records(ledger_file=ledger_file)

        assert result.released is True
        assert result.occupant_cleared is False
        assert get_claimed_workspaces(project_file) == []
        occupant = read_occupant_record(str(checkout))
        assert occupant is not None
        assert occupant.pid == foreign_pid
        assert any(
            record["success"] is False
            and "occupant record pid" in (record["error"] or "")
            for record in records
        )

    def test_git_release_step_prints_released_true(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        runner_pid = os.getppid()
        project_file = create_project_file_with_running(
            tmp_path, running_claims=[_claim(pid=runner_pid)]
        )
        checkout = tmp_path / "ws_23"
        checkout.mkdir()
        _write_occupant(checkout, runner_pid)

        with _isolate_ledger(tmp_path):
            git_release.main(
                project_file=project_file,
                workspace_num=23,
                workspace_dir=str(checkout),
                workflow_name=_WORKFLOW,
                cl_name=None,
            )

        out = capsys.readouterr().out
        assert "released=true" in out
        assert get_claimed_workspaces(project_file) == []
        assert read_occupant_record(str(checkout)) is None


def test_git_yml_release_step_delegates_to_git_release() -> None:
    git_yml = (
        Path(__file__).resolve().parents[2] / "src" / "sase" / "xprompts" / "git.yml"
    )
    text = git_yml.read_text(encoding="utf-8")
    assert "from sase.scripts.git_release import main" in text
    assert "workspace_dir={{ setup.workspace_dir | tojson }}" in text
    assert "release_workspace(" not in text
    git_release_src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sase"
        / "scripts"
        / "git_release.py"
    )
    assert '_CALLER_TAG = "git-release"' in git_release_src.read_text(encoding="utf-8")
