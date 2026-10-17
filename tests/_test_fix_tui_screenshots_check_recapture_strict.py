"""Strict inventory policy tests for check mode."""

from __future__ import annotations

from tests.ace.tui.visual._visual_capture import InventoryReport
from tests.ace.tui.visual._visual_maintenance_verify import check_mode_strict_errors


def _strict_inventory(
    *,
    reasons: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
    session_exitstatus: int = 0,
    scope: str = "full",
) -> InventoryReport:
    """Build the strict-policy inputs without running the visual suite."""
    return InventoryReport(
        run_id="strict-test",
        requested_scope=scope,
        full_inventory=False,
        pruning_allowed=False,
        complete=False,
        session_exitstatus=session_exitstatus,
        collectonly=False,
        reasons=reasons,
        errors=errors,
        workers_expected=("controller",),
        workers_seen=("controller",),
        lost_workers=(),
        captures=(),
        worker_sessions=(),
        collected_visual_node_ids=(),
        executed_visual_node_ids=(),
        skipped_visual_node_ids=(),
        xfailed_visual_node_ids=(),
        failed_visual_node_ids=(),
        deselected_visual_node_ids=(),
        roots_executed=(),
    )


def test_strict_ignores_cured_failure_and_ordinary_session_status() -> None:
    inventory = _strict_inventory(
        reasons=("failed_node:X", "session_exitstatus:1", "requested_scope_targeted"),
        scope="targeted",
    )
    assert check_mode_strict_errors(inventory, recovered=["X"]) == ()


def test_strict_keeps_uncured_failed_node() -> None:
    inventory = _strict_inventory(
        reasons=("failed_node:X", "session_exitstatus:1"),
    )
    errors = check_mode_strict_errors(inventory, recovered=[])
    assert any("failed_node:X" in error for error in errors)
    assert not any("session_exitstatus:1" in error for error in errors)


def test_strict_flags_internal_error_and_child_exit() -> None:
    inventory = _strict_inventory(
        reasons=("session_exitstatus:3",), session_exitstatus=3
    )
    errors = check_mode_strict_errors(inventory, recovered=["X"], child_exit_code=3)
    assert any("session_exitstatus:3" in error for error in errors)
    assert any("child_exit_code:3" in error for error in errors)


def test_strict_flags_exit_disagreement() -> None:
    inventory = _strict_inventory(reasons=(), session_exitstatus=0)
    errors = check_mode_strict_errors(inventory, recovered=[], child_exit_code=3)
    assert any("exit_disagreement" in error for error in errors)


def test_strict_targeted_scope_ignores_missing_root() -> None:
    inventory = _strict_inventory(reasons=("visual_root_unexecuted:pager",))
    assert check_mode_strict_errors(inventory, recovered=[], scope="targeted") == ()
    assert check_mode_strict_errors(inventory, recovered=[], scope="full") != ()


def test_strict_flags_collection_mismatch_and_unexpected_worker() -> None:
    inventory = _strict_inventory(
        reasons=("collection_mismatch", "unexpected_worker:controller-1"),
    )
    errors = check_mode_strict_errors(inventory, recovered=["X"])
    assert any("collection_mismatch" in error for error in errors)
    assert any("unexpected_worker" in error for error in errors)


def test_strict_flags_skipped_nodes_and_protocol_errors() -> None:
    inventory = _strict_inventory(
        reasons=("skipped_node:S",),
        errors=("worker_error:controller:boom",),
    )
    errors = check_mode_strict_errors(inventory, recovered=["S"])
    assert any("skipped_node:S" in error for error in errors)
    assert any("worker_error" in error for error in errors)
