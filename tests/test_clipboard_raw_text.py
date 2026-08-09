"""Tests for get_raw_patch_text() function."""

import tempfile
from pathlib import Path

from sase.ace.patch import Patch, get_raw_patch_text


def test_get_raw_patch_text_with_legacy_patch_header_delimiter(
    tmp_path: Path,
) -> None:
    """Test extraction stops at a legacy ## ChangeSpec header."""
    content = """\
## ChangeSpec
NAME: first_cl
DESCRIPTION: First CL
STATUS: Ready

## ChangeSpec
NAME: second_cl
DESCRIPTION: Second CL
STATUS: Draft
"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        f.flush()

        cs = Patch(
            name="first_cl",
            description="First CL",
            status="Ready",
            parent=None,
            cl=None,
            file_path=f.name,
            line_number=2,  # Line after the header
        )
        result = get_raw_patch_text(cs)
        assert result is not None
        assert "NAME: first_cl" in result
        assert "NAME: second_cl" not in result

    Path(f.name).unlink()


def test_get_raw_patch_text_with_two_blank_lines_delimiter(tmp_path: Path) -> None:
    """Test extraction stops at two consecutive blank lines."""
    content = """\
NAME: first_cl
DESCRIPTION: First CL
STATUS: Ready


NAME: second_cl
DESCRIPTION: Second CL
STATUS: Draft
"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        f.flush()

        cs = Patch(
            name="first_cl",
            description="First CL",
            status="Ready",
            parent=None,
            cl=None,
            file_path=f.name,
            line_number=1,
        )
        result = get_raw_patch_text(cs)
        assert result is not None
        assert "NAME: first_cl" in result
        assert "NAME: second_cl" not in result

    Path(f.name).unlink()


def test_get_raw_patch_text_with_name_delimiter(tmp_path: Path) -> None:
    """Test extraction stops at NAME: line (Patch without header)."""
    content = """\
NAME: first_cl
DESCRIPTION: First CL
STATUS: Ready
NAME: second_cl
DESCRIPTION: Second CL
STATUS: Draft
"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        f.flush()

        cs = Patch(
            name="first_cl",
            description="First CL",
            status="Ready",
            parent=None,
            cl=None,
            file_path=f.name,
            line_number=1,
        )
        result = get_raw_patch_text(cs)
        assert result is not None
        assert "NAME: first_cl" in result
        assert "NAME: second_cl" not in result

    Path(f.name).unlink()


def test_get_raw_patch_text_eof(tmp_path: Path) -> None:
    """Test extraction handles end of file properly."""
    content = """\
NAME: last_cl
DESCRIPTION: Last CL
STATUS: Ready"""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        f.flush()

        cs = Patch(
            name="last_cl",
            description="Last CL",
            status="Ready",
            parent=None,
            cl=None,
            file_path=f.name,
            line_number=1,
        )
        result = get_raw_patch_text(cs)
        assert result is not None
        assert "NAME: last_cl" in result
        assert "DESCRIPTION: Last CL" in result
        assert "STATUS: Ready" in result

    Path(f.name).unlink()


def test_get_raw_patch_text_file_not_found() -> None:
    """Test returns None when file doesn't exist."""
    cs = Patch(
        name="test_cl",
        description="Test description",
        status="Ready",
        parent=None,
        cl=None,
        file_path="/nonexistent/path/file.sase",
        line_number=1,
    )
    result = get_raw_patch_text(cs)
    assert result is None


def test_get_raw_patch_text_invalid_line_number(tmp_path: Path) -> None:
    """Test returns None when line number is out of range."""
    content = "NAME: test_cl\n"
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        f.flush()

        cs = Patch(
            name="test_cl",
            description="Test description",
            status="Ready",
            parent=None,
            cl=None,
            file_path=f.name,
            line_number=100,  # Way beyond file length
        )
        result = get_raw_patch_text(cs)
        assert result is None

    Path(f.name).unlink()
