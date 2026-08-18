"""Tests for RUNNING field and workspace management operations."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.patch import write_patch_atomic
from sase.logs.workspace_claim_ledger import read_ledger_records
from sase.running_field import (
    WorkspaceClaim,
    WorkspaceClaimError,
    claim_next_axe_workspace,
    claim_workspace,
    get_claimed_workspaces,
    get_first_available_axe_workspace,
    get_first_available_workspace,
    get_workspace_directory_for_num,
    hold_workspace_claim,
    release_workspace,
    transfer_workspace_claim,
)
from sase.running_field import (
    get_workspace_directory as get_workspace_dir,
)


def _create_project_file_with_running(
    tmp_path: Path,
    running_claims: list[WorkspaceClaim] | None = None,
) -> str:
    """Create a temporary project file with optional RUNNING field."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\n")
        if running_claims:
            f.write("RUNNING:\n")
            for claim in running_claims:
                f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("PARENT: None\n")
        f.write("PR: None\n")
        f.write("STATUS: Ready\n")
        return f.name


def test_workspace_claim_from_line_legacy_format_no_pid_no_cl_returns_none() -> None:
    """Test parsing legacy format without PID or cl_name returns None."""
    claim = WorkspaceClaim.from_line("  #1 | run | ")
    # Legacy format without PID is now invalid
    assert claim is None


def test_claim_workspace_new_running_field(tmp_path: Path) -> None:
    """Test claiming a workspace when RUNNING field doesn't exist (PID required)."""
    project_file = _create_project_file_with_running(
        tmp_path,
    )
    try:
        # PID is required - pass it as 4th positional arg
        result = claim_workspace(project_file, 1, "crs", 12345, "my_feature")
        assert result.success is True
        assert result.error is None

        with open(project_file) as f:
            content = f.read()

        assert "RUNNING:" in content
        # Format: #N | PID | WORKFLOW | CL_NAME
        assert "#1 | 12345 | crs | my_feature" in content

        # Verify PID is parsed correctly
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 12345
    finally:
        Path(project_file).unlink()


def test_claim_workspace_existing_running_field(tmp_path: Path) -> None:
    """Test claiming a workspace when RUNNING field already exists."""
    project_file = _create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "existing", pid=11111)]
    )
    try:
        result = claim_workspace(project_file, 2, "run", 22222, "new_feature")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
        workspace_nums = {c.workspace_num for c in claims}
        assert workspace_nums == {1, 2}
    finally:
        Path(project_file).unlink()


def test_release_workspace_single(tmp_path: Path) -> None:
    """Test releasing the only workspace claim."""
    project_file = _create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        result = release_workspace(project_file, 1)
        assert result.success is True

        with open(project_file) as f:
            content = f.read()

        # RUNNING field should be removed entirely
        assert "RUNNING:" not in content
    finally:
        Path(project_file).unlink()


def test_release_workspace_with_workflow_filter(tmp_path: Path) -> None:
    """Test releasing workspace with workflow filter."""
    project_file = _create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(1, "crs", "feature1", pid=11111),
            WorkspaceClaim(1, "run", "feature2", pid=22222),
        ],
    )
    try:
        # Should only release the "crs" claim
        result = release_workspace(project_file, 1, workflow="crs")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workflow == "run"
    finally:
        Path(project_file).unlink()


def test_hold_workspace_claim_preserves_identity_and_pins_atomically(
    tmp_path: Path,
) -> None:
    project_file = _create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                17,
                "ace(run)-260712_120000",
                "feature",
                pid=12345,
                artifacts_timestamp="20260712120000",
            )
        ],
    )
    try:
        with patch(
            "sase.running_field._operations.write_patch_atomic",
            wraps=write_patch_atomic,
        ) as write_atomic:
            result = hold_workspace_claim(
                project_file,
                17,
                "ace(run)-260712_120000",
                "feature",
                "20260712120000",
            )

        assert result.success is True
        claims = get_claimed_workspaces(project_file)
        assert claims == [
            WorkspaceClaim(
                17,
                "ace(run)-260712_120000",
                "feature",
                pid=12345,
                artifacts_timestamp="20260712120000",
                pinned=True,
            )
        ]
        write_atomic.assert_called_once()
    finally:
        Path(project_file).unlink()


