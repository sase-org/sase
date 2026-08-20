"""Tests for RUNNING field workspace-number allocation."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.running_field import (
    WorkspaceClaim,
    WorkspaceClaimError,
    claim_next_axe_workspace,
    claim_next_axe_workspace_dir,
    get_claimed_workspaces,
    get_first_available_axe_workspace,
    get_first_available_workspace,
)
from tests._running_field_helpers import create_project_file_with_running


def test_get_first_available_workspace_unified_pool_defaults_to_10(
    tmp_path: Path,
) -> None:
    """Default allocator returns ``#10`` even when ``#1`` is claimed."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        # ``#1`` is reserved; the unified claim pool starts at ``#10``.
        workspace_num = get_first_available_workspace(project_file)
        assert workspace_num == 10
    finally:
        Path(project_file).unlink()


def test_get_first_available_workspace_legacy_range_still_works(tmp_path: Path) -> None:
    """Explicit ``min_workspace`` / ``max_workspace`` preserves legacy ranges."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        workspace_num = get_first_available_workspace(
            project_file, min_workspace=1, max_workspace=99
        )
        assert workspace_num == 2
    finally:
        Path(project_file).unlink()


def test_get_first_available_workspace_skips_claimed_unified_pool_slot(
    tmp_path: Path,
) -> None:
    """Occupied ``#10`` allocates ``#11`` from the unified pool."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(10, "crs", "feature", pid=12345)]
    )
    try:
        workspace_num = get_first_available_workspace(project_file)
        assert workspace_num == 11
    finally:
        Path(project_file).unlink()


def test_get_first_available_axe_workspace_returns_first_gap(tmp_path: Path) -> None:
    """Axe allocation skips claimed slots and returns the first free number."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(100, "run", "first", pid=11111),
            WorkspaceClaim(102, "run", "third", pid=22222),
        ],
    )
    try:
        workspace_num = get_first_available_axe_workspace(
            project_file, min_workspace=100, max_workspace=102
        )
        assert workspace_num == 101
    finally:
        Path(project_file).unlink()


def test_get_first_available_axe_workspace_raises_when_range_claimed(
    tmp_path: Path,
) -> None:
    """A full axe range fails clearly instead of returning a duplicate slot."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(100, "run", "first", pid=11111),
            WorkspaceClaim(101, "run", "second", pid=22222),
        ],
    )
    try:
        with pytest.raises(
            RuntimeError,
            match=r"All axe workspaces \(100-101\) are claimed",
        ):
            get_first_available_axe_workspace(
                project_file, min_workspace=100, max_workspace=101
            )
    finally:
        Path(project_file).unlink()


@pytest.mark.parametrize("legacy_state", ["archived", "closed"])
def test_claim_next_axe_workspace_rejects_legacy_inactive_project_before_running_write(
    legacy_state: str,
    tmp_path: Path,
) -> None:
    """Atomic allocation uses the same lifecycle gate as direct claims."""
    project_file = tmp_path / "foo.sase"
    project_file.write_text(
        f"PROJECT_STATE: {legacy_state}\nNAME: Test Feature\nSTATUS: Ready\n",
        encoding="utf-8",
    )

    with pytest.raises(
        WorkspaceClaimError,
        match="project 'foo' is disabled; run 'sase project enable foo'",
    ):
        claim_next_axe_workspace(str(project_file), "spy-foo", 12345, cl_name="foo")

    assert "RUNNING:" not in project_file.read_text(encoding="utf-8")


def test_claim_next_axe_workspace_finds_first_available(tmp_path: Path) -> None:
    """Atomic claim picks the first free workspace in the unified pool."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(10, "spy-foo", "foo", pid=11111)]
    )
    try:
        workspace_num = claim_next_axe_workspace(
            project_file, "spy-bar", 22222, cl_name="bar"
        )
        assert workspace_num == 11

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
        claimed_nums = {c.workspace_num for c in claims}
        assert claimed_nums == {10, 11}
    finally:
        Path(project_file).unlink()


def test_claim_next_axe_workspace_empty_running_field(tmp_path: Path) -> None:
    """Atomic claim on an empty project allocates ``#10`` from the unified pool."""
    project_file = create_project_file_with_running(
        tmp_path,
    )
    try:
        workspace_num = claim_next_axe_workspace(
            project_file, "spy-foo", 12345, cl_name="foo"
        )
        assert workspace_num == 10

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workspace_num == 10
        assert claims[0].pid == 12345
    finally:
        Path(project_file).unlink()


