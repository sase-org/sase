"""Tests for sdd/ subpackage - SDD file writing utilities."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec_plan import _commit_sdd_files
from sase.sdd.beads import init_beads
from sase.sdd.files import (
    find_sdd_file,
    get_primary_workspace_dir,
    get_yyyymm,
    commit_sdd_files,
    get_sdd_dir,
    update_prompt_with_qa,
    update_spec_with_qa,
    write_sdd_files,
)


# ---------------------------------------------------------------------------
# get_primary_workspace_dir
# ---------------------------------------------------------------------------


def test_primary_workspace_dir_ws1() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 1) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws0() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 0) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws2() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_ws3() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_3", 3)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_suffix_in_parent_component() -> None:
    """Suffix in a parent path component, not the final one."""
    result = get_primary_workspace_dir("/google/src/cloud/bbugyi/pat_102/google3", 102)
    assert result == "/google/src/cloud/bbugyi/pat/google3"


def test_primary_workspace_dir_no_suffix() -> None:
    """If workspace dir doesn't end with _N suffix, return as-is."""
    result = get_primary_workspace_dir("/home/user/myproject", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_trailing_slash() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2/", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_prefers_project_workspace_dir() -> None:
    with (
        patch("sase.sdd.files.Path.home", return_value=Path("/home/user")),
        patch("sase.workspace_provider.get_workspace_name", return_value="myproject"),
        patch(
            "sase.workspace_provider.utils.parse_workspace_dir",
            return_value="/home/user/myproject",
        ),
    ):
        result = get_primary_workspace_dir("/home/user/myproject_2", 1)
    assert result == "/home/user/myproject"


# ---------------------------------------------------------------------------
# get_sdd_dir
# ---------------------------------------------------------------------------


def test_get_sdd_dir_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=True)
    assert result == Path("/home/user/project/sdd")


def test_get_sdd_dir_not_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_ws2() -> None:
    result = get_sdd_dir("/home/user/project_2", 2, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_suffix_in_parent() -> None:
    result = get_sdd_dir(
        "/google/src/cloud/bbugyi/pat_102/google3", 102, version_controlled=False
    )
    assert result == Path("/google/src/cloud/bbugyi/pat/google3/.sase/sdd")


# ---------------------------------------------------------------------------
# write_sdd_files
# ---------------------------------------------------------------------------


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "# My Spec\nDetails here", str(plan_file)
            )

        assert prompt_path.exists()
        assert plan_path.exists()
        assert prompt_path.parent.name == "202603"
        assert plan_path.parent.name == "202603"
        assert prompt_path.read_text(encoding="utf-8") == "# My Spec\nDetails here"
        plan_text = plan_path.read_text(encoding="utf-8")
        assert plan_text.startswith("---\ncreate_time:")
        assert "steps:" in plan_text


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
            )
        assert prompt_path.exists()
        assert not plan_path.exists()


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "prompts" / "202603").is_dir()
        assert (sdd_dir / "plans" / "202603").is_dir()


def test_write_sdd_files_epic_kind() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            prompt_path, plan_path = write_sdd_files(
                sdd_dir,
                "my_epic",
                "spec",
                str(plan_file),
                plan_kind="epics",
            )

        assert prompt_path == sdd_dir / "prompts" / "202603" / "my_epic.md"
        assert plan_path == sdd_dir / "epics" / "202603" / "my_epic.md"
        assert plan_path.exists()


def test_write_sdd_files_uses_canonical_sdd_kinds_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "sdd"
        plan_file = Path(tmpdir) / "source_plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with patch("sase.sdd.files.get_yyyymm", return_value="202603"):
            for plan_kind in ("plans", "epics", "legends"):
                write_sdd_files(
                    sdd_dir,
                    f"my_{plan_kind}",
                    "spec",
                    str(plan_file),
                    plan_kind=plan_kind,
                )

        assert (sdd_dir / "prompts" / "202603").is_dir()
        assert (sdd_dir / "plans" / "202603" / "my_plans.md").exists()
        assert (sdd_dir / "epics" / "202603" / "my_epics.md").exists()
        assert (sdd_dir / "legends" / "202603" / "my_legends.md").exists()
        assert not (Path(tmpdir) / "plans").exists()
        assert not (Path(tmpdir) / "prompts").exists()
        assert not (Path(tmpdir) / "specs").exists()


