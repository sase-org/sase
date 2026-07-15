"""Tests for committing SDD files."""

import json
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec_plan_accept import _commit_sdd_files, _commit_sdd_spec
from sase.sdd.files import commit_sdd_files, commit_sdd_store_files
from sase.sdd._git_contention import ENV_GIT_LOCK_RETRY_DELAYS
from sase.sdd.store import SddStore


def _init_test_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_commit_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )

        (sdd_dir / "test.md").write_text("hello", encoding="utf-8")
        commit_sdd_files(sdd_dir, "Test commit")

        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Test commit" in log.stdout
        assert "SASE_TYPE=sdd" in log.stdout


def test_commit_sdd_files_stages_only_targeted_paths() -> None:
    """Targeted local SDD commits must not sweep unrelated dirty files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )

        prompt = sdd_dir / "prompts" / "202605" / "targeted.md"
        plan = sdd_dir / "plans" / "202605" / "targeted.md"
        prompt.parent.mkdir(parents=True)
        plan.parent.mkdir(parents=True)
        prompt.write_text("prompt", encoding="utf-8")
        plan.write_text("plan", encoding="utf-8")
        unrelated = sdd_dir / "research" / "202605" / "notes.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("do not commit", encoding="utf-8")

        commit_sdd_files(sdd_dir, "Targeted commit", paths=[prompt, plan])

        committed = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        status = subprocess.run(
            [
                "git",
                "-c",
                "color.status=false",
                "status",
                "--short",
                "--",
                "research/202605/notes.md",
            ],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert committed == [
            "plans/202605/targeted.md",
            "prompts/202605/targeted.md",
        ]
        assert status == "?? research/202605/notes.md\n"


def test_commit_sdd_files_records_agent_marker_when_artifacts_dir_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    sdd_dir.mkdir()
    artifacts_dir.mkdir()
    subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260708120000")
    monkeypatch.setattr(
        "sase.workflows.commit.commit_tracking."
        "update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: None,
    )

    (sdd_dir / "test.md").write_text("hello", encoding="utf-8")

    assert (
        commit_sdd_files(
            sdd_dir,
            "Record SDD commit",
            repo_name="sase-org/sase--sdd",
        )
        is True
    )

    results = json.loads((artifacts_dir / "commit_results.json").read_text())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=sdd_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert not (artifacts_dir / "commit_result.json").exists()
    assert results[0]["run_id"] == "20260708120000"
    assert results[0]["cwd"] == str(sdd_dir)
    assert results[0]["result"] == head
    assert results[0]["message"].startswith("Record SDD commit")
    assert results[0]["repo_name"] == "sase-org/sase--sdd"
    diff_path = Path(results[0]["diff_path"])
    assert diff_path == artifacts_dir / "commit_diffs" / "001.diff"
    assert "+hello\n" in diff_path.read_text(encoding="utf-8")


def test_commit_sdd_files_diff_is_scoped_to_committed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    _init_test_git_repo(sdd_dir)
    artifacts_dir.mkdir()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setattr(
        "sase.workflows.commit.commit_tracking."
        "update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: None,
    )
    committed = sdd_dir / "plans" / "plan.md"
    uncommitted = sdd_dir / "research" / "report.md"
    committed.parent.mkdir()
    uncommitted.parent.mkdir()
    committed.write_text("plan\n", encoding="utf-8")
    uncommitted.write_text("report\n", encoding="utf-8")

    assert commit_sdd_files(
        sdd_dir,
        "Add plan",
        paths=[committed],
        artifacts_dir=artifacts_dir,
        repo_name="plans",
    )

    results = json.loads((artifacts_dir / "commit_results.json").read_text())
    diff_text = Path(results[0]["diff_path"]).read_text(encoding="utf-8")
    assert "plans/plan.md" in diff_text
    assert "research/report.md" not in diff_text
    assert (
        subprocess.run(
            ["git", "status", "--short"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == "?? research/\n"
    )


def test_commit_sdd_files_skips_agent_marker_when_artifacts_dir_is_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    sdd_dir.mkdir()
    artifacts_dir.mkdir()
    subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)

    (sdd_dir / "test.md").write_text("hello", encoding="utf-8")

    assert commit_sdd_files(sdd_dir, "Record SDD commit") is True

    assert not (artifacts_dir / "commit_results.json").exists()


def test_commit_sdd_files_no_changes() -> None:
    """No-op when there are no changes to commit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)

        commit_sdd_files(sdd_dir, "Empty commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        assert log.stdout.strip() == ""


def test_commit_sdd_files_not_git_repo() -> None:
    """No-op if sdd_dir is not a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        commit_sdd_files(sdd_dir, "Should not error")


def test_commit_sdd_files_retries_transient_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_test_git_repo(repo)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    lock_path = repo / ".git/index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.01,0.02,0.04,0.08")
    release = threading.Timer(0.03, lambda: lock_path.unlink(missing_ok=True))
    release.start()

    try:
        assert commit_sdd_files(repo, "Commit after contention") is True
    finally:
        release.cancel()
        lock_path.unlink(missing_ok=True)


def test_commit_sdd_files_surfaces_stderr_when_index_lock_retry_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_test_git_repo(repo)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    (repo / ".git/index.lock").touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.001,0.001")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        commit_sdd_files(repo, "Fail after contention")

    message = str(exc_info.value)
    assert "Unable to create" in message
    assert "index.lock" in message


def test_commit_sdd_files_does_not_retry_non_lock_128(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_test_git_repo(repo)
    sleep = MagicMock()
    monkeypatch.setattr("sase.sdd._git_contention.time.sleep", sleep)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        commit_sdd_files(repo, "Invalid pathspec", paths=[":(invalid)"])

    assert "pathspec" in str(exc_info.value).lower()
    sleep.assert_not_called()


def test_commit_sdd_files_passes_tempfile_to_m() -> None:
    """_commit_sdd_files writes the message to a temp file and passes it to -M."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        plans = Path(ws) / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        (prompts / "my_plan.md").write_text("prompt", encoding="utf-8")
        (plans / "my_plan.md").write_text("plan", encoding="utf-8")

        captured_msg_content: list[str] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            m_idx = cmd.index("-M")
            msg_path = Path(cmd[m_idx + 1])
            assert msg_path.is_file(), f"-M should point to a file, got: {msg_path}"
            captured_msg_content.append(msg_path.read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_plan") is True

        assert len(captured_msg_content) == 1
        assert (
            captured_msg_content[0]
            == "chore: Add SDD prompt and plan for my_plan\n\nSASE_TYPE=sdd"
        )


def test_commit_sdd_files_passes_f_flags() -> None:
    """_commit_sdd_files passes -f for each existing prompt/plan file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        plans = Path(ws) / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        prompt_file = prompts / "my_plan.md"
        plan_file = plans / "my_plan.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_plan") is True

        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_finds_canonical_sdd_paths() -> None:
    """_commit_sdd_files prefers version-controlled sdd/ paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "sdd" / "prompts" / "202603"
        plans = Path(ws) / "sdd" / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        prompt_file = prompts / "my_epic.md"
        plan_file = plans / "my_epic.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_epic", plan_tier="epic") is True

        f_values = [
            captured_cmd[0][i + 1] for i, v in enumerate(captured_cmd[0]) if v == "-f"
        ]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_prompt_only() -> None:
    """Only prompt file exists, so sase commit is invoked with one -f."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        prompts.mkdir(parents=True)
        (prompts / "only_prompt.md").write_text("prompt", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "only_prompt") is True

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert len(f_values) == 1


def test_commit_sdd_spec_excludes_existing_plan() -> None:
    """Epic approval commits only the planner-owned prompt snapshot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompts = Path(tmpdir) / "prompts" / "202603"
        plans = Path(tmpdir) / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        prompt_file = prompts / "my_epic.md"
        plan_file = plans / "my_epic.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_spec(tmpdir, "my_epic") is True

        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, value in enumerate(cmd) if value == "-f"]
        assert f_values == [str(prompt_file)]
        assert str(plan_file) not in cmd


