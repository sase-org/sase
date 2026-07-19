"""Tests for typed ``#fork`` history assembly."""

from __future__ import annotations

import json
from pathlib import Path

from sase.history.chat import build_fork_injected_history


def _write_member_artifacts(
    root: Path,
    timestamp: str,
    *,
    model: str,
    provider: str,
) -> Path:
    artifact_dir = root / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"model": model, "llm_provider": provider}),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    return artifact_dir


def test_clan_block_contains_prompts_and_stats_but_no_reply_text(
    tmp_path: Path,
) -> None:
    ancestor_chat = tmp_path / "ancestor.md"
    ancestor_chat.write_text(
        "## Prompt\n\nAncestor request\n\n## Response\n\nANCESTOR_SECRET_REPLY\n",
        encoding="utf-8",
    )
    early_chat = tmp_path / "early.md"
    early_chat.write_text(
        "## Prompt\n\n"
        f"%id:review.alpha #fork_by_chat:`{ancestor_chat}`\nImplement the change\n\n"
        "## Response\n\nEARLY_SECRET_REPLY has four words\n",
        encoding="utf-8",
    )
    late_chat = tmp_path / "late.md"
    late_chat.write_text(
        "## Prompt\n\n%wait:review.alpha Review the change\n\n"
        "## Response\n\nLATE_SECRET_REPLY\nsecond line\n",
        encoding="utf-8",
    )
    early_dir = _write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )
    late_dir = _write_member_artifacts(
        tmp_path / "artifacts", "20260718010202", model="opus", provider="claude"
    )
    source = {
        "kind": "clan",
        "name": "review",
        "generation": "20260718010000",
        "tribe": "epic",
        # Intentionally reverse the wire order; rendering is launch-ordered.
        "members": [
            {
                "name": "review.beta",
                "path": str(late_chat),
                "artifact_dir": str(late_dir),
            },
            {
                "name": "review.alpha",
                "path": str(early_chat),
                "artifact_dir": str(early_dir),
            },
        ],
    }

    rendered = build_fork_injected_history([source])

    assert "agent clan `review`" in rendered
    assert "**Generation:** `20260718010000`" in rendered
    assert "**Tribe:** `@epic`" in rendered
    assert "**Members:** 2" in rendered
    assert "Full clan-member replies were intentionally omitted" in rendered
    assert rendered.index("review.alpha") < rendered.index("review.beta")
    assert "Ancestor request" in rendered
    assert "Implement the change" in rendered
    assert "Review the change" in rendered
    assert "%id" not in rendered
    assert "%wait" not in rendered
    assert "#fork_by_chat" not in rendered
    assert "ANCESTOR_SECRET_REPLY" not in rendered
    assert "EARLY_SECRET_REPLY" not in rendered
    assert "LATE_SECRET_REPLY" not in rendered
    assert "model `openai/gpt-5`" in rendered
    assert "model `claude/opus`" in rendered
    assert "approximately 4 words / 1 lines" in rendered
    assert "approximately 3 words / 2 lines" in rendered
    assert f"transcript `{early_chat}`" in rendered
    assert f"transcript `{late_chat}`" in rendered


def test_mixed_agent_and_clan_sources_keep_agent_reply_only(
    tmp_path: Path,
) -> None:
    agent_chat = tmp_path / "agent.md"
    agent_chat.write_text(
        "## Prompt\n\nAgent prompt\n\n## Response\n\nAGENT_FULL_REPLY\n",
        encoding="utf-8",
    )
    clan_chat = tmp_path / "clan.md"
    clan_chat.write_text(
        "## Prompt\n\nClan prompt\n\n## Response\n\nCLAN_SECRET_REPLY\n",
        encoding="utf-8",
    )
    artifact_dir = _write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )

    rendered = build_fork_injected_history(
        [
            {"kind": "agent", "name": "planner", "path": str(agent_chat)},
            {
                "kind": "clan",
                "name": "review",
                "generation": "20260718010000",
                "tribe": None,
                "members": [
                    {
                        "name": "review.alpha",
                        "path": str(clan_chat),
                        "artifact_dir": str(artifact_dir),
                    }
                ],
            },
        ]
    )

    assert "## Source 1 of 2 — agent `planner`" in rendered
    assert "## Source 2 of 2 — agent clan `review`" in rendered
    assert "AGENT_FULL_REPLY" in rendered
    assert "Clan prompt" in rendered
    assert "CLAN_SECRET_REPLY" not in rendered


