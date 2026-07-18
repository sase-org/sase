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
        f"%name:review.alpha #fork_by_chat:`{ancestor_chat}`\nImplement the change\n\n"
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
    assert "%name" not in rendered
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
