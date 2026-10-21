from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests._github_actions_ci_helpers import job_run_text
from tests._github_actions_ci_helpers import load_core_pin_ratchet_workflow
from tests._github_actions_ci_helpers import load_shard_timings_ratchet_workflow
from tests._github_actions_ci_helpers import workflow_triggers
from tests._test_shards import SHARD_TIMINGS_ARTIFACT_NAME

pytestmark = pytest.mark.contract

_RATCHET_NEW_SHA = "0123456789abcdef0123456789abcdef01234567"
_RATCHET_OLD_SHA = "f" * 40
_RATCHET_BRANCH = "core-pin-ratchet"


def test_core_pin_ratchet_runs_on_schedule_not_push() -> None:
    """The ratchet must never itself be a push-path gate.

    It only ever opens a PR, which then runs the normal per-ref CI, so a
    pinned revision that would break sase cannot merge silently.
    """
    workflow = load_core_pin_ratchet_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "push" not in triggers
    assert workflow["concurrency"] == {
        "group": "core-pin-ratchet",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}


def test_core_pin_ratchet_uses_the_shared_tool_and_names_the_pin_file() -> None:
    job = load_core_pin_ratchet_workflow()["jobs"]["ratchet"]
    run_text = job_run_text(job)

    assert "tools/ratchet_core_revision --check" in run_text
    assert "tools/ratchet_core_revision" in run_text
    assert "sase-core-revision.txt" in run_text
    assert "gh pr create" in run_text


def test_core_pin_ratchet_apply_tolerates_exit_two() -> None:
    """The apply path exits 2 after a successful write; the step must continue.

    Regression test for sase-15v: a bare ``python3 tools/ratchet_core_revision``
    under ``set -euo pipefail`` aborted the step on its exit 2 before
    ``git push``/``gh pr create``, so the bot never opened a pin-bump PR.
    """
    job = load_core_pin_ratchet_workflow()["jobs"]["ratchet"]
    run_text = job_run_text(job)
    lines = run_text.splitlines()

    apply_idx = next(
        i
        for i, line in enumerate(lines)
        if "tools/ratchet_core_revision" in line and "--check" not in line
    )
    push_idx = next(i for i, line in enumerate(lines) if "git push" in line)
    pr_idx = next(i for i, line in enumerate(lines) if "gh pr create" in line)
    assert apply_idx < push_idx < pr_idx

    # The apply invocation itself must not abort the step under `set -e`.
    assert "||" in lines[apply_idx]
    window = "\n".join(lines[apply_idx:push_idx])
    # Exit 2 (ratchet applied) is tolerated; any other nonzero still fails.
    assert "-eq 2" in window or "-ne 2" in window
    assert "exit" in window


def _ratchet_step_run_text() -> str:
    job = load_core_pin_ratchet_workflow()["jobs"]["ratchet"]
    step = next(s for s in job["steps"] if s.get("name") == "Propose a core pin bump")
    return str(step["run"]).replace("${{ github.repository }}", "owner/repo")