def test_write_sdd_files_rejects_unknown_plan_kind() -> None:
    with pytest.raises(ValueError, match="invalid SDD plan kind"):
        write_sdd_files(Path("/tmp/sdd"), "bad", "spec", "/tmp/plan.md", plan_kind="x")


# ---------------------------------------------------------------------------
# update_prompt_with_qa
# ---------------------------------------------------------------------------


def test_update_prompt_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_prompt_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        content = prompt_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_prompt_with_qa_missing_file() -> None:
    """No-op if prompt file doesn't exist."""
    update_prompt_with_qa(Path("/nonexistent/prompt.md"), "qa content")
    # Should not raise


def test_update_spec_with_qa_legacy_wrapper() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_spec_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        assert "## Q&A" in prompt_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# init_beads
# ---------------------------------------------------------------------------


def testinit_beads_creates_sdd_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.beads.subprocess.run") as mock_run,
            patch("sase.sdd.beads.BeadProject.init") as mock_bead_init,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)

        assert result == Path(tmpdir) / ".sase" / "sdd"
        assert result.is_dir()
        # Verify .gitignore was created
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        gitignore = sdd_dir / ".gitignore"
        assert gitignore.exists()
        assert "beads/beads.db" in gitignore.read_text(encoding="utf-8")
        # Verify BeadProject.init was called with sdd_dir and non-VC dirname
        mock_bead_init.assert_called_once_with(sdd_dir, beads_dirname="beads")


def testinit_beads_idempotent() -> None:
    """Calling init_beads twice should not error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        sdd_dir.mkdir(parents=True)
        # Simulate existing git repo
        (sdd_dir / ".git").mkdir()
        # Simulate existing beads inside sdd_dir (non-VC uses "beads" without dot)
        (sdd_dir / "beads").mkdir()
        # Simulate existing .gitignore
        (sdd_dir / ".gitignore").write_text("beads/beads.db\n", encoding="utf-8")

        with patch("sase.sdd.beads.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)
        assert result == sdd_dir


# ---------------------------------------------------------------------------
# commit_sdd_files
# ---------------------------------------------------------------------------


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

        # Write a file and commit it
        (sdd_dir / "test.md").write_text("hello", encoding="utf-8")
        commit_sdd_files(sdd_dir, "Test commit")

        # Verify commit exists
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        assert "Test commit" in log.stdout


def test_commit_sdd_files_no_changes() -> None:
    """No-op when there are no changes to commit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)

        # Call with no files — should not error or create empty commit
        commit_sdd_files(sdd_dir, "Empty commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        # No commits should exist
        assert log.stdout.strip() == ""


def test_commit_sdd_files_not_git_repo() -> None:
    """No-op if sdd_dir is not a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        commit_sdd_files(sdd_dir, "Should not error")
        # Should not raise


# ---------------------------------------------------------------------------
# _commit_sdd_files (run_agent_exec_plan)
# ---------------------------------------------------------------------------


def test_commit_sdd_files_passes_tempfile_to_m() -> None:
    """_commit_sdd_files writes the message to a temp file and passes its path to -M."""
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
            # Find -M arg and read the file it points to
            m_idx = cmd.index("-M")
            msg_path = cmd[m_idx + 1]
            assert os.path.isfile(msg_path), (
                f"-M should point to a file, got: {msg_path}"
            )
            with open(msg_path, encoding="utf-8") as f:
                captured_msg_content.append(f.read())
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_plan")

        assert len(captured_msg_content) == 1
        assert captured_msg_content[0] == "chore: Add SDD prompt and plan for my_plan"


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

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_plan")

        cmd = captured_cmd[0]
        # Collect all -f values
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_finds_canonical_sdd_paths() -> None:
    """_commit_sdd_files prefers version-controlled sdd/ paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "sdd" / "prompts" / "202603"
        epics = Path(ws) / "sdd" / "epics" / "202603"
        prompts.mkdir(parents=True)
        epics.mkdir(parents=True)
        prompt_file = prompts / "my_epic.md"
        plan_file = epics / "my_epic.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_epic", plan_kind="epics")

        f_values = [
            captured_cmd[0][i + 1] for i, v in enumerate(captured_cmd[0]) if v == "-f"
        ]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_prompt_only() -> None:
    """Only prompt file exists — should still invoke sase commit with one -f."""
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

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "only_prompt")

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert len(f_values) == 1


