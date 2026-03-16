"""Tests for epic approval: check_epic_available, PlanApprovalResult, epic prompt construction."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd import check_epic_available


# ---------------------------------------------------------------------------
# check_epic_available
# ---------------------------------------------------------------------------


def test_check_epic_available_both_conditions_met() -> None:
    """Returns True when sdd.version_controlled is enabled and .beads/ exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / ".beads").mkdir()
        with patch("sase.sdd.get_sdd_config", return_value=True):
            assert check_epic_available(tmpdir, 1) is True


def test_check_epic_available_no_beads_dir() -> None:
    """Returns False when .beads/ directory doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("sase.sdd.get_sdd_config", return_value=True):
            assert check_epic_available(tmpdir, 1) is False


def test_check_epic_available_sdd_disabled() -> None:
    """Returns False when sdd.version_controlled is disabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / ".beads").mkdir()
        with patch("sase.sdd.get_sdd_config", return_value=False):
            assert check_epic_available(tmpdir, 1) is False


def test_check_epic_available_both_missing() -> None:
    """Returns False when both conditions are missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("sase.sdd.get_sdd_config", return_value=False):
            assert check_epic_available(tmpdir, 1) is False


def test_check_epic_available_workspace_num_2() -> None:
    """For workspace_num > 1, checks .beads/ in the primary workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create primary workspace (without _2 suffix) with .beads/
        primary = Path(tmpdir) / "project"
        primary.mkdir()
        (primary / ".beads").mkdir()
        workspace_2 = Path(tmpdir) / "project_2"
        workspace_2.mkdir()

        with patch("sase.sdd.get_sdd_config", return_value=True):
            assert check_epic_available(str(workspace_2), 2) is True


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
# Epic prompt construction (mirrors axe_run_agent_runner.py logic)
# ---------------------------------------------------------------------------


def test_epic_prompt_with_vcs_tag() -> None:
    """Epic prompt should include VCS tag prefix and bd/new_epic xprompt."""
    vcs_tag = "#git:sase "
    sdd_plan_name = "epic_approval"
    expected = "#git:sase #bd/new_epic:plans/epic_approval.md"
    assert f"{vcs_tag}#bd/new_epic:plans/{sdd_plan_name}.md" == expected


def test_epic_prompt_without_vcs_tag() -> None:
    """Epic prompt without VCS tag should just have the xprompt."""
    vcs_tag = ""
    sdd_plan_name = "my_feature"
    expected = "#bd/new_epic:plans/my_feature.md"
    assert f"{vcs_tag}#bd/new_epic:plans/{sdd_plan_name}.md" == expected


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
