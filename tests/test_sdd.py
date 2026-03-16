"""Tests for sdd.py - SDD file writing utilities."""

import tempfile
from pathlib import Path

from sase.sdd import (
    _get_primary_workspace_dir,
    get_sdd_dir,
    update_spec_with_qa,
    write_sdd_files,
)


# ---------------------------------------------------------------------------
# _get_primary_workspace_dir
# ---------------------------------------------------------------------------


def test_primary_workspace_dir_ws1() -> None:
    assert (
        _get_primary_workspace_dir("/home/user/myproject", 1) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws0() -> None:
    assert (
        _get_primary_workspace_dir("/home/user/myproject", 0) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws2() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_2", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_ws3() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_3", 3)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_no_suffix() -> None:
    """If workspace dir doesn't end with _N suffix, return as-is."""
    result = _get_primary_workspace_dir("/home/user/myproject", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_trailing_slash() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_2/", 2)
    assert result == "/home/user/myproject"


# ---------------------------------------------------------------------------
# get_sdd_dir
# ---------------------------------------------------------------------------


def test_get_sdd_dir_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=True)
    assert result == Path("/home/user/project")


def test_get_sdd_dir_not_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_ws2() -> None:
    result = get_sdd_dir("/home/user/project_2", 2, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


# ---------------------------------------------------------------------------
# write_sdd_files
# ---------------------------------------------------------------------------


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")

        spec_path, plan_path = write_sdd_files(
            sdd_dir, "my_plan", "# My Spec\nDetails here", str(plan_file)
        )

        assert spec_path.exists()
        assert plan_path.exists()
        assert spec_path.read_text(encoding="utf-8") == "# My Spec\nDetails here"
        assert "steps:" in plan_path.read_text(encoding="utf-8")


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        spec_path, plan_path = write_sdd_files(
            sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
        )
        assert spec_path.exists()
        assert not plan_path.exists()


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "specs").is_dir()
        assert (sdd_dir / "plans").is_dir()


# ---------------------------------------------------------------------------
# update_spec_with_qa
# ---------------------------------------------------------------------------


def test_update_spec_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        spec_path = Path(tmpdir) / "spec.md"
        spec_path.write_text("# Spec\nOriginal content", encoding="utf-8")

        update_spec_with_qa(spec_path, "## Q&A\nQ: Why?\nA: Because.")

        content = spec_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_spec_with_qa_missing_file() -> None:
    """No-op if spec file doesn't exist."""
    update_spec_with_qa(Path("/nonexistent/spec.md"), "qa content")
    # Should not raise