def test_family_block_renders_full_ordered_transcripts_without_ancestor_duplication(
    tmp_path: Path,
) -> None:
    outside_chat = tmp_path / "outside.md"
    outside_chat.write_text(
        "## Prompt\n\nOutside context\n\n## Response\n\nOUTSIDE_REPLY\n",
        encoding="utf-8",
    )
    planner_chat = tmp_path / "planner.md"
    planner_chat.write_text(
        "## Prompt\n\n"
        f"#fork_by_chat:{outside_chat} Plan the change\n\n"
        "## Response\n\nPLANNER_FULL_REPLY\n",
        encoding="utf-8",
    )
    coder_chat = tmp_path / "coder.md"
    coder_chat.write_text(
        "## Prompt\n\n"
        f"#fork_by_chat:{planner_chat} #fork_by_chat:{outside_chat} "
        "Implement the change\n\n"
        "## Response\n\nCODER_FULL_REPLY\n",
        encoding="utf-8",
    )
    planner_dir = _write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )
    coder_dir = _write_member_artifacts(
        tmp_path / "artifacts",
        "20260718010202",
        model="claude-fable-5",
        provider="anthropic",
    )
    source = {
        "kind": "family",
        "name": "cx",
        # Intentionally reverse the wire order; rendering is chain-ordered.
        "members": [
            {
                "name": "cx--code",
                "path": str(coder_chat),
                "artifact_dir": str(coder_dir),
                "outcome": "completed",
            },
            {
                "name": "cx--plan",
                "path": str(planner_chat),
                "artifact_dir": str(planner_dir),
                "outcome": "completed",
            },
        ],
        "excluded": [{"name": "cx--fix", "status": "running"}],
    }

    rendered = build_fork_injected_history([source])

    assert "# Previous Conversations" in rendered
    assert "agent family `cx`" in rendered
    assert "**Members shown:** 2 of 3 (sequential chain, oldest first)" in rendered
    assert "**Not shown:** `cx--fix` (running)" in rendered
    assert "Family members ran as one sequential chain" in rendered
    assert "transcripts of prior agents' conversations, not your own" in rendered
    assert rendered.index("cx--plan") < rendered.index("cx--code")
    assert "**Outcome:** `completed`" in rendered
    assert "**Model:** `openai/gpt-5`" in rendered
    assert "**Model:** `anthropic/claude-fable-5`" in rendered
    assert f"**Transcript:** `{planner_chat}`" in rendered
    assert f"**Transcript:** `{coder_chat}`" in rendered
    assert rendered.count("OUTSIDE_REPLY") == 1
    assert rendered.count("PLANNER_FULL_REPLY") == 1
    assert rendered.count("CODER_FULL_REPLY") == 1
    assert "Plan the change" in rendered
    assert "Implement the change" in rendered
    assert "#fork_by_chat" not in rendered


def test_family_mixed_with_agent_and_clan_uses_correct_source_guidance(
    tmp_path: Path,
) -> None:
    family_chat = tmp_path / "family.md"
    agent_chat = tmp_path / "agent.md"
    clan_chat = tmp_path / "clan.md"
    family_chat.write_text(
        "## Prompt\n\nFamily prompt\n\n## Response\n\nFAMILY_REPLY\n",
        encoding="utf-8",
    )
    agent_chat.write_text(
        "## Prompt\n\nAgent prompt\n\n## Response\n\nAGENT_REPLY\n",
        encoding="utf-8",
    )
    clan_chat.write_text(
        "## Prompt\n\nClan prompt\n\n## Response\n\nCLAN_REPLY\n",
        encoding="utf-8",
    )
    family_dir = _write_member_artifacts(
        tmp_path / "family-artifacts",
        "20260718010101",
        model="gpt-5",
        provider="openai",
    )
    clan_dir = _write_member_artifacts(
        tmp_path / "clan-artifacts",
        "20260718010202",
        model="opus",
        provider="claude",
    )
    family_source = {
        "kind": "family",
        "name": "cx",
        "members": [
            {
                "name": "cx--code",
                "path": str(family_chat),
                "artifact_dir": str(family_dir),
                "outcome": "completed",
            }
        ],
        "excluded": [],
    }
    clan_source = {
        "kind": "clan",
        "name": "review",
        "generation": "20260718010000",
        "tribe": None,
        "members": [
            {
                "name": "review.alpha",
                "path": str(clan_chat),
                "artifact_dir": str(clan_dir),
            }
        ],
    }

    family_agent = build_fork_injected_history(
        [
            family_source,
            {"kind": "agent", "name": "builder", "path": str(agent_chat)},
        ]
    )
    family_clan = build_fork_injected_history([family_source, clan_source])

    for rendered in (family_agent, family_clan):
        assert "Source sections are independent parents" in rendered
        assert "Members inside an agent family section are sequential" in rendered
        assert "## Source 1 of 2 — agent family `cx`" in rendered
    assert "## Source 2 of 2 — agent `builder`" in family_agent
    assert "AGENT_REPLY" in family_agent
    assert "## Source 2 of 2 — agent clan `review`" in family_clan
    assert "Clan prompt" in family_clan
    assert "CLAN_REPLY" not in family_clan
