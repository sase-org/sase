"""Last-resort workspace re-creation and non-holding setup failures (sase-16e.3).

Test implementations live in private modules so this public module path remains
stable for pytest collection and imports.
"""

from __future__ import annotations

from tests._axe_run_agent_exec_retry_helpers import (
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
)
from tests._axe_runner_workspace_reclone_git import (
    TestCorruptCheckoutPath,
    TestRecreateEndToEnd,
    TestRecreateManagedWorkspaceRealGit,
    TestRecreatePreservationGuard,
)
from tests._axe_runner_workspace_reclone_setup import (
    TestLinkedRepoPrepareReclone,
    TestPrepareWorkspaceIfNeededReclone,
    TestRecreateRefusesPrimary,
    TestRetryPrepareWorkspaceReclone,
)

__all__ = [
    "TestCorruptCheckoutPath",
    "TestLinkedRepoPrepareReclone",
    "TestPrepareWorkspaceIfNeededReclone",
    "TestRecreateEndToEnd",
    "TestRecreateManagedWorkspaceRealGit",
    "TestRecreatePreservationGuard",
    "TestRecreateRefusesPrimary",
    "TestRetryPrepareWorkspaceReclone",
]
