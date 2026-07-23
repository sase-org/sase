"""Shared fixtures for CommitWorkflow tests.

Not a conftest so the fixtures only apply when a test file opts in by
importing the re-exported name as an autouse fixture.
"""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity

_CONFIG_TARGET = "sase.workflows.commit.commit_hooks.load_merged_config"


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
            "sase.workflows.commit.workflow.capture_pre_commit_diff",
            return_value=None,
        ),
    ):
        yield