def test_commit_sdd_files_noop_no_files() -> None:
    """No-op when neither spec nor plan file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_run = MagicMock()
        with patch("sase.axe.run_agent_exec_plan_accept.subprocess.run", mock_run):
            assert _commit_sdd_files(tmpdir, "nonexistent") is True
        mock_run.assert_not_called()


def test_commit_sdd_files_logs_failure() -> None:
    """Non-zero exit code from sase commit is logged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        prompts.mkdir(parents=True)
        (prompts / "fail.md").write_text("prompt", encoding="utf-8")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stderr="boom")

        with (
            patch(
                "sase.axe.run_agent_exec_plan_accept.subprocess.run",
                side_effect=fake_run,
            ),
            patch("sase.axe.run_agent_exec_plan_accept.logger") as mock_logger,
        ):
            assert _commit_sdd_files(ws, "fail") is False

        mock_logger.warning.assert_called_once()
        assert (
            "exit 1"
            in mock_logger.warning.call_args[0][0]
            % mock_logger.warning.call_args[0][1:]
        )


@pytest.mark.parametrize(
    ("mode", "async_remote", "sync_error", "expected_sync", "expected_async"),
    [
        (True, True, None, 1, 0),
        (False, True, None, 0, 0),
        ("async", True, None, 0, 1),
        ("async", False, None, 0, 1),
        (True, True, "push failed", 1, 0),
    ],
)
def test_commit_sdd_store_files_push_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: bool | str,
    async_remote: bool,
    sync_error: str | None,
    expected_sync: int,
    expected_async: int,
) -> None:
    store = SddStore(
        storage="separate_repo",
        sdd_dir=tmp_path,
        repo_root=tmp_path,
        remote_url="git@example.com:owner/repo-sdd.git" if async_remote else None,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": mode}},
    )
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", lambda *a, **k: True)
    sync_calls: list[Path] = []
    async_calls: list[Path] = []

    def fake_sync(path: Path) -> SimpleNamespace:
        sync_calls.append(path)
        return SimpleNamespace(pushed=sync_error is None, error=sync_error)

    def fake_async(path: Path) -> SimpleNamespace | None:
        async_calls.append(path)
        if not async_remote:
            return None
        return SimpleNamespace(pid=123, log_path=tmp_path / "push.log")

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_sync)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch_async", fake_async)

    assert commit_sdd_store_files(store, "Commit SDD") is True
    assert sync_calls == [tmp_path] * expected_sync
    assert async_calls == [tmp_path] * expected_async


