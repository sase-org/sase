"""Agent-session sources in typed ``#fork`` history assembly."""

from __future__ import annotations

from pathlib import Path

from sase.history.chat import build_fork_injected_history
from tests._fork_history_helpers import proc_source, write_member_artifacts


def test_agent_session_block_renders_full_ordered_transcripts_without_ancestor_duplication(
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
    planner_dir = write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )
    coder_dir = write_member_artifacts(
        tmp_path / "artifacts",
        "20260718010202",
        model="claude-fable-5",
        provider="anthropic",
    )
    source = {
        "kind": "session",
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
    assert "agent session `cx`" in rendered
    assert "**Members shown:** 2 of 3 (sequential chain, oldest first)" in rendered
    assert "**Not shown:** `cx--fix` (running)" in rendered
    assert "Session members ran as one sequential chain" in rendered
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


def test_legacy_family_kind_fork_source_renders_as_agent_session(
    tmp_path: Path,
) -> None:
    chat = tmp_path / "planner.md"
    chat.write_text(
        "## Prompt\n\nPlan the change\n\n## Response\n\nPLANNER_FULL_REPLY\n",
        encoding="utf-8",
    )
    artifact_dir = write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )
    members = [
        {
            "name": "cx--plan",
            "path": str(chat),
            "artifact_dir": str(artifact_dir),
            "outcome": "completed",
        }
    ]

    rendered_session = build_fork_injected_history(
        [{"kind": "session", "name": "cx", "members": members, "excluded": []}]
    )
    # legacy agent-family spelling: pre-rename stored fork sources carry "family".
    rendered_legacy = build_fork_injected_history(
        [{"kind": "family", "name": "cx", "members": members, "excluded": []}]
    )

    assert rendered_legacy == rendered_session
    assert "agent session `cx`" in rendered_legacy


def test_agent_session_mixed_with_agent_and_clan_uses_correct_source_guidance(
    tmp_path: Path,
) -> None:
    agent_session_chat = tmp_path / "agent_session.md"
    agent_chat = tmp_path / "agent.md"
    clan_chat = tmp_path / "clan.md"
    agent_session_chat.write_text(
        "## Prompt\n\nAgent-session prompt\n\n## Response\n\nAGENT_SESSION_REPLY\n",
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
    agent_session_dir = write_member_artifacts(
        tmp_path / "agent-session-artifacts",
        "20260718010101",
        model="gpt-5",
        provider="openai",
    )
    clan_dir = write_member_artifacts(
        tmp_path / "clan-artifacts",
        "20260718010202",
        model="opus",
        provider="claude",
    )
    agent_session_source = {
        "kind": "session",
        "name": "cx",
        "members": [
            {
                "name": "cx--code",
                "path": str(agent_session_chat),
                "artifact_dir": str(agent_session_dir),
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

    agent_session_agent = build_fork_injected_history(
        [
            agent_session_source,
            {"kind": "agent", "name": "builder", "path": str(agent_chat)},
        ]
    )
    agent_session_clan = build_fork_injected_history(
        [agent_session_source, clan_source]
    )

    for rendered in (agent_session_agent, agent_session_clan):
        assert "Source sections are independent parents" in rendered
        assert "Members inside an agent session section are sequential" in rendered
        assert "## Source 1 of 2 — agent session `cx`" in rendered
    assert "## Source 2 of 2 — agent `builder`" in agent_session_agent
    assert "AGENT_REPLY" in agent_session_agent
    assert "## Source 2 of 2 — agent clan `review`" in agent_session_clan
    assert "Clan prompt" in agent_session_clan
    assert "CLAN_REPLY" not in agent_session_clan


def test_agent_session_with_monitor_member_renders_named_proc_heading(
    tmp_path: Path,
) -> None:
    planner_chat = tmp_path / "planner.md"
    planner_chat.write_text(
        "## Prompt\n\nPlan it\n\n## Response\n\nPLAN_REPLY\n", encoding="utf-8"
    )
    planner_dir = write_member_artifacts(
        tmp_path / "artifacts", "20260718010101", model="gpt-5", provider="openai"
    )
    monitor_dir = tmp_path / "artifacts" / "20260718010202"
    monitor_dir.mkdir(parents=True)
    source = {
        "kind": "session",
        "name": "cx",
        "members": [
            {
                "kind": "agent",
                "name": "cx--plan",
                "path": str(planner_chat),
                "artifact_dir": str(planner_dir),
                "outcome": "completed",
            },
            {
                "kind": "proc",
                "name": "cx--mon",
                "artifact_dir": str(monitor_dir),
                "outcome": "completed",
                "proc": proc_source("cx--mon", is_monitor=True)["proc"],
            },
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([source])

    assert "### Member 2 of 2 — named proc (monitor) `cx--mon`" in rendered
    assert "command execution records, not conversations" in rendered
    assert "PLAN_REPLY" in rendered