def _write_stub(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_ratchet_step(
    tmp_path: Path,
    *,
    check_rc: int,
    apply_rc: int,
    existing_pr: str = "",
) -> tuple[int, str, str, str]:
    if shutil.which("bash") is None:
        pytest.skip("bash is not available")
    run_text = _ratchet_step_run_text()
    assert "github.repository" not in run_text

    work = tmp_path / "work"
    work.mkdir()
    (work / "sase-core-revision.txt").write_text(
        _RATCHET_OLD_SHA + "\n", encoding="utf-8"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_log = tmp_path / "python-argv.log"
    git_log = tmp_path / "git-argv.log"
    gh_log = tmp_path / "gh-argv.log"
    python_log.write_text("", encoding="utf-8")
    git_log.write_text("", encoding="utf-8")
    gh_log.write_text("", encoding="utf-8")

    _write_stub(
        bin_dir / "python3",
        "#!/bin/sh\n"
        'echo "$*" >> "$PYTHON_LOG"\n'
        'case " $* " in\n'
        '  *" --check "*) exit "$CHECK_RC";;\n'
        "esac\n"
        "printf '%s' \"$NEW_SHA\" > sase-core-revision.txt\n"
        'exit "$APPLY_RC"\n',
    )
    _write_stub(
        bin_dir / "git",
        '#!/bin/sh\necho "$*" >> "$GIT_LOG"\nexit 0\n',
    )
    _write_stub(
        bin_dir / "gh",
        "#!/bin/sh\n"
        'echo "$*" >> "$GH_LOG"\n'
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then printf "%s" "$EXISTING_PR"; fi\n'
        "exit 0\n",
    )

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["CHECK_RC"] = str(check_rc)
    env["APPLY_RC"] = str(apply_rc)
    env["EXISTING_PR"] = existing_pr
    env["NEW_SHA"] = _RATCHET_NEW_SHA
    env["PYTHON_LOG"] = str(python_log)
    env["GIT_LOG"] = str(git_log)
    env["GH_LOG"] = str(gh_log)

    completed = subprocess.run(
        ["bash", "-c", run_text],
        cwd=work,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return (
        completed.returncode,
        python_log.read_text(encoding="utf-8"),
        git_log.read_text(encoding="utf-8"),
        gh_log.read_text(encoding="utf-8"),
    )


def test_core_pin_ratchet_step_pending_bump_pushes_and_opens_pr(
    tmp_path: Path,
) -> None:
    """No PR is open on the fixed branch yet: force-push then create one."""
    code, _python_argv, git_argv, gh_argv = _run_ratchet_step(
        tmp_path, check_rc=2, apply_rc=2, existing_pr=""
    )

    assert code == 0
    assert f"checkout -B {_RATCHET_BRANCH}" in git_argv
    assert f"push --force origin {_RATCHET_BRANCH}" in git_argv
    assert "pr list" in gh_argv
    assert "pr create" in gh_argv
    assert "pr edit" not in gh_argv
    assert _RATCHET_BRANCH in gh_argv


def test_core_pin_ratchet_step_pending_bump_updates_existing_pr(
    tmp_path: Path,
) -> None:
    """A PR is already open on the fixed branch: force-push and edit it in place.

    This is what keeps at most one ratchet PR open at a time instead of
    piling up a new PR every time the schedule fires while the prior one is
    still open.
    """
    code, _python_argv, git_argv, gh_argv = _run_ratchet_step(
        tmp_path, check_rc=2, apply_rc=2, existing_pr="42"
    )

    assert code == 0
    assert f"push --force origin {_RATCHET_BRANCH}" in git_argv
    assert "pr edit 42" in gh_argv
    assert "pr create" not in gh_argv


def test_core_pin_ratchet_step_up_to_date_makes_no_push_or_pr(
    tmp_path: Path,
) -> None:
    code, python_argv, git_argv, gh_argv = _run_ratchet_step(
        tmp_path, check_rc=0, apply_rc=2
    )

    assert code == 0
    assert "--check" in python_argv
    assert git_argv == ""
    assert gh_argv == ""


def test_core_pin_ratchet_step_check_failure_aborts_before_apply(
    tmp_path: Path,
) -> None:
    code, python_argv, git_argv, gh_argv = _run_ratchet_step(
        tmp_path, check_rc=3, apply_rc=2
    )

    assert code == 3
    assert "--check" in python_argv
    assert "push" not in git_argv
    assert "pr create" not in gh_argv
    assert "pr edit" not in gh_argv


def test_core_pin_ratchet_step_apply_failure_aborts_before_push(
    tmp_path: Path,
) -> None:
    code, _python_argv, git_argv, gh_argv = _run_ratchet_step(
        tmp_path, check_rc=2, apply_rc=3
    )

    assert code == 3
    assert "push" not in git_argv
    assert "pr create" not in gh_argv
    assert "pr edit" not in gh_argv


def test_shard_timings_ratchet_runs_on_schedule_not_push() -> None:
    """The ratchet must never itself be a push-path gate.

    It only ever opens a PR, which then runs the normal per-ref CI, so a
    stale timings table cannot redden master on its own.
    """
    workflow = load_shard_timings_ratchet_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "push" not in triggers
    assert workflow["concurrency"] == {
        "group": "shard-timings-ratchet",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}


def test_shard_timings_ratchet_consumes_the_full_ci_artifact() -> None:
    job = load_shard_timings_ratchet_workflow()["jobs"]["ratchet"]
    run_text = job_run_text(job)

    assert "--workflow=full.yml" in run_text
    assert f"--name {SHARD_TIMINGS_ARTIFACT_NAME}" in run_text
    assert "tools/refresh_shard_timings" in run_text
    assert "--from-payload" in run_text
    assert "--check" in run_text
    assert "--assignment" in run_text
    assert "--max-age 14" in run_text
    assert "tests/shard_timings.json" in run_text
    assert "gh pr create" in run_text
