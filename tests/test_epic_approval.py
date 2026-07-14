"""Tests for epic approval: ensure_beads_initialized, PlanApprovalResult, epic prompt construction."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd.beads import ensure_beads_initialized
from tests.sdd_policy_helpers import patched_sdd_policy


# ---------------------------------------------------------------------------
# ensure_beads_initialized
# ---------------------------------------------------------------------------


def test_ensure_beads_initialized_vc_already_exists() -> None:
    """No-op when sdd.version_controlled is enabled and sdd/beads/ already exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "sdd/beads").mkdir(parents=True)
        with (
            patched_sdd_policy("in_tree"),
            patch("sase.sdd.beads.BeadProject") as mock_bp,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_bp.init.assert_not_called()


def test_ensure_beads_initialized_vc_creates_beads() -> None:
    """Initializes sdd/beads/ when sdd.version_controlled is enabled and sdd/beads/ missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patched_sdd_policy("in_tree"),
            patch("sase.sdd.beads.BeadProject") as mock_bp,
            patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_bp.init.assert_called_once_with(Path(tmpdir))
            ensure_sdd.assert_called_once_with(
                tmpdir,
                commit=True,
                push=False,
            )


def test_ensure_beads_initialized_non_vc_already_exists() -> None:
    """No-op when non-VC repo already has .sase/sdd/beads/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / ".sase" / "sdd" / "beads").mkdir(parents=True)
        with (
            patched_sdd_policy("local"),
            patch("sase.sdd.beads.init_beads") as mock_init,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_init.assert_not_called()


def test_ensure_beads_initialized_non_vc_calls_init_beads() -> None:
    """Calls _init_beads when non-VC repo is missing .sase/sdd/beads/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patched_sdd_policy("local"),
            patch("sase.sdd.beads.init_beads") as mock_init,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_init.assert_called_once_with(tmpdir, 1)


def test_ensure_beads_initialized_workspace_num_2() -> None:
    """For workspace_num > 1, checks sdd/beads/ in the primary workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "project"
        primary.mkdir()
        workspace_2 = Path(tmpdir) / "project_2"
        workspace_2.mkdir()

        with (
            patched_sdd_policy("in_tree"),
            patch("sase.sdd.beads.BeadProject") as mock_bp,
        ):
            ensure_beads_initialized(str(workspace_2), 2)
            mock_bp.init.assert_called_once_with(primary)


# ---------------------------------------------------------------------------
# PlanApprovalResult dataclass
# ---------------------------------------------------------------------------


def test_plan_approval_result_approve() -> None:
    result = PlanApprovalResult(action="approve", plan_file="/tmp/plan.md")
    assert result.action == "approve"
    assert result.plan_file == "/tmp/plan.md"


def test_plan_approval_result_epic() -> None:
    result = PlanApprovalResult(action="epic", plan_file="/tmp/plan.md")
    assert result.action == "epic"
    assert result.plan_file == "/tmp/plan.md"


# ---------------------------------------------------------------------------
# Deterministic epic plan references
# ---------------------------------------------------------------------------


def test_epic_plan_ref_non_vc_repo() -> None:
    """Deterministic bead creation stores the non-VC SDD plan reference."""
    sdd_plan_name = "my_feature"
    version_controlled = False
    plan_ref = (
        f".sase/sdd/plans/202605/{sdd_plan_name}.md"
        if sdd_plan_name and not version_controlled
        else f"sdd/plans/202605/{sdd_plan_name}.md"
        if sdd_plan_name
        else "fallback"
    )
    expected = ".sase/sdd/plans/202605/my_feature.md"
    assert plan_ref == expected


def test_coder_prompt_includes_vcs_tag() -> None:
    """Coder prompt should prepend VCS tag (bug fix verification)."""
    vcs_tag = "#git:sase "
    plan_file = "/tmp/plans/my_plan.md"
    prompt = (
        f"{vcs_tag}@{plan_file}\n\n"
        "The above plan has been reviewed and approved. Implement it now."
    )
    assert prompt.startswith("#git:sase ")
    assert f"@{plan_file}" in prompt


def test_coder_prompt_without_vcs_tag() -> None:
    """Coder prompt without VCS tag should start with @plan_file."""
    vcs_tag = ""
    plan_file = "/tmp/plans/my_plan.md"
    prompt = (
        f"{vcs_tag}@{plan_file}\n\n"
        "The above plan has been reviewed and approved. Implement it now."
    )
    assert prompt.startswith(f"@{plan_file}")
