"""Shared approved-epic launch helper tests."""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import (
    _update_epic_launch_metadata,
    build_epic_launch_argv,
    epic_launch_origin_from_gate_source,
    finish_epic_launch,
    resolve_epic_launch_project,
    start_epic_launch_monitor,
)
from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)


def _fake_lease(tmp_path: Path, *, claim_pid: int = 4321) -> OperationalLease:
    checkout = tmp_path / "leased"
    checkout.mkdir(exist_ok=True)
    context = OperationContext(
        project="sase",
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=10,
        checkout_dir=checkout,
        primary_checkout_dir=tmp_path / "primary",
        claim_pid=claim_pid,
        claim_workflow="epic-launch",
    )
    return OperationalLease(
        project="sase",
        workflow="epic-launch",
        holder="planner",
        workspace_num=10,
        checkout_dir=checkout,
        project_file=tmp_path / "sase.sase",
        claim_pid=claim_pid,
        cl_name=None,
        context=context,
    )


def test_build_epic_launch_argv_carries_approval_linking_options() -> None:
    assert build_epic_launch_argv(
        "/tmp/epic plan.md",
        artifacts_dir="/tmp/artifacts",
        cl_name="demo",
    ) == [
        "sase",
        "bead",
        "work",
        "/tmp/epic plan.md",
        "--yes-to-all",
        "--artifacts-dir",
        "/tmp/artifacts",
        "--cl-name",
        "demo",
        "--expect-prompt-snapshot",
    ]


def test_build_epic_launch_argv_defaults_to_expecting_prompt_snapshot() -> None:
    argv = build_epic_launch_argv("/tmp/epic plan.md")

    assert "--expect-prompt-snapshot" in argv


def test_build_epic_launch_argv_omits_expect_prompt_snapshot_when_disabled() -> None:
    argv = build_epic_launch_argv(
        "/tmp/epic plan.md",
        expect_prompt_snapshot=False,
    )

    assert "--expect-prompt-snapshot" not in argv


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("tui", "ace"),
        ("telegram", "telegram"),
        ("auto_resolution", "axe"),
        ("host", "api"),
        ("unknown", "api"),
        (None, "api"),
    ],
)
def test_epic_launch_origin_maps_gate_response_sources(
    source: str | None,
    expected: str,
) -> None:
    assert epic_launch_origin_from_gate_source(source) == expected


def test_resolve_epic_launch_project_prefers_canonical_project_file(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sase_10"
    project_dir.mkdir()
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )

    with patch("sase.workspace_provider.get_workspace_name") as get_workspace_name:
        resolved = resolve_epic_launch_project(
            project_dir,
            agent_project_file=project_file,
        )

    assert resolved == "gh_sase-org__sase"
    get_workspace_name.assert_not_called()


def test_resolve_epic_launch_project_accepts_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )

    with patch("sase.workspace_provider.get_workspace_name") as get_workspace_name:
        resolved = resolve_epic_launch_project(
            None,
            agent_project_file=project_file,
        )

    assert resolved == "gh_sase-org__sase"
    get_workspace_name.assert_not_called()


def test_resolve_epic_launch_project_requires_a_project_signal() -> None:
    with pytest.raises(ValueError, match="project_dir or agent_project_file"):
        resolve_epic_launch_project(None)


@pytest.mark.parametrize("provider_name", ["sase", None])
def test_resolve_epic_launch_project_canonicalizes_compatibility_fallback(
    tmp_path: Path,
    provider_name: str | None,
) -> None:
    project_dir = tmp_path / "sase_10"

    with (
        patch(
            "sase.workspace_provider.get_workspace_name",
            return_value=provider_name,
        ),
        patch(
            "sase.project_aliases.resolve_project_alias_ref",
            return_value="gh_sase-org__sase",
        ) as resolve_alias,
    ):
        resolved = resolve_epic_launch_project(project_dir)

    assert resolved == "gh_sase-org__sase"
    resolve_alias.assert_called_once_with("sase")


def test_resolve_epic_launch_project_rejects_invalid_project_file_identity(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        pytest.raises(ValueError, match="does not identify a valid SASE project"),
    ):
        resolve_epic_launch_project(
            tmp_path / "sase_10",
            agent_project_file="project.sase",
        )

    get_workspace_name.assert_not_called()


