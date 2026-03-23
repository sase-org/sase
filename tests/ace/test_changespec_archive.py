"""Tests for ChangeSpec archive file operations."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec.archive import (
    _extract_changespec_block,
    get_archive_file_path,
    get_main_file_path,
    is_archive_file,
    move_changespec_to_file,
)
from sase.ace.changespec.parser import parse_project_file


def test_get_archive_file_path() -> None:
    """Test conversion from main to archive path."""
    assert (
        get_archive_file_path("/home/user/.sase/projects/sase/sase.gp")
        == "/home/user/.sase/projects/sase/sase-archive.gp"
    )
    assert get_archive_file_path("/tmp/myproject.gp") == "/tmp/myproject-archive.gp"


def test_get_main_file_path() -> None:
    """Test conversion from archive to main path."""
    assert (
        get_main_file_path("/home/user/.sase/projects/sase/sase-archive.gp")
        == "/home/user/.sase/projects/sase/sase.gp"
    )
    assert get_main_file_path("/tmp/myproject-archive.gp") == "/tmp/myproject.gp"


def test_is_archive_file() -> None:
    """Test archive file detection."""
    assert is_archive_file("/tmp/sase-archive.gp") is True
    assert is_archive_file("/tmp/sase.gp") is False
    assert is_archive_file("/tmp/archive.gp") is False


def test__extract_changespec_block_single() -> None:
    """Test extracting a single ChangeSpec from a file."""
    lines = [
        "NAME: my_change\n",
        "DESCRIPTION:\n",
        "  Some description\n",
        "STATUS: Submitted\n",
    ]
    extracted, remaining = _extract_changespec_block(lines, "my_change")
    assert extracted is not None
    assert any("NAME: my_change" in line for line in extracted)
    assert any("STATUS: Submitted" in line for line in extracted)
    assert not any("NAME: my_change" in line for line in remaining)


def test__extract_changespec_block_multiple() -> None:
    """Test extracting one ChangeSpec from a file with multiple."""
    lines = [
        "NAME: first_change\n",
        "DESCRIPTION:\n",
        "  First description\n",
        "STATUS: Ready\n",
        "\n",
        "NAME: second_change\n",
        "DESCRIPTION:\n",
        "  Second description\n",
        "STATUS: Submitted\n",
        "\n",
        "NAME: third_change\n",
        "DESCRIPTION:\n",
        "  Third description\n",
        "STATUS: WIP\n",
    ]
    extracted, remaining = _extract_changespec_block(lines, "second_change")
    assert extracted is not None
    assert any("NAME: second_change" in line for line in extracted)
    # first and third should remain
    assert any("NAME: first_change" in line for line in remaining)
    assert any("NAME: third_change" in line for line in remaining)
    assert not any("NAME: second_change" in line for line in remaining)


def test__extract_changespec_block_with_header() -> None:
    """Test extracting a ChangeSpec that has a ## ChangeSpec header."""
    lines = [
        "## ChangeSpec\n",
        "NAME: my_change\n",
        "DESCRIPTION:\n",
        "  Some description\n",
        "STATUS: Archived\n",
    ]
    extracted, remaining = _extract_changespec_block(lines, "my_change")
    assert extracted is not None
    assert any("## ChangeSpec" in line for line in extracted)
    assert any("NAME: my_change" in line for line in extracted)


def test__extract_changespec_block_not_found() -> None:
    """Test extraction when ChangeSpec name is not in the file."""
    lines = [
        "NAME: other_change\n",
        "DESCRIPTION:\n",
        "  Other description\n",
        "STATUS: Ready\n",
    ]
    extracted, remaining = _extract_changespec_block(lines, "nonexistent")
    assert extracted is None
    assert len(remaining) == len(lines)


