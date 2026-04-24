"""Shared fixtures for CommitWorkflow tests.

Not a conftest so the fixtures only apply when a test file opts in by
importing the re-exported name as an autouse fixture.
"""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

_CONFIG_TARGET = "sase.workflows.commit.precommit_hooks.load_merged_config"


@pytest.fixture
def no_precommit_hooks() -> Iterator[None]:
    """Stub out precommit, SASE_PLAN, and the three workflow hook call sites.

    Covers: precommit command execution, SASE_PLAN env, and the
    handle_beads / handle_sase_plan / capture_pre_commit_diff calls in
    CommitWorkflow.run that otherwise shell out on every invocation.
    """
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
        patch("sase.workflows.commit.workflow.handle_beads", return_value=None),
        patch("sase.workflows.commit.workflow.handle_sase_plan", return_value=None),
        patch(
            "sase.workflows.commit.workflow.capture_pre_commit_diff",
            return_value=None,
        ),
    ):
        yield
