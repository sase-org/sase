"""Tests for ChangeSpec suffix allocation."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.workflows.commit.patch_operations import compute_suffixed_cl_name


def test_compute_suffixed_cl_name_basic(tmp_path: Path) -> None:
    """Test compute_suffixed_cl_name returns suffixed name."""
    # Project file with one existing ChangeSpec (already prefixed)
    content = "NAME: test_project_eval_foobar_1\nSTATUS: Draft\n"
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = compute_suffixed_cl_name(
                "test_project", "test_project_eval_foobar"
            )
        # _1 already exists, so should get _2
        assert result == "test_project_eval_foobar_2"
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_no_existing(tmp_path: Path) -> None:
    """Test compute_suffixed_cl_name starts at _1 when no existing names."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = compute_suffixed_cl_name("test_project", "test_project_eval_bar")
        assert result == "test_project_eval_bar_1"
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_skips_remote_branch_suffixes(tmp_path: Path) -> None:
    """Suffix allocation excludes _<N> whose branch already exists on the remote.

    Regression for the orphaned-PR bug: the ChangeSpec namespace is nearly
    empty (only _1) but the remote branch namespace is dense (_1.._4), so the
    reserved name must skip every taken remote branch instead of colliding.
    """
    content = "NAME: test_project_eval_foo_1\nSTATUS: Draft\n"
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        project_file = f.name

    provider = MagicMock()
    provider.existing_branch_suffixes.return_value = {1, 2, 3, 4}

    try:
        with (
            patch(
                "sase.workflows.commit.patch_operations.get_project_file_path",
                return_value=project_file,
            ),
            patch(
                "sase.vcs_provider.get_vcs_provider",
                return_value=provider,
            ),
        ):
            result = compute_suffixed_cl_name(
                "test_project", "test_project_eval_foo", cwd="/repo"
            )
        # ChangeSpec _1 + remote _1.._4 are taken, so the next free is _5.
        assert result == "test_project_eval_foo_5"
        provider.existing_branch_suffixes.assert_called_once_with(
            "test_project_eval_foo", "/repo"
        )
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_skips_remote_query_without_cwd(
    tmp_path: Path,
) -> None:
    """Without cwd the remote namespace is not consulted (no network call)."""
    content = "NAME: test_project_eval_foo_1\nSTATUS: Draft\n"
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write(content)
        project_file = f.name

    provider = MagicMock()

    try:
        with (
            patch(
                "sase.workflows.commit.patch_operations.get_project_file_path",
                return_value=project_file,
            ),
            patch(
                "sase.vcs_provider.get_vcs_provider",
                return_value=provider,
            ),
        ):
            result = compute_suffixed_cl_name("test_project", "test_project_eval_foo")
        assert result == "test_project_eval_foo_2"
        provider.existing_branch_suffixes.assert_not_called()
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_no_project_file() -> None:
    """Test compute_suffixed_cl_name returns None when project file can't be created."""
    with (
        patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value="/nonexistent/path.sase",
        ),
        patch(
            "sase.workflows.commit.patch_operations.os.path.isfile",
            return_value=False,
        ),
        patch(
            "sase.workflows.commit.project_file_utils.create_project_file",
            return_value=False,
        ),
    ):
        result = compute_suffixed_cl_name("test_project", "eval_baz")
    assert result is None


def test_compute_suffixed_cl_name_adds_project_prefix(tmp_path: Path) -> None:
    """compute_suffixed_cl_name prepends project prefix when missing."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = compute_suffixed_cl_name("myproj", "fix_bug")
        assert result == "myproj_fix_bug_1"
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_uses_display_project_prefix(tmp_path: Path) -> None:
    """Reservation uses the canonical project file but returns display NAME."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with (
            patch(
                "sase.workflows.commit.patch_operations.get_project_file_path",
                return_value=project_file,
            ),
            patch(
                "sase.project_display_names.project_display_name_for",
                return_value="widgets",
            ),
            patch(
                "sase.project_display_names.humanize_cl_name",
                side_effect=lambda name: name.replace("gh_acme__widgets", "widgets"),
            ),
        ):
            result = compute_suffixed_cl_name("gh_acme__widgets", "fix_bug")

        assert result == "widgets_fix_bug_1"
        with open(project_file, encoding="utf-8") as f:
            assert "NAME: widgets_fix_bug_1" in f.read()
    finally:
        os.unlink(project_file)


def test_compute_suffixed_cl_name_no_double_prefix(tmp_path: Path) -> None:
    """compute_suffixed_cl_name does not double-prefix when already present."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.patch_operations.get_project_file_path",
            return_value=project_file,
        ):
            result = compute_suffixed_cl_name("myproj", "myproj_fix_bug")
        assert result == "myproj_fix_bug_1"
    finally:
        os.unlink(project_file)