def test_move_changespec_to_archive() -> None:
    """Test end-to-end move from main to archive file."""
    main_content = """NAME: active_change
DESCRIPTION:
  Active description
STATUS: Ready

NAME: archived_change
DESCRIPTION:
  Archived description
STATUS: Submitted
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        with open(main_file, "w") as f:
            f.write(main_content)

        result = move_changespec_to_file(main_file, archive_file, "archived_change")
        assert result is True

        # Verify archived_change is in the archive file
        assert os.path.exists(archive_file)
        with open(archive_file) as f:
            archive_content = f.read()
        assert "NAME: archived_change" in archive_content
        assert "STATUS: Submitted" in archive_content

        # Verify archived_change is NOT in the main file
        with open(main_file) as f:
            main_content_after = f.read()
        assert "NAME: archived_change" not in main_content_after
        assert "NAME: active_change" in main_content_after


def test_move_changespec_from_archive() -> None:
    """Test end-to-end move from archive back to main file."""
    main_content = """NAME: active_change
DESCRIPTION:
  Active description
STATUS: Ready
"""
    archive_content = """NAME: restored_change
DESCRIPTION:
  Restored description
STATUS: Draft
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        with open(main_file, "w") as f:
            f.write(main_content)
        with open(archive_file, "w") as f:
            f.write(archive_content)

        result = move_changespec_to_file(archive_file, main_file, "restored_change")
        assert result is True

        # Verify restored_change is in the main file
        with open(main_file) as f:
            main_after = f.read()
        assert "NAME: restored_change" in main_after
        assert "NAME: active_change" in main_after

        # Verify restored_change is NOT in the archive file
        with open(archive_file) as f:
            archive_after = f.read()
        assert "NAME: restored_change" not in archive_after


def test_move_creates_dest_file() -> None:
    """Test that move creates the destination file if it doesn't exist."""
    main_content = """NAME: my_change
DESCRIPTION:
  My description
STATUS: Submitted
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        with open(main_file, "w") as f:
            f.write(main_content)

        assert not os.path.exists(archive_file)

        result = move_changespec_to_file(main_file, archive_file, "my_change")
        assert result is True
        assert os.path.exists(archive_file)

        with open(archive_file) as f:
            content = f.read()
        assert "NAME: my_change" in content


def test_move_changespec_not_found() -> None:
    """Test move returns False when ChangeSpec is not in source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        main_file = os.path.join(tmpdir, "test.gp")
        archive_file = os.path.join(tmpdir, "test-archive.gp")

        with open(main_file, "w") as f:
            f.write("NAME: other\nDESCRIPTION:\n  x\nSTATUS: WIP\n")

        result = move_changespec_to_file(main_file, archive_file, "nonexistent")
        assert result is False
        assert not os.path.exists(archive_file)


def test_find_all_changespecs_reads_archive() -> None:
    """Test that find_all_changespecs reads both main and archive files."""
    main_content = """NAME: active_cl
DESCRIPTION:
  Active
STATUS: Ready
"""
    archive_content = """NAME: archived_cl
DESCRIPTION:
  Archived
STATUS: Submitted
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = os.path.join(tmpdir, "myproj")
        os.makedirs(project_dir)

        with open(os.path.join(project_dir, "myproj.gp"), "w") as f:
            f.write(main_content)
        with open(os.path.join(project_dir, "myproj-archive.gp"), "w") as f:
            f.write(archive_content)

        # The function looks for ~/.sase/projects, so create the structure
        sase_projects_dir = Path(tmpdir) / ".sase" / "projects" / "myproj"
        sase_projects_dir.mkdir(parents=True)
        (sase_projects_dir / "myproj.gp").write_text(main_content)
        (sase_projects_dir / "myproj-archive.gp").write_text(archive_content)

        with patch("pathlib.Path.home", return_value=Path(tmpdir)):
            from sase.ace.changespec import find_all_changespecs

            result = find_all_changespecs()

        names = {cs.name for cs in result}
        assert "active_cl" in names
        assert "archived_cl" in names


def test_project_basename_for_archive_file() -> None:
    """Test that project_basename strips -archive from the file path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="-archive.gp", delete=False, prefix="myproj"
    ) as f:
        f.write("NAME: test_cl\nDESCRIPTION:\n  Test\nSTATUS: Submitted\n")
        archive_file = f.name

    try:
        result = parse_project_file(archive_file)
        assert len(result) == 1
        # project_basename should strip the -archive suffix
        basename = result[0].project_basename
        assert "-archive" not in basename
    finally:
        os.unlink(archive_file)
