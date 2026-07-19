"""Tests for runner prompt-tag persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tags import load_agent_tags, save_agent_tags
from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.ace.tui.models.agent import AgentType
from sase.axe.run_agent_phases import AgentInfo, extract_directives_and_write_meta
from sase.bead.work import (
    SASE_EPIC_BEAD_ID_ENV,
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
            f"%name:!{expected_name}\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    persisted = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert info.meta == persisted
    assert persisted["epic_bead_id"] == "sase-7"
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
                "plan_committed": True,
                "epic_bead_id": "sase-7",
                "phase_bead_id": "sase-7.2",
                "agent_clan": "sase-7",
                "agent_clan_generation": "20260718090000",
                "clan_tribe": "epic",
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
            "%name:!sase-7.2\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    assert info.meta["sdd_plan_path"] == "sdd/plans/202607/epic.md"
    assert info.meta["plan_committed"] is True
    assert info.meta["epic_bead_id"] == "sase-7"
    assert info.meta["phase_bead_id"] == "sase-7.2"
    assert info.meta["agent_clan"] == "sase-7"
    assert info.meta["agent_clan_generation"] == "20260718090000"
    assert info.meta["clan_tribe"] == "epic"


def test_extract_directives_persists_tag_with_atomic_helper(
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
        patch("sase.ace.agent_tags.update_agent_tag") as update_agent_tag,
    ):
        info = extract_directives_and_write_meta(
            "%name:taggy\n%tribe:sase-26\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="sample-cl",
        )

    assert info.tag == "sase-26"
    assert json.loads((artifacts_dir / "agent_meta.json").read_text())["tag"] == (
        "sase-26"
    )
    update_agent_tag.assert_called_once_with(
        (AgentType.WORKFLOW, "sample-cl", "20260506120000"),
        "sase-26",
    )


def _extract_with_agent_tags(
    tmp_path: Path,
    prompt: str,
    *,
    seed_tags: dict[tuple[AgentType, str, str | None], str],
    cl_name: str | None = "sample-cl",
    planned_name: str | None = None,
    raw_resolved_prompt: str | None = None,
    artifacts_suffix: str = "20260506121000",
) -> tuple[AgentInfo, dict[str, object], dict[tuple[AgentType, str, str | None], str]]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts" / artifacts_suffix
    tag_file = tmp_path / "agent_tags.json"
    workspace_dir.mkdir()
    artifacts_dir.mkdir(parents=True)

    env_patch = {}
    if planned_name is not None:
        env_patch["SASE_AGENT_PLANNED_NAME"] = planned_name
    planned_entry = (
        {"artifacts_dir": str(artifacts_dir)} if planned_name is not None else None
    )

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        assert save_agent_tags(seed_tags)
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
        tags = load_agent_tags()
    return info, meta, tags


def test_explicit_tribe_wins_over_matching_existing_tribe(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    identity = (AgentType.WORKFLOW, "sample-cl", "20260506121000")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:foo.child\n%tribe:bar\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.tag == "bar"
    assert meta["tag"] == "bar"
    assert tags == {
        existing: "foo",
        identity: "bar",
    }


def test_clan_tribe_uses_metadata_without_agent_tag_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")
    plan = ClanMembershipPlan(clan_name="research", generation="g1")
    monkeypatch.setenv(CLAN_MEMBERSHIP_ENV, encode_clan_membership_plan(plan))

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:research.worker\n%clan(research, tribe=research)\nDo work",
        seed_tags={existing: "legacy"},
    )

    assert info.tag is None
    assert meta["agent_clan"] == "research"
    assert meta["agent_clan_generation"] == "g1"
    assert meta["clan_tribe"] == "research"
    assert "tag" not in meta
    assert tags == {existing: "legacy"}


def test_named_agent_does_not_inherit_existing_tribe(tmp_path: Path) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:foo.child\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.name == "foo.child"
    assert info.tag is None
    assert "tag" not in meta
    assert tags == {existing: "foo"}


def test_wait_derived_agent_name_does_not_inherit_existing_tribe(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%wait:foo\nDo work",
        seed_tags={existing: "foo"},
    )

    assert info.name == "foo.w0"
    assert info.tag is None
    assert "tag" not in meta
    assert tags == {existing: "foo"}


def test_fork_derived_agent_name_does_not_inherit_existing_tribe(
    tmp_path: Path,
) -> None:
    existing = (AgentType.RUNNING, "seed", "ts1")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "expanded prompt",
        seed_tags={existing: "foo"},
        raw_resolved_prompt="#fork:foo\nDo work",
    )

    assert info.name == "foo.f0"
    assert info.tag is None
    assert "tag" not in meta
    assert tags == {existing: "foo"}


def test_planned_template_name_does_not_inherit_nested_existing_tribe(
    tmp_path: Path,
) -> None:
    parent = (AgentType.RUNNING, "seed-parent", "ts1")
    child = (AgentType.RUNNING, "seed-child", "ts2")

    info, meta, tags = _extract_with_agent_tags(
        tmp_path,
        "%name:sase-42.3.@\nDo work",
        seed_tags={
            parent: "sase-42",
            child: "sase-42.3",
        },
        planned_name="sase-42.3.1",
    )

    assert info.name == "sase-42.3.1"
    assert info.tag is None
    assert "tag" not in meta
    assert tags == {
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


def _extract_phase_worker_model_meta(tmp_path: Path) -> dict[str, object]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir()
    artifacts_dir.mkdir()

    with (
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.agent.names.claim_agent_name"),
    ):
        extract_directives_and_write_meta(
            "%name:phase-worker\n%model:@phase_worker\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
        )

    return json.loads((artifacts_dir / "agent_meta.json").read_text())


def test_phase_worker_directive_metadata_resolves_default_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``%model:@phase_worker`` phase records the resolved default-lane model.

    The worker lane was retired in epic sase-5d phase 4; ``@phase_worker`` now
    falls through to ``@default``, so the recorded metadata is the configured
    default provider's large-tier model. As an explicit ``@`` alias reference it
    resolves to the configured default and is not swayed by a primary override.
    """
    _mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="test")

    meta = _extract_phase_worker_model_meta(tmp_path)

    assert (meta["llm_provider"], meta["model"]) == ("claude", "opus")