def test_commit_sdd_store_files_does_not_push_local_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(storage="local", sdd_dir=tmp_path, repo_root=tmp_path)
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", lambda *a, **k: True)
    sync = MagicMock()
    async_push = MagicMock()
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", sync)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch_async", async_push)

    assert commit_sdd_store_files(store, "Commit SDD") is True
    sync.assert_not_called()
    async_push.assert_not_called()


def test_commit_sdd_store_files_routes_split_paths_to_owning_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    research = tmp_path / "project--research"
    _init_test_git_repo(plans)
    _init_test_git_repo(research)
    plan = plans / "202607" / "plan.md"
    report = research / "202607" / "report.md"
    plan.parent.mkdir()
    report.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    report.write_text("# Research\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        research_dir=research,
        research_remote_url="git@example.com:acme/project--research.git",
    )

    assert commit_sdd_store_files(store, "Commit split SDD", paths=[plan, report])

    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=plans,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["202607/plan.md"]
    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=research,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["202607/report.md"]


def test_commit_sdd_store_files_pushes_each_changed_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    research = tmp_path / "project--research"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        research_dir=research,
        research_remote_url="git@example.com:acme/project--research.git",
    )
    commit_roots: list[Path] = []
    pushed_roots: list[Path] = []

    def fake_commit(root: Path, *_args: object, **_kwargs: object) -> bool:
        commit_roots.append(root)
        return True

    def fake_push(root: Path) -> SimpleNamespace:
        pushed_roots.append(root)
        return SimpleNamespace(pushed=True, error=None)

    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", fake_commit)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)

    assert commit_sdd_store_files(
        store,
        "Commit split SDD",
        push_after_commit=True,
    )
    assert commit_roots == [plans, research]
    assert pushed_roots == [plans, research]
