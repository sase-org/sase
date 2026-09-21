"""Regression tests for preserving launch handoffs across runner refresh.

A clan-declaring agent whose dependency wait crosses a sase code update must
keep its clan membership after the runner re-exec instead of failing with
"clan already exists" or silently losing prompt expansions.
"""

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
    preserved_clan_membership_plan,
)
from sase.axe.run_agent_directives import extract_directives_and_write_meta


def _extract(
    prompt: str,
    artifacts_dir: Path,
    *,
    env: dict[str, str] | None = None,
) -> object:
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
        # Isolate from the outer agent's launch env when tests run nested.
        os.environ.pop("SASE_AGENT_FAMILY_ATTACH", None)
        return extract_directives_and_write_meta(
            prompt,
            workspace_dir="/workspace",
            artifacts_dir=str(artifacts_dir),
            cl_name="feature",
            raw_resolved_prompt=prompt,
        )


def _artifact_dir(sase_home: Path, timestamp: str) -> Path:
    return sase_home / "projects" / "sase" / "artifacts" / "ace-run" / timestamp


def test_declared_clan_reuses_preserved_metadata_after_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact regression: a declaring member replays without env payload."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)
    generation = "20260921010101"
    founder_dir = _artifact_dir(sase_home, generation)
    founder_dir.mkdir(parents=True)

    from sase.agent.names import (
        claim_registered_clan_name,
        lookup_registered_name,
        reserve_registered_clan_name,
    )

    reserve_registered_clan_name("rc", generation, founder_dir)
    claim_registered_clan_name("rc", generation, founder_dir)

    # Keep the replaying member outside the scanned artifacts tree so its
    # pre-written preserved metadata is not itself scanned as a clan source.
    member_dir = tmp_path / "member_artifacts"
    member_dir.mkdir(parents=True)
    (member_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 123,
                AGENT_CLAN_FIELD: "rc",
                AGENT_CLAN_GENERATION_FIELD: generation,
            }
        ),
        encoding="utf-8",
    )

    info = _extract(
        "%clan(rc, tribe=research)\n%id:rc.final\nDo work",
        member_dir,
    )

    assert info.meta[AGENT_CLAN_FIELD] == "rc"
    assert info.meta[AGENT_CLAN_GENERATION_FIELD] == generation
    entry = lookup_registered_name("rc")
    assert isinstance(entry, dict)
    assert entry.get("clan_generation") == generation
    founder_resolved = founder_dir.expanduser().resolve(strict=False)
    assert (
        Path(str(entry.get("artifacts_dir"))).expanduser().resolve(strict=False)
        == founder_resolved
    )


def test_two_pass_replay_keeps_declared_member_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First pass with env payload, second pass with preserved metadata only."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)
    generation = "20260921030303"
    founder_dir = _artifact_dir(sase_home, generation)
    founder_dir.mkdir(parents=True)

    from sase.agent.names import reserve_registered_clan_name

    reserve_registered_clan_name("rc", generation, founder_dir)

    member_dir = _artifact_dir(sase_home, "20260921040404")
    member_dir.mkdir(parents=True)
    prompt = "%id:rc.final\n%clan(rc, tribe=research)\n%wait:other\nDo work"
    plan = ClanMembershipPlan(clan_name="rc", generation=generation)
    first = _extract(
        prompt,
        member_dir,
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )

    assert CLAN_MEMBERSHIP_ENV not in os.environ
    monkeypatch.setenv("SASE_RUNNER_CODE_REFRESHED", "1")
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", first.name)
    second = _extract(prompt, member_dir)

    assert second.name == first.name
    assert second.meta[AGENT_CLAN_FIELD] == first.meta[AGENT_CLAN_FIELD]
    assert (
        second.meta[AGENT_CLAN_GENERATION_FIELD]
        == first.meta[AGENT_CLAN_GENERATION_FIELD]
    )
    assert second.meta.get("clan_tribe") == first.meta.get("clan_tribe")
    assert second.meta.get("wait_for") == first.meta.get("wait_for")


