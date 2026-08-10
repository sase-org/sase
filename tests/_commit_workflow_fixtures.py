"""Shared fixtures for CommitWorkflow tests.

Not a conftest so the fixtures only apply when a test file opts in by
importing the re-exported name as an autouse fixture.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity

_CONFIG_TARGET = "sase.workflows.commit.command_hooks.load_merged_config"


@pytest.fixture(name="artifacts_dir")
def commit_artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Direct checkpoint persistence to a hermetic artifacts directory."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def make_provider(
    *, dispatch_result: tuple[bool, str | None], is_conflict: bool = False
) -> MagicMock:
    """Build a VCS provider mock with the standard workflow behavior."""
    provider = MagicMock()
    provider._provider_name = "git"
    provider.create_commit.return_value = dispatch_result
    provider.create_proposal.return_value = dispatch_result
    provider.create_pull_request.return_value = dispatch_result
    provider.is_sync_in_progress.return_value = is_conflict
    provider.get_conflicted_files.return_value = ["a.py"] if is_conflict else []
    provider.diff.return_value = (True, None)
    return provider


@pytest.fixture
def no_commit_hooks() -> Iterator[None]:
    """Stub out commit hooks, SASE_PLAN, and workflow shell call sites.

    Covers: before/after command execution, SASE_PLAN env, and the
    handle_beads / handle_sase_plan / capture_pre_commit_diff calls in
    CommitWorkflow.run that otherwise shell out on every invocation.
    """
    with (
        patch(
            _CONFIG_TARGET,
            return_value={"commit_hooks": {"before": "", "after": ""}},
        ),
        patch.dict(
            "os.environ",
            {"SASE_PLAN": "", "SASE_AGENT_NAME": "", "SASE_ARTIFACTS_DIR": ""},
            clear=False,
        ),
        patch(
            "sase.config.require_agent_owner_identity",
            return_value=AgentOwnerIdentity("test-user", "test-host"),
        ),
        patch("sase.workflows.commit.workflow.handle_beads", return_value=None),
        patch("sase.workflows.commit.workflow.handle_sase_plan", return_value=None),
        patch(
            "sase.workflows.commit.workflow.close_task_bead_after_commit",
            return_value=False,
        ),
        patch(
            "sase.workflows.commit.workflow.capture_pre_commit_diff",
            return_value=None,
        ),
        patch(
            "sase.bead_pages.links.resolve_bead_commit_tag",
            side_effect=lambda bead_id, **_kwargs: bead_id,
        ),
    ):
        yield
