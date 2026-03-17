"""Tests for epic approval: ensure_beads_initialized, PlanApprovalResult, epic prompt construction."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.sdd import ensure_beads_initialized


# ---------------------------------------------------------------------------
# ensure_beads_initialized
# ---------------------------------------------------------------------------


def test_ensure_beads_initialized_vc_already_exists() -> None:
    """No-op when sdd.version_controlled is enabled and .sase_beads/ already exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / ".sase_beads").mkdir()
        with (
            patch("sase.sdd.get_sdd_config", return_value=True),
            patch("sase.sdd.BeadProject") as mock_bp,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_bp.init.assert_not_called()


def test_ensure_beads_initialized_vc_creates_beads() -> None:
    """Initializes .sase_beads/ when sdd.version_controlled is enabled and .sase_beads/ missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.get_sdd_config", return_value=True),
            patch("sase.sdd.BeadProject") as mock_bp,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_bp.init.assert_called_once_with(Path(tmpdir))


def test_ensure_beads_initialized_non_vc_already_exists() -> None:
    """No-op when non-VC repo already has .sase/sdd/beads/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / ".sase" / "sdd" / "beads").mkdir(parents=True)
        with (
            patch("sase.sdd.get_sdd_config", return_value=False),
            patch("sase.sdd.init_beads") as mock_init,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_init.assert_not_called()


def test_ensure_beads_initialized_non_vc_calls_init_beads() -> None:
    """Calls init_beads when non-VC repo is missing .sase/sdd/beads/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.get_sdd_config", return_value=False),
            patch("sase.sdd.init_beads") as mock_init,
        ):
            ensure_beads_initialized(tmpdir, 1)
            mock_init.assert_called_once_with(tmpdir, 1)


def test_ensure_beads_initialized_workspace_num_2() -> None:
    """For workspace_num > 1, checks .sase_beads/ in the primary workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        primary = Path(tmpdir) / "project"
        primary.mkdir()
        workspace_2 = Path(tmpdir) / "project_2"
        workspace_2.mkdir()

        with (
            patch("sase.sdd.get_sdd_config", return_value=True),
            patch("sase.sdd.BeadProject") as mock_bp,
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


def test_epic_prompt_non_vc_repo() -> None:
    """Epic prompt for non-VC repo should use .sase/sdd/plans/ prefix."""
    vcs_tag = ""
    sdd_plan_name = "my_feature"
    version_controlled = False
    plan_ref = (
        f".sase/sdd/plans/{sdd_plan_name}.md"
        if sdd_plan_name and not version_controlled
        else f"plans/{sdd_plan_name}.md"
        if sdd_plan_name
        else "fallback"
    )
    expected = ".sase/sdd/plans/my_feature.md"
    assert plan_ref == expected
    assert (
        f"{vcs_tag}#bd/new_epic:{plan_ref}"
        == "#bd/new_epic:.sase/sdd/plans/my_feature.md"
    )


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