def test_get_first_available_workspace_unified_pool_defaults_to_10(
    tmp_path: Path,
) -> None:
    """Default allocator returns ``#10`` even when ``#1`` is claimed."""
    project_file = _create_project_file_with_running(
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
    project_file = _create_project_file_with_running(
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
    project_file = _create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(10, "crs", "feature", pid=12345)]
    )
    try:
        workspace_num = get_first_available_workspace(project_file)
        assert workspace_num == 11
    finally:
        Path(project_file).unlink()


def test_get_first_available_axe_workspace_returns_first_gap(tmp_path: Path) -> None:
    """Axe allocation skips claimed slots and returns the first free number."""
    project_file = _create_project_file_with_running(
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
    project_file = _create_project_file_with_running(
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


def test_running_field_get_workspace_directory_plugin_failure() -> None:
    """Test get_workspace_directory raises on plugin failure."""
    with patch(
        "sase.workspace_provider._registry.detect_workflow_type",
        side_effect=ValueError("No workspace plugin detected"),
    ):
        with pytest.raises(RuntimeError, match="No workspace plugin detected"):
            get_workspace_dir("myproject")


def test_running_field_get_workspace_directory_falls_back_to_workspace_dir(
    tmp_path: Path,
) -> None:
    """When no plugin claims the project, a configured WORKSPACE_DIR is used."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
    ):
        result = get_workspace_dir("myproject", 1)

    assert result == str(workspace_dir)


def test_running_field_get_workspace_directory_fallback_uses_git_clone(
    tmp_path: Path,
) -> None:
    """Numbered workspaces fall back to ``ensure_workspace_checkout`` for git checkouts."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()
    (workspace_dir / ".git").mkdir()

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
        patch(
            "sase.workspace_provider.utils.ensure_workspace_checkout",
            return_value="/fake/clones/myproject_3/",
        ) as mock_ensure,
    ):
        result = get_workspace_dir("myproject", 3)

    assert result == "/fake/clones/myproject_3/"
    mock_ensure.assert_called_once_with(str(workspace_dir), 3)


def test_running_field_get_workspace_directory_fallback_skips_non_git_share(
    tmp_path: Path,
) -> None:
    """Without a git checkout, numbered workspaces still raise the plugin error."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()  # no .git inside

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
    ):
        with pytest.raises(RuntimeError, match="No workspace plugin detected"):
            get_workspace_dir("myproject", 3)


def test_get_workspace_directory_for_num_main() -> None:
    """Test getting main workspace directory."""
    with patch(
        "sase.running_field._workspace.get_workspace_directory",
        return_value="/cloud/myproject/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(1, "myproject")
        assert workspace_dir == "/cloud/myproject/google3"
        assert suffix is None
        mock_get_ws.assert_called_once_with("myproject", 1)


def test_get_workspace_directory_for_num_share() -> None:
    """Test getting workspace share directory."""
    with patch(
        "sase.running_field._workspace.get_workspace_directory",
        return_value="/cloud/myproject_3/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(3, "myproject")
        assert workspace_dir == "/cloud/myproject_3/google3"
        assert suffix == "myproject_3"
        mock_get_ws.assert_called_once_with("myproject", 3)


def test_claim_workspace_rejects_duplicate_workspace_num(tmp_path: Path) -> None:
    """Test that claim_workspace refuses to double-claim a workspace number."""
    project_file = _create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(100, "spy-foo", "foo", pid=11111)]
    )
    try:
        # Second claim for workspace #100 should be rejected
        result = claim_workspace(project_file, 100, "spy-foo", 22222, "foo")
        assert result.success is False
        assert result.error is not None
        assert "100" in result.error

        # Only the original claim should remain
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 11111
    finally:
        Path(project_file).unlink()


def test_claim_workspace_allows_workspace_zero_duplicates(tmp_path: Path) -> None:
    """Test that workspace #0 (deferred placeholder) allows duplicates."""
    project_file = _create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(0, "ace(run)-1", "foo", pid=11111)]
    )
    try:
        result = claim_workspace(project_file, 0, "ace(run)-2", 22222, "bar")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
    finally:
        Path(project_file).unlink()