def test_two_pass_replay_keeps_founder_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The founding member's replay is an idempotent rewrite."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)
    generation = "20260921050505"
    founder_dir = _artifact_dir(sase_home, generation)
    founder_dir.mkdir(parents=True)

    prompt = "%id:rc.final\n%clan(rc, tribe=research)\n%wait:other\nDo work"
    plan = ClanMembershipPlan(clan_name="rc", generation=generation)
    first = _extract(
        prompt,
        founder_dir,
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )

    monkeypatch.setenv("SASE_RUNNER_CODE_REFRESHED", "1")
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", first.name)
    second = _extract(prompt, founder_dir)

    assert second.name == first.name
    assert second.meta[AGENT_CLAN_FIELD] == "rc"
    assert second.meta[AGENT_CLAN_GENERATION_FIELD] == generation


def test_fresh_declaration_of_existing_clan_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The create-only guard stays intact for genuinely new launches."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)
    founder_dir = _artifact_dir(sase_home, "20260921060606")
    founder_dir.mkdir(parents=True)

    from sase.agent.names import reserve_registered_clan_name

    reserve_registered_clan_name("existing", "20260921060606", founder_dir)

    member_dir = _artifact_dir(sase_home, "20260921070707")
    with pytest.raises(ClanMembershipError, match=r"join it with %id\("):
        _extract("%id:existing.two\n%clan:existing\nWork", member_dir)


def test_env_payload_wins_over_preserved_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env payload keeps precedence over preserved metadata."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)

    from sase.agent.names import reserve_registered_clan_name

    env_dir = _artifact_dir(sase_home, "20260921080808")
    env_dir.mkdir(parents=True)
    reserve_registered_clan_name("envclan", "20260921080808", env_dir)
    preserved_dir = _artifact_dir(sase_home, "20260921090909")
    preserved_dir.mkdir(parents=True)
    reserve_registered_clan_name("oldclan", "20260921090909", preserved_dir)

    member_dir = _artifact_dir(sase_home, "20260921101010")
    member_dir.mkdir(parents=True)
    (member_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 123,
                AGENT_CLAN_FIELD: "oldclan",
                AGENT_CLAN_GENERATION_FIELD: "20260921090909",
            }
        ),
        encoding="utf-8",
    )

    plan = ClanMembershipPlan(clan_name="envclan", generation="20260921080808")
    info = _extract(
        "%id:envclan.final\n%clan:envclan\nDo work",
        member_dir,
        env={CLAN_MEMBERSHIP_ENV: encode_clan_membership_plan(plan)},
    )

    assert info.meta[AGENT_CLAN_FIELD] == "envclan"
    assert info.meta[AGENT_CLAN_GENERATION_FIELD] == "20260921080808"


def test_preserved_clan_without_directive_does_not_fabricate_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Family-attach continuations must not get a plan without %clan."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv(CLAN_MEMBERSHIP_ENV, raising=False)

    member_dir = _artifact_dir(sase_home, "20260921111111")
    member_dir.mkdir(parents=True)
    (member_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 123,
                AGENT_CLAN_FIELD: "rc",
                AGENT_CLAN_GENERATION_FIELD: "20260921010101",
            }
        ),
        encoding="utf-8",
    )

    info = _extract("%id:rc.final\nDo work", member_dir)

    assert info.meta[AGENT_CLAN_FIELD] == "rc"
    assert info.meta[AGENT_CLAN_GENERATION_FIELD] == "20260921010101"


@pytest.mark.parametrize(
    "preserved",
    [
        {},
        {AGENT_CLAN_FIELD: "rc"},
        {AGENT_CLAN_GENERATION_FIELD: "G"},
        {AGENT_CLAN_FIELD: "", AGENT_CLAN_GENERATION_FIELD: "G"},
        {AGENT_CLAN_FIELD: "rc", AGENT_CLAN_GENERATION_FIELD: ""},
        {AGENT_CLAN_FIELD: 123, AGENT_CLAN_GENERATION_FIELD: "G"},
        {AGENT_CLAN_FIELD: "rc", AGENT_CLAN_GENERATION_FIELD: None},
    ],
)
def test_preserved_clan_helper_rejects_missing_or_invalid_fields(
    preserved: dict,
) -> None:
    assert preserved_clan_membership_plan(preserved) is None


def test_preserved_clan_helper_returns_plan_for_valid_fields() -> None:
    plan = preserved_clan_membership_plan(
        {AGENT_CLAN_FIELD: "rc", AGENT_CLAN_GENERATION_FIELD: "G"}
    )
    assert plan == ClanMembershipPlan(clan_name="rc", generation="G")
