"""Finalize and no-proposal summary tests for axe runner utils.

Split from ``tests.test_axe_runner_utils``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.runner_reporting import (
    build_no_proposal_error_summary,
    finalize_axe_runner,
)

__all__ = [
    "test_finalize_axe_runner_handles_errors",
    "test_finalize_axe_runner_no_matching_patch",
    "test_finalize_axe_runner_success",
    "test_no_proposal_summary_prefers_generic_finalizer_result",
    "test_no_proposal_summary_reads_historical_commit_result_only",
]


def test_finalize_axe_runner_success() -> None:
    """Test finalize_axe_runner calls all required functions."""
    mock_cs = MagicMock()
    mock_cs.name = "test_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_reporting.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.sase",
            changespec_name="test_cl",
            proposal_id="abc123",
            exit_code=0,
            update_suffix_fn=mock_update_suffix,
        )

        # Check update_suffix was called
        assert len(update_suffix_calls) == 1
        assert update_suffix_calls[0] == (mock_cs, "/path/project.sase", "abc123", 0)


def test_no_proposal_summary_prefers_generic_finalizer_result(tmp_path: Path) -> None:
    (tmp_path / "commit_finalizer_result.json").write_text(
        json.dumps(
            {
                "status": "clean",
                "reason": "no_changes",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "finalizer_result.json").write_text(
        json.dumps(
            {
                "status": "success",
                "instances": [
                    {
                        "instance_id": "lint",
                        "status": "success",
                    },
                    {
                        "instance_id": "commit",
                        "status": "success",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert build_no_proposal_error_summary(str(tmp_path)) == (
        "Agent completed but no proposal was created — "
        "finalizers: success [lint=success, commit=success]"
    )


def test_no_proposal_summary_reads_historical_commit_result_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "commit_finalizer_result.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "reason": "dirty_after_max_passes",
                "error": "uncommitted changes remain",
            }
        ),
        encoding="utf-8",
    )

    assert build_no_proposal_error_summary(str(tmp_path)) == (
        "Agent completed but no proposal was created — "
        "commit finalizer: failed (dirty_after_max_passes): "
        "uncommitted changes remain"
    )


def test_finalize_axe_runner_no_matching_patch() -> None:
    """Test finalize_axe_runner skips suffix update when patch not found."""
    mock_cs = MagicMock()
    mock_cs.name = "other_cl"

    update_suffix_calls: list[tuple[object, str, str | None, int]] = []

    def mock_update_suffix(cs: object, pf: str, pid: str | None, ec: int) -> None:
        update_suffix_calls.append((cs, pf, pid, ec))

    with patch(
        "sase.axe.runner_reporting.parse_project_file",
        return_value=[mock_cs],
    ):
        finalize_axe_runner(
            project_file="/path/project.sase",
            changespec_name="test_cl",
            proposal_id="abc123",
            exit_code=0,
            update_suffix_fn=mock_update_suffix,
        )

        # update_suffix should not be called - no matching patch
        assert len(update_suffix_calls) == 0


def test_finalize_axe_runner_handles_errors() -> None:
    """Test finalize_axe_runner handles errors gracefully."""
    with patch(
        "sase.axe.runner_reporting.parse_project_file",
        side_effect=Exception("Parse error"),
    ):
        # Should not raise - errors are caught and printed
        finalize_axe_runner(
            project_file="/path/project.sase",
            changespec_name="test_cl",
            proposal_id=None,
            exit_code=1,
            update_suffix_fn=lambda *args: None,
        )
