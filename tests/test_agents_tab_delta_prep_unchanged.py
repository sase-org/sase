"""Skip unchanged exact-delta preparation without treating misses as deletions."""

from __future__ import annotations

from copy import deepcopy

from sase.ace.tui.actions.agents._loading_graph import (
    exact_delta_consumed_projection_unchanged,
)
from tests._agents_tab_query_helpers import make_agent


def test_unchanged_incoming_rows_skip_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
        make_agent(cl_name="other", raw_suffix="20260918090100", status="DONE"),
    ]
    incoming = [deepcopy(cached[0])]
    assert exact_delta_consumed_projection_unchanged(incoming, cached) is True


def test_status_change_does_not_skip_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    incoming = [deepcopy(cached[0])]
    incoming[0].status = "DONE"
    assert exact_delta_consumed_projection_unchanged(incoming, cached) is False


def test_new_identity_does_not_skip_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    incoming = [
        make_agent(cl_name="fresh", raw_suffix="20260918090200", status="RUNNING"),
    ]
    assert exact_delta_consumed_projection_unchanged(incoming, cached) is False


def test_empty_incoming_does_not_skip_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    assert exact_delta_consumed_projection_unchanged([], cached) is False


def test_deleted_dirs_do_not_skip_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    incoming = [deepcopy(cached[0])]
    assert (
        exact_delta_consumed_projection_unchanged(
            incoming,
            cached,
            deleted_artifact_dirs={"/tmp/artifacts/keep"},
        )
        is False
    )


def test_live_hint_only_does_not_force_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    cached[0].live_file_change_hint = True
    incoming = [deepcopy(cached[0])]
    incoming[0].live_file_change_hint = False
    incoming[0].linked_file_change_hint = True
    assert exact_delta_consumed_projection_unchanged(incoming, cached) is True


def test_claim_and_liveness_fields_force_prep() -> None:
    cached = [
        make_agent(cl_name="keep", raw_suffix="20260918090000", status="RUNNING"),
    ]
    claim = deepcopy(cached[0])
    claim.from_running_claim = True
    assert exact_delta_consumed_projection_unchanged([claim], cached) is False
    live = deepcopy(cached[0])
    live.runner_is_live = True
    assert exact_delta_consumed_projection_unchanged([live], cached) is False
    unverified = deepcopy(cached[0])
    unverified.pid_liveness_unverified = True
    assert exact_delta_consumed_projection_unchanged([unverified], cached) is False


def test_parent_timestamp_change_does_not_skip_prep() -> None:
    cached = [
        make_agent(
            cl_name="child",
            raw_suffix="20260918090100",
            status="RUNNING",
            parent_timestamp="20260918090000",
        ),
    ]
    incoming = [deepcopy(cached[0])]
    incoming[0].parent_timestamp = "20260918085900"
    assert exact_delta_consumed_projection_unchanged(incoming, cached) is False
