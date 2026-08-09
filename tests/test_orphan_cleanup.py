from types import SimpleNamespace
from unittest.mock import patch as mock_patch

from sase.ace.scheduler.orphan_cleanup import cleanup_orphaned_workspace_claims
from sase.running_field import WorkspaceClaim


def test_orphan_cleanup_skips_pinned_failed_agent_hold() -> None:
    patch = SimpleNamespace(
        name="feature",
        status="Reverted",
        file_path="/tmp/projects/proj/proj.sase",
    )
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow="run",
        cl_name="feature",
        pid=11111,
        artifacts_timestamp="20260712120000",
        pinned=True,
    )

    with (
        mock_patch(
            "sase.ace.scheduler.orphan_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        mock_patch(
            "sase.ace.scheduler.orphan_cleanup.is_process_running"
        ) as is_running,
        mock_patch("sase.ace.scheduler.orphan_cleanup.release_workspace") as release,
    ):
        released = cleanup_orphaned_workspace_claims([patch])  # type: ignore[list-item]

    assert released == 0
    is_running.assert_not_called()
    release.assert_not_called()