def test_claim_workspace_rejects_disabled_project_before_running_write(
    tmp_path: Path,
) -> None:
    """Disabled projects cannot receive even deferred workspace claims."""
    project_file = tmp_path / "foo.sase"
    project_file.write_text(
        "PROJECT_STATE: disabled\nNAME: Test Feature\nSTATUS: Ready\n",
        encoding="utf-8",
    )

    result = claim_workspace(str(project_file), 0, "ace(run)-1", 22222, "foo")

    assert result.success is False
    assert result.error is not None
    assert result.error == (
        "project 'foo' is disabled; run 'sase project enable foo' before launching work"
    )
    assert "RUNNING:" not in project_file.read_text(encoding="utf-8")


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
    project_file = _create_project_file_with_running(
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
    project_file = _create_project_file_with_running(
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
    project_file = _create_project_file_with_running(
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


def test_transfer_workspace_claim_by_pid(tmp_path: Path) -> None:
    """Test transferring a claim to a retry child by matching workspace and PID."""
    project_file = _create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                100,
                "ace(run)-old",
                "feature",
                pid=11111,
                artifacts_timestamp="20260501115959",
            )
        ],
    )
    try:
        result = transfer_workspace_claim(
            project_file,
            100,
            from_pid=11111,
            to_pid=22222,
            new_workflow="ace(run)-new",
            new_artifacts_timestamp="20260501120000",
            cl_name="feature",
        )
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 22222
        assert claims[0].workflow == "ace(run)-new"
        assert claims[0].artifacts_timestamp == "20260501120000"
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


class TestWorkspaceClaimLedger:
    """Every claim/hold/transfer/release mutation is durably ledgered."""

    def test_claim_then_release_round_trip_produces_two_records(
        self, tmp_path: Path
    ) -> None:
        project_file = _create_project_file_with_running(tmp_path)
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        try:
            with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
                claim_result = claim_workspace(
                    project_file,
                    5,
                    "crs",
                    12345,
                    "my_feature",
                    caller_tag="test-claim",
                )
                assert claim_result.success is True

                release_result = release_workspace(
                    project_file, 5, "crs", "my_feature", caller_tag="test-release"
                )
                assert release_result.success is True

                records = read_ledger_records(ledger_file=ledger_file)

            assert [r["operation"] for r in records] == ["claim", "release"]

            claim_record = records[0]
            assert claim_record["success"] is True
            assert claim_record["caller_tag"] == "test-claim"
            assert claim_record["before"] == []
            assert claim_record["after"] == [
                {
                    "workspace_num": 5,
                    "workflow": "crs",
                    "cl_name": "my_feature",
                    "pid": 12345,
                    "artifacts_timestamp": None,
                    "pinned": False,
                }
            ]

            release_record = records[1]
            assert release_record["success"] is True
            assert release_record["caller_tag"] == "test-release"
            assert release_record["claim_pid"] == 12345
            assert release_record["before"] == claim_record["after"]
            assert release_record["after"] == []
        finally:
            Path(project_file).unlink()

    def test_claim_rejection_is_ledgered_with_unchanged_occupancy(
        self, tmp_path: Path
    ) -> None:
        project_file = _create_project_file_with_running(
            tmp_path, running_claims=[WorkspaceClaim(1, "crs", "existing", pid=11111)]
        )
        ledger_file = str(tmp_path / "workspace_claims.jsonl")
        try:
            with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
                result = claim_workspace(project_file, 1, "run", 22222, "other")
                assert result.success is False

                records = read_ledger_records(ledger_file=ledger_file)

            assert len(records) == 1
            record = records[0]
            assert record["success"] is False
            assert record["error"]
            assert record["before"] == record["after"]
            assert record["before"][0]["pid"] == 11111
        finally:
            Path(project_file).unlink()
