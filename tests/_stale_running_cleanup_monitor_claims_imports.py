"""Monitor import isolation cases for stale-running cleanup."""

import importlib.abc
import sys
from unittest.mock import patch

import pytest

from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.running_field import WorkspaceClaim


def _block_monitor_start_import(
    monkeypatch: pytest.MonkeyPatch,
    *submodules: str,
) -> None:
    """Make each ``sase.monitor.<submodule>`` raise SyntaxError on import.

    Defaults to ``start`` and ``claims``: the claim label lives in the
    ``claims`` leaf, and ``start`` is the heavy supervisor stack.
    """

    import sase.monitor as monitor_pkg

    names = submodules or ("start", "claims")
    blocked = {f"sase.monitor.{name}" for name in names}

    class _BrokenMonitorModules(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> None:
            del path, target
            if fullname in blocked:
                raise SyntaxError(f"simulated {fullname} syntax error")
            return None

    monkeypatch.setattr(sys, "meta_path", [_BrokenMonitorModules(), *sys.meta_path])
    for name in names:
        monkeypatch.delitem(sys.modules, f"sase.monitor.{name}", raising=False)
        if name in vars(monitor_pkg):
            monkeypatch.delattr(monitor_pkg, name)


def test_cleanup_skip_monitor_claims_survives_unimportable_monitor_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_monitor_claims=True must not import sase.monitor.start."""
    _block_monitor_start_import(monkeypatch)
    monitor_claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    other_claim = WorkspaceClaim(
        workspace_num=11,
        workflow="run",
        cl_name="other",
        pid=44444,
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[monitor_claim, other_claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries(skip_monitor_claims=True)

    assert isinstance(released, int)
    assert released == 1
    release.assert_called_once_with(
        project_file,
        11,
        "run",
        "other",
        caller_tag="stale-cleanup",
        expected_pid=other_claim.pid,
        artifacts_timestamp=other_claim.artifacts_timestamp,
    )


def test_cleanup_imports_monitor_claim_label_when_not_skipping_monitor_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_monitor_claims=False reads the label from sase.monitor.claims."""
    _block_monitor_start_import(monkeypatch, "claims")
    with pytest.raises(SyntaxError, match="simulated sase.monitor.claims syntax error"):
        cleanup_stale_running_entries(skip_monitor_claims=False)


def test_cleanup_never_imports_monitor_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 5 s sweep reads the claim label without the monitor supervisor stack."""
    _block_monitor_start_import(monkeypatch, "start")
    with patch(
        "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
        return_value=[],
    ):
        assert cleanup_stale_running_entries(skip_monitor_claims=False) == 0
