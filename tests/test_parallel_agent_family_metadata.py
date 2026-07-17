from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.clan_membership import (
    AGENT_CLAN_FIELD,
    AGENT_CLAN_GENERATION_FIELD,
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipError,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.axe.run_agent_directives import AgentInfo, extract_directives_and_write_meta


def _write_artifact(
    sase_home: Path,
    *,
    timestamp: str,
    meta: dict[str, object],
    outcome: str | None = None,
) -> Path:
    artifact_dir = sase_home / "projects" / "sase" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if outcome is not None:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": outcome}))
    return artifact_dir


def _extract_runner_metadata(
    prompt: str,
    *,
    artifacts_dir: Path,
    env: dict[str, str] | None = None,
) -> AgentInfo:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with (
        patch.dict(os.environ, env or {}, clear=False),
        patch("sase.agent.names.ensure_historical_auto_name_migration"),
        patch(
            "sase.agent.names.agent_name_allocation_lock",
            return_value=nullcontext(),
        ),
        patch("sase.agent.names.claim_agent_name"),
        patch("sase.agent.names.claim_registered_clan_name"),
        patch(
            "sase.xprompt.process_xprompt_references",
            side_effect=lambda value, **_: value,
        ),
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch(
            "sase.llm_provider.config.resolve_effective_effort",
            return_value=(None, None),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        return extract_directives_and_write_meta(
            prompt,
            workspace_dir="/workspace",
            artifacts_dir=str(artifacts_dir),
            cl_name="feature",
            raw_resolved_prompt=prompt,
        )


def test_runner_writes_rootless_clan_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    plan = ClanMembershipPlan(clan_name="root", generation="20260716010101")

    one = _extract_runner_metadata(
        "%name:root.one\n%clan:root\nWork",
        artifacts_dir=sase_home / "projects/sase/artifacts/ace-run/20260716010101",
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )
    two = _extract_runner_metadata(
        "%name:root.two\n%clan:root\nReview",
        artifacts_dir=sase_home / "projects/sase/artifacts/ace-run/20260716010202",
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )

    for info in (one, two):
        assert info.meta[AGENT_CLAN_FIELD] == "root"
        assert info.meta[AGENT_CLAN_GENERATION_FIELD] == "20260716010101"
        assert "agent_family" not in info.meta
        assert "agent_family_role" not in info.meta
        assert "agent_family_parallel" not in info.meta
        assert "parent_timestamp" not in info.meta
    assert one.wait_identity_deps == []
    assert two.wait_identity_deps == []


def test_runner_fallback_joins_existing_clan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    _write_artifact(
        sase_home,
        timestamp="20260716020101",
        meta={
            "name": "existing.one",
            AGENT_CLAN_FIELD: "existing",
            AGENT_CLAN_GENERATION_FIELD: "20260716020000",
        },
        outcome="completed",
    )

    info = _extract_runner_metadata(
        "%name:existing.late\n%clan:existing\nWork",
        artifacts_dir=(sase_home / "projects/sase/artifacts/ace-run/20260716020202"),
    )

    assert info.meta[AGENT_CLAN_FIELD] == "existing"
    assert info.meta[AGENT_CLAN_GENERATION_FIELD] == "20260716020000"


def test_clan_wait_and_fork_resolve_only_after_every_member_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    generation = "20260716030000"
    first = _write_artifact(
        sase_home,
        timestamp="20260716030101",
        meta={
            "name": "family.one",
            AGENT_CLAN_FIELD: "family",
            AGENT_CLAN_GENERATION_FIELD: generation,
        },
        outcome="completed",
    )
    second = _write_artifact(
        sase_home,
        timestamp="20260716030202",
        meta={
            "name": "family.two",
            AGENT_CLAN_FIELD: "family",
            AGENT_CLAN_GENERATION_FIELD: generation,
        },
    )

    from sase.agent.names import resolve_resume_agent_name, resolve_wait_dependency

    assert resolve_wait_dependency("family") is False
    assert resolve_resume_agent_name("family") is None
    (second / "done.json").write_text(json.dumps({"outcome": "completed"}))
    assert resolve_wait_dependency("family") is True
    resolved = resolve_resume_agent_name("family")
    assert resolved is not None
    assert Path(resolved.artifacts_dir) == second
    assert Path(resolved.artifacts_dir) != first


@pytest.mark.parametrize("agent_name", ["outsider", "root."])
def test_runner_rejects_member_outside_clan_hood(
    tmp_path: Path,
    agent_name: str,
) -> None:
    plan = ClanMembershipPlan(clan_name="root", generation="20260716040000")
    with pytest.raises(ClanMembershipError, match="clan members must use"):
        _extract_runner_metadata(
            f"%name:{agent_name}\n%clan:root\nWork",
            artifacts_dir=tmp_path / "run",
            env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
        )


def test_clan_membership_survives_runner_reexec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    artifacts_dir = sase_home / "projects/sase/artifacts/ace-run/20260716040101"
    plan = ClanMembershipPlan(clan_name="reexec", generation="20260716040000")
    _extract_runner_metadata(
        "%name:reexec.member\n%clan:reexec\nWork",
        artifacts_dir=artifacts_dir,
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )

    second = _extract_runner_metadata(
        "%name:reexec.member\nWork",
        artifacts_dir=artifacts_dir,
    )
    assert second.meta[AGENT_CLAN_FIELD] == "reexec"
    assert second.meta[AGENT_CLAN_GENERATION_FIELD] == "20260716040000"