def test_start_epic_launch_monitor_starts_literal_monitor_command(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    monitor = SimpleNamespace(monitor_id="m7k2xyz")
    lease = _fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ) as acquire,
        patch("sase.workspace_provider.lease.release_operational_lease") as release,
        patch(
            "sase.monitor.start.start_monitor",
            return_value=monitor,
        ) as start_monitor,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "planner"},
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            origin="telegram",
        )

    assert submitted is monitor
    acquire.assert_called_once_with(
        "sase",
        workflow="epic-launch",
        holder="planner",
        cl_name="demo",
    )
    release.assert_not_called()
    request = start_monitor.call_args.args[0]
    assert request.command == (
        "sase bead work "
        f"{shlex.quote(str(plan))} "
        "--yes-to-all --artifacts-dir "
        f"{shlex.quote(str(tmp_path / 'artifacts'))} "
        "--cl-name demo --expect-prompt-snapshot"
    )
    assert request.cwd == str(lease.checkout_dir)
    assert request.project_name == "sase"
    assert request.lane == "planner"
    assert request.label == "Epic launch · auth rewrite"
    assert request.reason == "Launch the approved epic from auth rewrite.md"
    assert request.next_action is None
    assert request.start_status == "EPIC APPROVED"
    assert request.stop_status == "EPIC CREATED"
    assert request.timeout_seconds == 4 * 60 * 60
    assert request.inherit_lane_workspace_claim is False
    assert request.transfer_claim_from_pid == lease.claim_pid


def test_start_epic_launch_monitor_uses_clan_member_name_as_lane(
    tmp_path: Path,
) -> None:
    request = _start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "sase-m6.6", "agent_clan": "sase-m6"},
    )

    assert request.lane == "sase-m6.6"


def test_start_epic_launch_monitor_treats_legacy_parallel_family_as_clan(
    tmp_path: Path,
) -> None:
    request = _start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={
            "name": "sase-m6.6",
            "agent_family": "sase-m6",
            "agent_family_parallel": True,
        },
    )

    assert request.lane == "sase-m6.6"


def test_start_epic_launch_monitor_uses_explicit_family_lane(
    tmp_path: Path,
) -> None:
    request = _start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "auth--plan", "agent_family": "auth"},
    )

    assert request.lane == "auth"


def test_start_epic_launch_monitor_parses_name_when_group_metadata_is_absent(
    tmp_path: Path,
) -> None:
    request = _start_epic_launch_monitor_request(
        tmp_path,
        agent_meta={"name": "sase-m6.6"},
    )

    assert request.lane == "sase-m6"


def _start_epic_launch_monitor_request(
    tmp_path: Path,
    *,
    agent_meta: dict[str, object],
) -> object:
    plan = tmp_path / "child epic.md"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(agent_meta) + "\n",
        encoding="utf-8",
    )
    monitor = SimpleNamespace(monitor_id="m7k2xyz")
    lease = _fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ),
        patch("sase.workspace_provider.lease.release_operational_lease"),
        patch(
            "sase.monitor.start.start_monitor",
            return_value=monitor,
        ) as start_monitor,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "sase-m6.6"},
            artifacts_dir=artifacts,
        )

    assert submitted is monitor
    return start_monitor.call_args.args[0]


def test_start_epic_launch_monitor_falls_back_to_leased_proc_when_lane_missing(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "auth rewrite.md"
    task = SimpleNamespace(
        task_id="k7m2xyz",
        kind="command",
        session_id=None,
    )
    lease = _fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ) as acquire,
        patch("sase.workspace_provider.lease.release_operational_lease") as release,
        patch(
            "sase.workspace_provider.lease.submit_via_lease",
            return_value=task,
        ) as submit_via_lease,
    ):
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            origin="telegram",
        )

    assert submitted is task
    release.assert_not_called()
    acquire.assert_called_once_with(
        "sase",
        workflow="epic-launch",
        holder="epic-launch",
        cl_name="demo",
    )
    request = submit_via_lease.call_args.args[0]
    assert list(request.argv) == [
        "sase",
        "bead",
        "work",
        str(plan),
        "--yes-to-all",
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
        "--cl-name",
        "demo",
        "--expect-prompt-snapshot",
    ]
    assert request.label == "Epic launch · auth rewrite"
    assert request.cwd == str(lease.checkout_dir)
    assert request.origin == "telegram"
    assert request.project == "sase"
    assert request.cl_name == "demo"
    assert request.session_id is None
    assert sorted(request.tags) == ["epic", "launch"]
    assert submit_via_lease.call_args.args[1] is lease


