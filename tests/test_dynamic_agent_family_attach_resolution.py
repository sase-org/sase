from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from sase.agent._family_attach_candidates import family_sase_plan
from sase.agent.family_attach import (
    FamilyAttachDirective,
    FamilyAttachError,
    prepare_family_attach_launch,
    resolve_family_attach_plan,
)
from sase.agent.launch_executor import LaunchExecutionContext
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests._dynamic_agent_family_attach_helpers import (
    _artifact_record,
    _in_batch_sibling,
    _patch_attach_snapshot,
)


def test_family_attach_absent_parent_error_uses_rust_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(monkeypatch, [])

    with pytest.raises(FamilyAttachError) as exc_info:
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="missing", suffix="reviewer"),
            project_name="sase",
        )

    assert "parent agent 'missing' was not found in project 'sase'" in str(
        exc_info.value
    )


def test_family_attach_dismissed_parent_error_names_revive_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _artifact_record(name="foo", timestamp="20260701010101")
    _patch_attach_snapshot(
        monkeypatch,
        [parent],
        dismissed=[
            {
                "agent_type": "workflow",
                "cl_name": "feature",
                "raw_suffix": "20260701010101",
            }
        ],
    )

    with pytest.raises(FamilyAttachError) as exc_info:
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo", suffix="reviewer"),
            project_name="sase",
        )

    message = str(exc_info.value)
    assert "dismissed parent 'foo'" in message
    assert "Revive the parent from the Agents tab" in message


def test_family_attach_ambiguous_parent_error_lists_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = "20260701010101"
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="foo--plan",
                workflow_name="foo",
                timestamp=timestamp,
                artifact_dir="/tmp/foo-plan",
            ),
            _artifact_record(
                name="foo--code",
                workflow_name="foo",
                timestamp=timestamp,
                artifact_dir="/tmp/foo-code",
            ),
        ],
    )

    with pytest.raises(FamilyAttachError) as exc_info:
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo", suffix="reviewer"),
            project_name="sase",
        )

    message = str(exc_info.value)
    assert "multiple newest parent candidates matched" in message
    assert f"foo--plan@{timestamp}" in message
    assert f"foo--code@{timestamp}" in message


def test_family_attach_resolution_uses_newest_match_with_project_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(name="foo", timestamp="20260701010101"),
            _artifact_record(name="foo", timestamp="20260701010202"),
            _artifact_record(
                name="foo",
                timestamp="20260701030303",
                project_name="other",
                artifact_dir="/tmp/other/foo",
            ),
        ],
    )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_project_name == "sase"
    assert plan.parent_timestamp == "20260701010202"
    assert plan.parent_artifacts_dir != "/tmp/other/foo"


def test_family_attach_inherits_parent_model_alias_overrides(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"model_alias_overrides": {"coder": "sonnet"}}),
        encoding="utf-8",
    )
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", artifact_dir=parent_dir)],
    )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )
    _, env = prepare_family_attach_launch(
        "%i(reviewer, family=foo)\nReview",
        LaunchExecutionContext(
            cl_name="feature",
            project_file="/tmp/sase.sase",
            project_name="sase",
        ),
        {},
    )

    assert plan.model_alias_overrides == {"coder": "sonnet"}
    assert json.loads((env or {})["SASE_MODEL_ALIAS_OVERRIDES"]) == {"coder": "sonnet"}


def test_family_attach_running_parent_builds_queued_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _artifact_record(
        name="foo",
        timestamp="20260701010101",
        has_done_marker=False,
    )
    _patch_attach_snapshot(monkeypatch, [record])

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_is_running is True
    assert plan.parent_project_name == "sase"
    assert plan.parent_timestamp == "20260701010101"
    assert plan.agent_name == "foo--reviewer"
    assert plan.parent_needs_rename is True
    assert plan.parent_family_member_name == "foo--0"
    assert plan.parent_family_role_suffix == "--0"
    assert plan.parent_workspace_num == 7


def test_family_attach_reserves_original_parent_zero_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(monkeypatch, [_artifact_record(name="foo")])

    with pytest.raises(FamilyAttachError, match="reserved for the original parent"):
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo", suffix="0"),
            project_name="sase",
        )


def test_family_attach_reserves_original_plan_parent_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", role_suffix="--plan")],
    )

    with pytest.raises(FamilyAttachError, match="reserved for the original parent"):
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo", suffix="plan"),
            project_name="sase",
        )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="code"),
        project_name="sase",
    )
    assert plan.parent_family_member_name == "foo--plan"
    assert plan.parent_family_role_suffix == "--plan"


