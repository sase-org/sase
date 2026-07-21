"""Tests for runner prompt-tribe persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tribes import load_agent_tribes, save_agent_tribes
from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_phases import AgentInfo, extract_directives_and_write_meta
from sase.bead.work import (
    SASE_EPIC_BEAD_ID_ENV,
    SASE_EPIC_CLAN_TRIBE_ENV,
    SASE_EPIC_PLAN_REF_ENV,
    SASE_PHASE_BEAD_ID_ENV,
)
from sase.llm_provider.temporary_override import set_temporary_override


def test_extract_directives_persists_runner_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    output_path = tmp_path / "runner.log"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        info = extract_directives_and_write_meta(
            "Do work",
            str(workspace_dir),
            str(artifacts_dir),
            output_path=str(output_path),
        )

    assert info.meta["output_path"] == str(output_path)
    persisted = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert persisted["output_path"] == str(output_path)


@pytest.mark.parametrize(
    ("phase_bead_id", "expected_name"),
    [("sase-7.2", "sase-7.2"), (None, "sase-7")],
    ids=["phase", "land"],
)
def test_extract_directives_persists_epic_work_role_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase_bead_id: str | None,
    expected_name: str,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    plan_ref = "sase/repos/plans/202607/epic.md"
    monkeypatch.setenv(SASE_EPIC_PLAN_REF_ENV, plan_ref)
    monkeypatch.setenv(SASE_EPIC_BEAD_ID_ENV, "sase-7")
    if phase_bead_id is not None:
        monkeypatch.setenv(SASE_PHASE_BEAD_ID_ENV, phase_bead_id)
    monkeypatch.setenv("SASE_PLAN", "/tmp/commit-attribution-plan.md")

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        info = extract_directives_and_write_meta(
            f"%id:!{expected_name}\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    persisted = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.meta == persisted
    assert persisted["epic_bead_id"] == "sase-7"
    assert persisted["epic_plan_ref"] == plan_ref
    assert persisted["sdd_plan_path"] == plan_ref
    assert persisted["plan_committed"] is True
    if phase_bead_id is None:
        assert "phase_bead_id" not in persisted
    else:
        assert persisted["phase_bead_id"] == phase_bead_id
    assert SASE_EPIC_PLAN_REF_ENV not in os.environ
    assert SASE_EPIC_BEAD_ID_ENV not in os.environ
    assert SASE_PHASE_BEAD_ID_ENV not in os.environ
    assert os.environ["SASE_PLAN"] == "/tmp/commit-attribution-plan.md"


def test_extract_directives_preserves_epic_work_metadata_on_reexec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "sdd_plan_path": "sdd/plans/202607/epic.md",
                "epic_plan_ref": "sdd/plans/202607/epic.md",
                "plan_committed": True,
                "epic_bead_id": "sase-7",
                "phase_bead_id": "sase-7.2",
                "agent_clan": "sase-7",
                "agent_clan_generation": "20260718090000",
                "clan_tribe": "epic",
                "clan_summary": "[bold]EPIC sase-7[/bold]",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        info = extract_directives_and_write_meta(
            "%id:!sase-7.2\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    assert info.meta["sdd_plan_path"] == "sdd/plans/202607/epic.md"
    assert info.meta["epic_plan_ref"] == "sdd/plans/202607/epic.md"
    assert info.meta["plan_committed"] is True
    assert info.meta["epic_bead_id"] == "sase-7"
    assert info.meta["phase_bead_id"] == "sase-7.2"
    assert info.meta["agent_clan"] == "sase-7"
    assert info.meta["agent_clan_generation"] == "20260718090000"
    assert info.meta["clan_tribe"] == "epic"
    assert info.meta["clan_summary"] == "[bold]EPIC sase-7[/bold]"


def test_join_only_epic_member_persists_launch_clan_tribe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    plan_ref = "sase/repos/plans/202607/epic.md"
    membership = ClanMembershipPlan(clan_name="sase-7", generation="g1")
    monkeypatch.setenv(
        CLAN_MEMBERSHIP_ENV,
        encode_clan_membership_plan(membership),
    )
    monkeypatch.setenv(SASE_EPIC_PLAN_REF_ENV, plan_ref)
    monkeypatch.setenv(SASE_EPIC_BEAD_ID_ENV, "sase-7")
    monkeypatch.setenv(SASE_PHASE_BEAD_ID_ENV, "sase-7.2")
    monkeypatch.setenv(SASE_EPIC_CLAN_TRIBE_ENV, "epic")

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        info = extract_directives_and_write_meta(
            "%id(!2, clan=sase-7)\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    assert info.meta["agent_clan"] == "sase-7"
    assert info.meta["agent_clan_generation"] == "g1"
    assert info.meta["clan_tribe"] == "epic"
    assert info.meta["sdd_plan_path"] == plan_ref
    assert info.meta["epic_plan_ref"] == plan_ref
    assert info.meta["epic_bead_id"] == "sase-7"
    assert info.meta["phase_bead_id"] == "sase-7.2"
    for env_name in (
        SASE_EPIC_PLAN_REF_ENV,
        SASE_EPIC_BEAD_ID_ENV,
        SASE_PHASE_BEAD_ID_ENV,
        SASE_EPIC_CLAN_TRIBE_ENV,
    ):
        assert env_name not in os.environ


def test_extract_directives_persists_tribe_with_atomic_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / "20260506120000"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.ace.agent_tribes.update_agent_tribe") as update_agent_tribe,
    ):
        info = extract_directives_and_write_meta(
            "%id(taggy, tribe=sase-26)\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="sample-cl",
        )

    assert info.tribe == "sase-26"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text())["tribe"] == (
        "sase-26"
    )
    update_agent_tribe.assert_called_once_with(
        (AgentType.WORKFLOW, "sample-cl", "20260506120000"),
        "sase-26",
    )


def _extract_with_agent_tribes(
    tmp_path: Path,
    prompt: str,
    *,
    seed_tribes: dict[tuple[AgentType, str, str | None], str],
    cl_name: str | None = "sample-cl",
    planned_name: str | None = None,
    raw_resolved_prompt: str | None = None,
    artifacts_suffix: str = "20260506121000",
) -> tuple[AgentInfo, dict[str, object], dict[tuple[AgentType, str, str | None], str]]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / artifacts_suffix
    tribe_file = tmp_path / "agent_tribes.json"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)

    env_patch = {}
    if planned_name is not None:
        env_patch["SASE_AGENT_PLANNED_NAME"] = planned_name
    planned_entry = (
        {"artifacts_dir": str(artifacts_dir)} if planned_name is not None else None
    )

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        assert save_agent_tribes(seed_tribes)
        with (
            patch.dict("os.environ", env_patch, clear=False),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
            patch("sase.agent.names.claim_agent_name"),
            patch(
                "sase.agent.names.lookup_registered_name",
                return_value=planned_entry,
            ),
        ):
            info = extract_directives_and_write_meta(
                prompt,
                str(workspace_dir),
                str(artifacts_dir),
                cl_name=cl_name,
                raw_resolved_prompt=raw_resolved_prompt,
            )

        meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
        tribes = load_agent_tribes()
    return info, meta, tribes


def test_explicit_tribe_wins_over_matching_existing_tribe(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "%id(foo.child, tribe=bar)\nDo work",
        seed_tribes={existing: "foo"},
    )

    assert info.tribe == "bar"
    assert meta["tribe"] == "bar"
    assert tribes == {
        existing: "foo",
        identity: "bar",
    }


def test_clan_tribe_uses_metadata_without_standalone_tribe_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    plan = ClanMembershipPlan(clan_name="research", generation="g1")
    monkeypatch.setenv(CLAN_MEMBERSHIP_ENV, encode_clan_membership_plan(plan))

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "%id:research.worker\n%clan(research, tribe=research)\nDo work",
        seed_tribes={existing: "legacy"},
    )

    assert info.tribe is None
    assert meta["agent_clan"] == "research"
    assert meta["agent_clan_generation"] == "g1"
    assert meta["clan_tribe"] == "research"
    assert "tribe" not in meta
    assert tribes == {existing: "legacy"}


def test_named_agent_does_not_inherit_existing_tribe(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "%id:foo.child\nDo work",
        seed_tribes={existing: "foo"},
    )

    assert info.name == "foo.child"
    assert info.tribe is None
    assert "tribe" not in meta
    assert tribes == {existing: "foo"}


def test_wait_derived_agent_name_does_not_inherit_existing_tribe(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "%wait:foo\nDo work",
        seed_tribes={existing: "foo"},
    )

    assert info.name == "foo.w0"
    assert info.tribe is None
    assert "tribe" not in meta
    assert tribes == {existing: "foo"}


def test_fork_derived_agent_name_does_not_inherit_existing_tribe(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "expanded prompt",
        seed_tribes={existing: "foo"},
        raw_resolved_prompt="#fork:foo\nDo work",
    )

    assert info.name == "foo.f0"
    assert info.tribe is None
    assert "tribe" not in meta
    assert tribes == {existing: "foo"}


def test_planned_template_name_does_not_inherit_nested_existing_tribe(
    tmp_path: Path,
) -> None:
    parent = (AgentType.RUNNING, "seed-parent", "ts1")
    child = (AgentType.RUNNING, "seed-child", "ts2")

    info, meta, tribes = _extract_with_agent_tribes(
        tmp_path,
        "%id:sase-42.3.@\nDo work",
        seed_tribes={
            parent: "sase-42",
            child: "sase-42.3",
        },
        planned_name="sase-42.3.1",
    )

    assert info.name == "sase-42.3.1"
    assert info.tribe is None
    assert "tribe" not in meta
    assert tribes == {
        parent: "sase-42",
        child: "sase-42.3",
    }


def _mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )


def _extract_medium_phase_worker_model_meta(tmp_path: Path) -> dict[str, object]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()

    with (
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        extract_directives_and_write_meta(
            "%id:phase-worker\n%model:@medium_phase_worker\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    return json.loads((artifacts_dir / "agent_meta.json").read_text())


def test_medium_phase_worker_directive_metadata_resolves_default_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A medium phase records the configured default-lane model.

    As an explicit alias reference it resolves to the configured default and is
    not swayed by a primary override.
    """
    _mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="test")

    meta = _extract_medium_phase_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("claude", "opus")
