"""Shared fixtures for clan summary persistence tests."""

from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.clan_membership import (
    CLAN_MEMBERSHIP_ENV,
    ClanMembershipPlan,
    encode_clan_membership_plan,
)
from sase.axe.run_agent_directives import (
    AgentInfo,
    extract_directives_and_write_meta,
)
from tests._agent_names_extract_fixtures import run_extract


def write_script(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def extract_clan_info_and_meta(
    tmp_path: Path,
    clan_args: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path | None = None,
    clan_name: str = "research",
    declared: bool = True,
) -> tuple[AgentInfo, dict[str, object]]:
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir.mkdir(exist_ok=True)
    artifacts_dir.mkdir(exist_ok=True)
    monkeypatch.setenv(
        CLAN_MEMBERSHIP_ENV,
        encode_clan_membership_plan(
            ClanMembershipPlan(clan_name=clan_name, generation="g1")
        ),
    )

    with (
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
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        prompt = (
            f"%id:{clan_name}.worker\n%clan({clan_name}, {clan_args})\nDo work"
            if declared
            else f"%id(worker, clan={clan_name})\nDo work"
        )
        info = extract_directives_and_write_meta(
            prompt,
            str(workspace_dir),
            str(artifacts_dir),
            output_path=str(output_path) if output_path is not None else None,
        )

    persisted = json.loads(
        (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert info.meta == persisted
    assert persisted["agent_clan"] == clan_name
    assert persisted["agent_clan_generation"] == "g1"
    return info, persisted


def extract_clan_meta(
    tmp_path: Path,
    clan_args: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_path: Path | None = None,
    clan_name: str = "research",
    declared: bool = True,
) -> dict[str, object]:
    return extract_clan_info_and_meta(
        tmp_path,
        clan_args,
        monkeypatch,
        output_path=output_path,
        clan_name=clan_name,
        declared=declared,
    )[1]


def extract_outside_clan(tmp_path: Path) -> AgentInfo:
    result = run_extract(
        tmp_path,
        env_auto_dismiss=True,
        prompt="Do ordinary work",
    )
    return result["info"]