def test_family_attach_inherits_parent_clan_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="research.worker",
                agent_clan="research",
                agent_clan_generation="20260701010000",
            )
        ],
    )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="research.worker", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_agent_clan == "research"
    assert plan.parent_agent_clan_generation == "20260701010000"
    assert plan.parent_family_member_name == "research.worker--0"
    assert plan.agent_name == "research.worker--reviewer"


def test_family_attach_resolves_in_batch_parent_without_artifact_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(monkeypatch, [])
    sibling = _in_batch_sibling()

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
        pending_family_parents=[sibling],
    )

    assert plan.parent_is_running is True
    assert plan.parent_name == "foo"
    assert plan.parent_base == "foo"
    assert plan.parent_timestamp == sibling.timestamp
    assert plan.parent_artifacts_dir == sibling.artifact_dir
    assert plan.parent_cl_name == "feature"
    assert plan.parent_workspace_dir == "/tmp/sase_8"
    assert plan.parent_workspace_num == 8
    assert plan.agent_name == "foo--reviewer"


def test_family_attach_launch_repairs_a_numbered_directory_missing_its_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent's own meta can still record a numbered ``workspace_dir``
    with no ``workspace_num`` (the monitor-claim defect this epic tracks
    separately); the launch must repair the pair via the registry lookup
    rather than leaving the child paired with workspace ``0``."""
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", workspace_dir="/tmp/sase_9", workspace_num=None)],
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/sase_primary", None),
        ),
        patch(
            "sase.workspace_provider.resolve_consistent_workspace_pair",
            return_value=("/tmp/sase_9", 9),
        ),
    ):
        context, _ = prepare_family_attach_launch(
            "%i(reviewer, family=foo)\nReview",
            LaunchExecutionContext(
                cl_name="launcher",
                project_file="/tmp/sase.sase",
                project_name="sase",
            ),
            {},
        )

    assert context.workspace_dir == "/tmp/sase_9"
    assert context.workspace_num == 9


def test_family_attach_launch_repairs_a_deferred_running_parent_pairing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="foo",
                workspace_dir="/tmp/sase_9",
                workspace_num=None,
                has_done_marker=False,
            )
        ],
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/sase_primary", None),
        ),
        patch(
            "sase.workspace_provider.resolve_consistent_workspace_pair",
            return_value=("/tmp/sase_9", 9),
        ),
    ):
        context, env = prepare_family_attach_launch(
            "%i(reviewer, family=foo)\nReview",
            LaunchExecutionContext(
                cl_name="launcher",
                project_file="/tmp/sase.sase",
                project_name="sase",
            ),
            {},
        )

    assert context.deferred_workspace is True
    assert context.use_preallocated_workspace is False
    assert context.workspace_dir == "/tmp/sase_9"
    assert context.workspace_num == 9
    assert env is not None
    assert env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_DIR"] == "/tmp/sase_9"
    assert env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM"] == "9"


def test_family_attach_launch_fails_loudly_when_pairing_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", workspace_dir="/tmp/sase_9", workspace_num=None)],
    )

    with (
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/sase_primary", None),
        ),
        patch(
            "sase.workspace_provider.resolve_consistent_workspace_pair",
            return_value=None,
        ),
        pytest.raises(FamilyAttachError, match="Refusing to launch"),
    ):
        prepare_family_attach_launch(
            "%i(reviewer, family=foo)\nReview",
            LaunchExecutionContext(
                cl_name="launcher",
                project_file="/tmp/sase.sase",
                project_name="sase",
            ),
            {},
        )


def test_family_attach_prefers_in_batch_parent_over_older_persisted_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="foo",
                timestamp="20260701010101",
                artifact_dir="/tmp/sase/artifacts/ace-run/20260701010101",
                workspace_dir="/tmp/sase_7",
                workspace_num=7,
            )
        ],
    )
    sibling = _in_batch_sibling(
        timestamp="20260701010202",
        artifact_dir="/tmp/sase/artifacts/ace-run/20260701010202",
        workspace_dir="/tmp/sase_8",
        workspace_num=8,
    )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
        pending_family_parents=[sibling],
    )

    assert plan.parent_artifacts_dir == sibling.artifact_dir
    assert plan.parent_workspace_num == 8


def test_family_attach_auto_suffix_and_collision_include_in_batch_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_attach_snapshot(monkeypatch, [])
    pending = [_in_batch_sibling()]

    first = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="@"),
        project_name="sase",
        pending_family_parents=pending,
    )
    pending.append(
        _in_batch_sibling(
            name=first.agent_name,
            timestamp="20260701010303",
            artifact_dir="/tmp/sase/artifacts/ace-run/20260701010303",
            can_attach_parent=True,
        )
    )
    second = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="@"),
        project_name="sase",
        pending_family_parents=pending,
    )

    assert first.role_suffix == "--1"
    assert second.role_suffix == "--2"
    assert second.parent_name == "foo--1"
    assert second.parent_timestamp == "20260701010303"
    with pytest.raises(FamilyAttachError, match=r"%i\(@, family=foo\)"):
        resolve_family_attach_plan(
            FamilyAttachDirective(parent="foo", suffix="1"),
            project_name="sase",
            pending_family_parents=pending,
        )


@pytest.mark.parametrize(
    ("suffix", "expected_role"),
    [
        ("plan", "plan"),
        ("q", "q"),
        ("code", "code"),
        ("epic", "epic"),
        ("commit", "commit"),
        ("reviewer", "reviewer"),
        ("security_review", "security_review"),
    ],
)
def test_family_attach_role_mapping_through_attach_path(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    expected_role: str,
) -> None:
    _patch_attach_snapshot(monkeypatch, [_artifact_record(name="foo")])

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix=suffix),
        project_name="sase",
    )

    assert plan.role_suffix == f"--{suffix}"
    assert plan.agent_family_role == expected_role


@pytest.mark.parametrize(
    ("suffix", "parent_plan_path", "expected_sase_plan"),
    [
        ("code", "sdd/plans/202607/foo.md", "sdd/plans/202607/foo.md"),
        ("q", "sdd/plans/202607/foo.md", None),
        ("code", None, None),
    ],
)
def test_family_attach_sase_plan_env_only_for_code_with_parent_plan(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    parent_plan_path: str | None,
    expected_sase_plan: str | None,
) -> None:
    _patch_attach_snapshot(
        monkeypatch,
        [_artifact_record(name="foo", sdd_plan_path=parent_plan_path)],
    )
    _, env = prepare_family_attach_launch(
        f"%i({suffix}, family=foo)\nDo work",
        LaunchExecutionContext(
            cl_name="launcher",
            project_file="/tmp/sase.sase",
            project_name="sase",
            is_home_mode=True,
        ),
        {},
    )

    assert env is not None
    if expected_sase_plan is None:
        assert "SASE_PLAN" not in env
    else:
        assert env["SASE_PLAN"] == expected_sase_plan


def _configured_owner_identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena",),
    )


def test_family_attach_coder_resolves_when_snapshot_has_empty_agent_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.AgentIdentitySnapshot.current",
        _configured_owner_identity,
    )
    parent_plan = "sdd/plans/202609/foo.md"
    _patch_attach_snapshot(
        monkeypatch,
        [
            _artifact_record(
                name="other",
                agent_family=None,
                timestamp="20260701010000",
                artifact_dir="/tmp/sase/artifacts/ace-run/20260701010000",
            ),
            _artifact_record(
                name="",
                agent_family=None,
                timestamp="20260701010001",
                artifact_dir="/tmp/sase/artifacts/ace-run/20260701010001",
            ),
            _artifact_record(
                name="foo",
                timestamp="20260701010101",
                sdd_plan_path=parent_plan,
            ),
        ],
    )

    plan = resolve_family_attach_plan(
        FamilyAttachDirective(parent="foo", suffix="code"),
        project_name="sase",
    )

    assert plan.agent_family_role == "code"
    assert plan.agent_name == "foo--code"
    assert plan.sase_plan == parent_plan


def test_family_sase_plan_skips_empty_identity_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.AgentIdentitySnapshot.current",
        _configured_owner_identity,
    )
    matching_plan = "sdd/plans/202609/foo.md"
    records = [
        _artifact_record(
            name="",
            agent_family=None,
            timestamp="20260701020202",
            sdd_plan_path="sdd/plans/202609/unrelated.md",
        ),
        _artifact_record(
            name="foo",
            workflow_name="foo",
            agent_family="foo",
            timestamp="20260701010101",
            sdd_plan_path=matching_plan,
        ),
    ]

    assert family_sase_plan(records, "foo") == matching_plan