def test_start_epic_launch_monitor_fallback_deduplicates_active_resolved_plan(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "epic.md"
    existing = SimpleNamespace(
        task_id="existing",
        command=["sase", "bead", "work", "plans/epic.md", "--yes-to-all"],
        cwd=str(tmp_path),
        tags=["epic", "launch"],
    )
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[existing]) as read_tasks,
        patch("sase.workspace_provider.lease.acquire_operational_lease") as acquire,
    ):
        submitted = start_epic_launch_monitor(plan, project="sase")

    assert submitted is existing
    read_tasks.assert_called_once()
    assert read_tasks.call_args.kwargs["status"] == frozenset(
        {"pending", "running", "settling"}
    )
    assert read_tasks.call_args.kwargs["kind"] == {"command", "detached"}
    acquire.assert_not_called()


def test_update_epic_launch_metadata_backfills_all_host_fields(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta_path = artifacts / "agent_meta.json"
    meta_path.write_text('{"name": "planner"}\n', encoding="utf-8")

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        _update_epic_launch_metadata(
            artifacts,
            epic_id="sase-64",
            sdd_plan_path="/plans/epic.md",
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    epic_started_at = meta.pop("epic_started_at")
    assert isinstance(epic_started_at, str)
    datetime.fromisoformat(epic_started_at)
    assert meta == {
        "name": "planner",
        "epic_bead_id": "sase-64",
        "plan_committed": True,
        "sdd_plan_path": "/plans/epic.md",
    }
    update_index.assert_called_once_with(artifacts)


def test_work_command_backfills_from_structured_result_and_notifies(
    tmp_path: Path,
) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=True,
    )
    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata") as update_metadata,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )

    update_metadata.assert_called_once_with(
        tmp_path / "artifacts",
        epic_id="sase-64",
        sdd_plan_path=str(result.archived_plan_path),
    )
    assert notify.call_args.args[:3] == ("epic-launch", "demo", True)
    assert "Epic sase-64 launched" in notify.call_args.args[3][0]


def test_work_command_failure_notification_has_complete_resume_hint(
    tmp_path: Path,
) -> None:
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        finish_epic_launch(
            str(tmp_path / "epic plan.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            error=RuntimeError("launch failed"),
        )

    assert notify.call_args.args[:3] == ("epic-launch", "demo", False)
    notes = notify.call_args.args[3]
    assert "launch failed" in notes[0]
    assert "--yes " in notes[1]
    assert "--yes-to-all" not in notes[1]
    assert "--artifacts-dir" in notes[1]
    assert "--cl-name demo" in notes[1]


def test_work_command_declined_launch_notifies_failure(tmp_path: Path) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=False,
    )
    with (
        patch("sase.bead.epic_launch._update_epic_launch_metadata") as update_metadata,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )

    update_metadata.assert_not_called()
    assert notify.call_args.args[:3] == ("epic-launch", "demo", False)
    notes = notify.call_args.args[3]
    assert "epic launch was declined" in notes[0]
    assert "--yes " in notes[1]
    assert "--yes-to-all" not in notes[1]


def test_work_command_linking_side_effects_are_best_effort(tmp_path: Path) -> None:
    result = SimpleNamespace(
        dry_run=False,
        epic_id="sase-64",
        archived_plan_path=tmp_path / "plans" / "epic.md",
        launched=True,
    )
    with (
        patch(
            "sase.bead.epic_launch._update_epic_launch_metadata",
            side_effect=OSError("read-only"),
        ),
        patch(
            "sase.notifications.senders.notify_workflow_complete",
            side_effect=OSError("store unavailable"),
        ),
    ):
        finish_epic_launch(
            str(tmp_path / "epic.md"),
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
            result=result,
        )
