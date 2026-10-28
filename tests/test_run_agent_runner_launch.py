"""Tests for runner-side bead launch promotion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from sase.axe.run_agent_runner_bead import (
    _schedule_launch_claim_convergence,
    closed_bead_launch_notice,
)
from sase.axe.run_agent_runner_launch import _promote_bead_claim
from sase.bead.model import Issue, Resolution, Status


def test_launch_claim_hints_use_the_marker_project_key(monkeypatch, tmp_path) -> None:
    marker = SimpleNamespace(project_key="gh_acme__widget", project_name="widget")
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _path: (str(tmp_path), marker),
    )
    from sase.bead import background_store

    schedule = patch.object(background_store, "schedule_beads_sidecar_convergence")
    with schedule as schedule_hint:
        _schedule_launch_claim_convergence(str(tmp_path))

    schedule_hint.assert_called_once_with("gh_acme__widget")


@pytest.mark.parametrize("force_reuse", [False, True], ids=["normal", "force-reuse"])
def test_promote_closed_bead_records_context_metadata_and_notice(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    force_reuse: bool,
) -> None:
    monkeypatch.setattr(
        "sase.core.time.get_timezone",
        lambda: ZoneInfo("America/New_York"),
    )
    issue = Issue(
        id="sase-x.1",
        title="Closed bead",
        status=Status.CLOSED,
        closed_at="2026-06-16T15:00:00Z",
        resolution=Resolution.DONE,
    )
    state = SimpleNamespace(
        agent_name="worker",
        timestamp="260616_120000",
        launch_submitted_at="2026-06-16T16:00:00.900000Z",
        artifacts_timestamp="260616_120001",
        workspace_dir=str(tmp_path),
        workspace_num=12,
        artifacts_dir=str(tmp_path / "artifacts"),
        prompt="Continue the assigned work.",
        held_bead_claim=object(),
    )
    association = SimpleNamespace(owner_name="prior-owner") if force_reuse else None
    bootstrap = SimpleNamespace(
        info=SimpleNamespace(bead_id=issue.id),
        force_reuse_bead_association=association,
        agent_meta={"launch_submitted_at": state.launch_submitted_at},
    )
    notice = closed_bead_launch_notice(issue)

    with (
        patch(
            "sase.axe.run_agent_runner_launch.claim_bead_for_agent_launch",
            return_value=issue,
        ) as claim,
        patch("sase.axe.run_agent_runner_launch.overlay_live_auto_keys"),
        patch("sase.axe.run_agent_runner_launch.write_agent_meta"),
        patch("sase.axe.run_agent_runner_launch.clear_bead_claim_marker"),
    ):
        _promote_bead_claim(state, bootstrap)
        _promote_bead_claim(state, bootstrap)

    assert claim.call_count == 2
    for call in claim.call_args_list:
        assert call.kwargs["submitted_at"] == state.launch_submitted_at
        assert call.kwargs["run_id"] == "260616_120001"
        if force_reuse:
            assert call.kwargs["force_reuse_prior_owner"] == "prior-owner"
        else:
            assert "force_reuse_prior_owner" not in call.kwargs
    assert state.prompt == f"{notice}\n\nContinue the assigned work."
    assert bootstrap.agent_meta["bead_launch_disposition"] == "closed_attached"
    assert bootstrap.agent_meta["bead_launch_prior_closed_at"] == issue.closed_at
    assert bootstrap.agent_meta["bead_launch_prior_resolution"] == "done"
    assert bootstrap.agent_meta["bead_claim_promoted"] is True
    assert state.held_bead_claim is None


def test_promote_open_bead_does_not_add_closed_notice_or_metadata(
    tmp_path,
) -> None:
    issue = Issue(id="sase-x.2", title="Open bead", status=Status.IN_PROGRESS)
    state = SimpleNamespace(
        agent_name="worker",
        timestamp="260616_120000",
        launch_submitted_at="2026-06-16T16:00:00.900000Z",
        artifacts_timestamp="260616_120001",
        workspace_dir=str(tmp_path),
        workspace_num=12,
        artifacts_dir=str(tmp_path / "artifacts"),
        prompt="Continue the assigned work.",
        held_bead_claim=None,
    )
    bootstrap = SimpleNamespace(
        info=SimpleNamespace(bead_id=issue.id),
        force_reuse_bead_association=None,
        agent_meta={"launch_submitted_at": state.launch_submitted_at},
    )

    with (
        patch(
            "sase.axe.run_agent_runner_launch.claim_bead_for_agent_launch",
            return_value=issue,
        ) as claim,
        patch("sase.axe.run_agent_runner_launch.overlay_live_auto_keys"),
        patch("sase.axe.run_agent_runner_launch.write_agent_meta"),
        patch("sase.axe.run_agent_runner_launch.clear_bead_claim_marker"),
    ):
        _promote_bead_claim(state, bootstrap)

    assert state.prompt == "Continue the assigned work."
    assert "bead_launch_disposition" not in bootstrap.agent_meta
    assert "bead_launch_prior_closed_at" not in bootstrap.agent_meta
    assert "bead_launch_prior_resolution" not in bootstrap.agent_meta
    assert bootstrap.agent_meta["bead_claim_promoted"] is True
    assert claim.call_args.kwargs["submitted_at"] == state.launch_submitted_at
    assert claim.call_args.kwargs["run_id"] == "260616_120001"


def test_promote_legacy_closed_launch_does_not_infer_submission_from_launch_id(
    tmp_path,
) -> None:
    issue = Issue(
        id="sase-x.3",
        title="Legacy closed bead",
        status=Status.CLOSED,
        closed_at="2026-06-16T15:00:00Z",
        resolution=Resolution.DONE,
    )
    state = SimpleNamespace(
        agent_name="worker",
        timestamp="260616_120002",
        artifacts_timestamp="260616_120001",
        workspace_dir=str(tmp_path),
        workspace_num=12,
        artifacts_dir=str(tmp_path / "artifacts"),
        prompt="Continue the assigned work.",
        held_bead_claim=None,
    )
    bootstrap = SimpleNamespace(
        info=SimpleNamespace(bead_id=issue.id),
        force_reuse_bead_association=None,
        agent_meta={},
    )

    with (
        patch(
            "sase.axe.run_agent_runner_launch.claim_bead_for_agent_launch",
            return_value=issue,
        ) as claim,
        patch("sase.axe.run_agent_runner_launch.overlay_live_auto_keys"),
        patch("sase.axe.run_agent_runner_launch.write_agent_meta"),
        patch("sase.axe.run_agent_runner_launch.clear_bead_claim_marker"),
    ):
        _promote_bead_claim(state, bootstrap)

    assert claim.call_args.kwargs["submitted_at"] is None