def test_claim_next_axe_workspace_empty_running_header(tmp_path: Path) -> None:
    """Atomic claim on a file with an empty RUNNING field allocates ``#10``."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("RUNNING:\nNAME: Test Feature\nSTATUS: Ready\n")
        project_file = f.name
    try:
        workspace_num = claim_next_axe_workspace(
            project_file, "spy-foo", 12345, cl_name="foo"
        )
        assert workspace_num == 10

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workspace_num == 10
    finally:
        Path(project_file).unlink()


def test_claim_next_axe_workspace_legacy_range_still_works(tmp_path: Path) -> None:
    """Explicit ``min_workspace`` / ``max_workspace`` preserves legacy ranges."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(100, "spy-foo", "foo", pid=11111)]
    )
    try:
        workspace_num = claim_next_axe_workspace(
            project_file,
            "spy-bar",
            22222,
            cl_name="bar",
            min_workspace=100,
            max_workspace=199,
        )
        assert workspace_num == 101
    finally:
        Path(project_file).unlink()


def test_running_field_malformed_claim_rows_are_ignored_for_allocation(
    tmp_path: Path,
) -> None:
    """Malformed RUNNING rows do not block Rust-backed allocation."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write(
            "RUNNING:\n"
            "  #10 | not-a-pid | spy-bad | bad\n"
            "  #11 | 11111 | spy-good | good\n"
            "\n\n"
            "NAME: Test Feature\n"
            "STATUS: Ready\n"
        )
        project_file = f.name
    try:
        workspace_num = claim_next_axe_workspace(
            project_file, "spy-new", 22222, cl_name="new"
        )
        assert workspace_num == 10

        claims = get_claimed_workspaces(project_file)
        assert {claim.workspace_num for claim in claims} == {10, 11}
    finally:
        Path(project_file).unlink()


def test_running_field_suffix_corrupt_claim_blocks_allocation(
    tmp_path: Path,
) -> None:
    """A valid claim with unknown suffix fields still occupies its workspace."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write(
            "RUNNING:\n"
            "  #10 | 11111 | spy-old | old | 20260820_121314 | legacy=bad\n"
            "\n\n"
            "NAME: Test Feature\n"
            "STATUS: Ready\n"
        )
        project_file = f.name
    try:
        workspace_num = claim_next_axe_workspace(
            project_file, "spy-new", 22222, cl_name="new"
        )
        assert workspace_num == 11

        claims = get_claimed_workspaces(project_file)
        assert {claim.workspace_num for claim in claims} == {10, 11}
        old_claim = next(claim for claim in claims if claim.workspace_num == 10)
        assert old_claim.artifacts_timestamp == "20260820_121314"
    finally:
        Path(project_file).unlink()


def test_claim_next_axe_workspace_dir_resolves_after_claim(tmp_path: Path) -> None:
    """Directory resolution happens only after the atomic claim is held."""
    project_file = create_project_file_with_running(tmp_path)
    try:
        with patch(
            "sase.running_field._workspace.get_workspace_directory_for_num",
            return_value=("/ws/10", "proj_10"),
        ) as resolve_dir:
            workspace_num, workspace_dir, suffix = claim_next_axe_workspace_dir(
                project_file,
                "spy-foo",
                12345,
                "proj",
                cl_name="foo",
            )

        assert workspace_num == 10
        assert workspace_dir == "/ws/10"
        assert suffix == "proj_10"
        resolve_dir.assert_called_once_with(10, "proj")
        claims = get_claimed_workspaces(project_file)
        assert [claim.workspace_num for claim in claims] == [10]
    finally:
        Path(project_file).unlink()


def test_claim_next_axe_workspace_dir_releases_on_resolve_failure(
    tmp_path: Path,
) -> None:
    """A materialization failure after claim must free the slot."""
    project_file = create_project_file_with_running(tmp_path)
    try:
        with patch(
            "sase.running_field._workspace.get_workspace_directory_for_num",
            side_effect=RuntimeError("clone failed"),
        ):
            with pytest.raises(WorkspaceClaimError, match="clone failed"):
                claim_next_axe_workspace_dir(
                    project_file,
                    "spy-foo",
                    12345,
                    "proj",
                    cl_name="foo",
                )

        assert get_claimed_workspaces(project_file) == []
    finally:
        Path(project_file).unlink()