def test_commit_sdd_files_noop_no_files() -> None:
    """No-op when neither spec nor plan file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_run = MagicMock()
        with patch("sase.axe.run_agent_exec_plan.subprocess.run", mock_run):
            _commit_sdd_files(tmpdir, "nonexistent")
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
            patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run),
            patch("sase.axe.run_agent_exec_plan.logger") as mock_logger,
        ):
            _commit_sdd_files(ws, "fail")

        mock_logger.warning.assert_called_once()
        assert (
            "exit 1"
            in mock_logger.warning.call_args[0][0]
            % mock_logger.warning.call_args[0][1:]
        )


# ---------------------------------------------------------------------------
# get_yyyymm
# ---------------------------------------------------------------------------


def test_get_yyyymm_default() -> None:
    """get_yyyymm returns a 6-digit YYYYMM string."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    dt = datetime(2025, 11, 15, 10, 30, 0, tzinfo=ZoneInfo("UTC"))
    assert get_yyyymm(dt) == "202511"


def test_get_yyyymm_january() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    dt = datetime(2026, 1, 5, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert get_yyyymm(dt) == "202601"


# ---------------------------------------------------------------------------
# find_sdd_file
# ---------------------------------------------------------------------------


def test_find_sdd_file_prompts_flat() -> None:
    """find_sdd_file returns canonical prompt flat path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        (base / "prompts" / "my_plan.md").write_text("prompt", encoding="utf-8")
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == base / "prompts" / "my_plan.md"


def test_find_sdd_file_legacy_yyyymm() -> None:
    """find_sdd_file finds legacy file in YYYYMM subdirectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "plans" / "202603").mkdir(parents=True)
        (base / "plans" / "202603" / "my_plan.md").write_text("plan", encoding="utf-8")
        result = find_sdd_file(base, "plans", "my_plan.md")
        assert result == base / "plans" / "202603" / "my_plan.md"


def test_find_sdd_file_prefers_flat() -> None:
    """find_sdd_file prefers flat path over YYYYMM when both exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        (base / "prompts" / "my_plan.md").write_text("flat", encoding="utf-8")
        (base / "prompts" / "202603").mkdir()
        (base / "prompts" / "202603" / "my_plan.md").write_text(
            "yyyymm", encoding="utf-8"
        )
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == base / "prompts" / "my_plan.md"


def test_find_sdd_file_prefers_canonical_sdd_over_legacy() -> None:
    """Canonical sdd/<kind> wins over legacy root <kind>."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "prompts" / "202603").mkdir(parents=True)
        (base / "specs" / "202603").mkdir(parents=True)
        canonical = base / "sdd" / "prompts" / "202603" / "my_plan.md"
        legacy = base / "specs" / "202603" / "my_plan.md"
        canonical.write_text("canonical", encoding="utf-8")
        legacy.write_text("legacy", encoding="utf-8")

        result = find_sdd_file(base, "specs", "my_plan.md")
        assert result == canonical


def test_find_sdd_file_legacy_specs_alias() -> None:
    """Legacy specs paths remain visible through prompt lookup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "specs" / "202603").mkdir(parents=True)
        legacy = base / "sdd" / "specs" / "202603" / "my_plan.md"
        legacy.write_text("legacy", encoding="utf-8")

        assert find_sdd_file(base, "prompts", "my_plan.md") == legacy
        assert find_sdd_file(base, "specs", "my_plan.md") == legacy


def test_find_sdd_file_supports_epics_and_legends() -> None:
    """Resolution covers all SDD plan-like kinds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "epics" / "202603").mkdir(parents=True)
        (base / "sdd" / "legends" / "202603").mkdir(parents=True)
        epic = base / "sdd" / "epics" / "202603" / "roadmap.md"
        legend = base / "sdd" / "legends" / "202603" / "roadmap.md"
        epic.write_text("epic", encoding="utf-8")
        legend.write_text("legend", encoding="utf-8")

        assert find_sdd_file(base, "epics", "roadmap.md") == epic
        assert find_sdd_file(base, "legends", "roadmap.md") == legend


def test_find_sdd_file_missing() -> None:
    """find_sdd_file returns None when file doesn't exist anywhere."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        result = find_sdd_file(base, "prompts", "nonexistent.md")
        assert result is None
