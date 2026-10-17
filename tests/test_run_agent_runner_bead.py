"""Tests for the runner's post-preparation bead claim helper."""

from pathlib import Path

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from tests import (
    _run_agent_runner_bead_claim_cases as claim_cases,
    _run_agent_runner_bead_error_cases as error_cases,
    _run_agent_runner_bead_sidecar_cases as sidecar_cases,
)


def test_claim_helper_claims_in_tree_store_and_export_reflects_claim(
    tmp_path: Path,
) -> None:
    claim_cases.case_claim_helper_claims_in_tree_store_and_export_reflects_claim(
        tmp_path
    )


def test_claim_helper_records_closed_launch_with_distinct_commit_subject(
    tmp_path: Path,
) -> None:
    claim_cases.case_claim_helper_records_closed_launch_with_distinct_commit_subject(
        tmp_path
    )


def test_force_reuse_closed_bead_attaches_without_changing_prior_assignee(
    tmp_path: Path,
) -> None:
    claim_cases.case_force_reuse_closed_bead_attaches_without_changing_prior_assignee(
        tmp_path
    )


def test_claim_helper_commits_managed_store_and_rejects_active_reassignment(
    tmp_path: Path,
) -> None:
    claim_cases.case_claim_helper_commits_managed_store_and_rejects_active_reassignment(
        tmp_path
    )


def test_claim_helper_retains_force_reuse_in_progress_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim_cases.case_claim_helper_retains_force_reuse_in_progress_without_mutation(
        tmp_path, monkeypatch
    )


def test_claim_helper_rejects_force_reuse_marker_for_another_owner(
    tmp_path: Path,
) -> None:
    claim_cases.case_claim_helper_rejects_force_reuse_marker_for_another_owner(tmp_path)


def test_claim_helper_routes_split_store_commit_and_publish_to_beads_sidecar(
    tmp_path: Path,
) -> None:
    sidecar_cases.case_claim_helper_routes_split_store_commit_and_publish_to_beads_sidecar(
        tmp_path
    )


def test_claim_helper_materializes_cold_split_beads_store(tmp_path: Path) -> None:
    sidecar_cases.case_claim_helper_materializes_cold_split_beads_store(tmp_path)


def test_claim_helper_materializes_before_taking_store_lock(tmp_path: Path) -> None:
    sidecar_cases.case_claim_helper_materializes_before_taking_store_lock(tmp_path)


def test_claim_helper_ensures_existing_store_before_taking_store_lock(
    tmp_path: Path,
) -> None:
    sidecar_cases.case_claim_helper_ensures_existing_store_before_taking_store_lock(
        tmp_path
    )


def test_claim_helper_retries_missing_issue_after_fresh_ensure(tmp_path: Path) -> None:
    sidecar_cases.case_claim_helper_retries_missing_issue_after_fresh_ensure(tmp_path)


def test_claim_helper_fresh_retry_still_fails_when_bead_is_missing(
    tmp_path: Path,
) -> None:
    sidecar_cases.case_claim_helper_fresh_retry_still_fails_when_bead_is_missing(
        tmp_path
    )


def test_claim_helper_leaves_schema_two_sidecar_layout_unchanged(
    tmp_path: Path,
) -> None:
    sidecar_cases.case_claim_helper_leaves_schema_two_sidecar_layout_unchanged(tmp_path)


def test_claim_helper_surfaces_beads_sidecar_materialization_failure(
    tmp_path: Path,
) -> None:
    sidecar_cases.case_claim_helper_surfaces_beads_sidecar_materialization_failure(
        tmp_path
    )


@pytest.mark.parametrize("failure", ["missing", "closed"])
def test_claim_helper_wraps_bead_mutation_errors(
    tmp_path: Path,
    failure: str,
) -> None:
    error_cases.case_claim_helper_wraps_bead_mutation_errors(tmp_path, failure)


def test_claim_helper_wraps_store_and_commit_failures(tmp_path: Path) -> None:
    error_cases.case_claim_helper_wraps_store_and_commit_failures(tmp_path)
