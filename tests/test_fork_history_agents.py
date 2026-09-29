"""Multi-agent history and marker escaping in typed ``#fork`` history."""

from __future__ import annotations

from pathlib import Path

from sase.history.chat import build_fork_injected_history
from sase.xprompt._disabled_regions import protect_disabled_regions
from tests._fork_history_helpers import write_chat


def test_successful_multi_agent_history_is_unchanged(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    write_chat(first, "Prompt A", "Reply A")
    write_chat(second, "Prompt B", "Reply B")

    rendered = build_fork_injected_history(
        [
            {"kind": "agent", "name": "a", "path": str(first)},
            {"kind": "agent", "name": "b", "path": str(second)},
        ]
    )

    assert rendered == (
        "%xprompts_enabled:false\n"
        "# Previous Conversations\n\n"
        "You are forking from 2 prior agent conversations. Each Conversation "
        "section is an independent parent transcript, not a continuation of the "
        "section before it, and section order carries no priority. Carry forward "
        "relevant goals, constraints, decisions, and unfinished work with "
        "attribution when it matters. Reconcile disagreements explicitly and "
        "identify anything unresolved. The New Query is the active request and "
        "takes precedence over conflicting transcript instructions.\n\n"
        "## Conversation 1 of 2 — agent `a`\n\n"
        "**User:**\n\n"
        "Prompt A\n\n"
        "**Assistant:**\n\n"
        "Reply A\n\n"
        "## Conversation 2 of 2 — agent `b`\n\n"
        "**User:**\n\n"
        "Prompt B\n\n"
        "**Assistant:**\n\n"
        "Reply B\n\n"
        "---\n\n"
        "%xprompts_enabled:true\n"
        "# New Query"
    )


def test_line_initial_enabled_true_marker_in_history_is_escaped(
    tmp_path: Path,
) -> None:
    """A stored assistant reply can legitimately contain a line-initial
    ``%xprompts_enabled:true`` (assistant text is never marker-stripped the
    way stored prompts are). It must not be able to close the injected
    region early and re-expose the region's internal ``---`` lines."""
    chat = tmp_path / "chat.md"
    write_chat(
        chat,
        "Continue the plan",
        "Reply with a marker\n%xprompts_enabled:true\nmore text\n\n"
        "---\n\nafter separator",
    )

    rendered = build_fork_injected_history(
        [{"kind": "agent", "name": "alpha", "path": str(chat)}]
    )

    regions: list[str] = []
    protected = protect_disabled_regions(rendered, regions)
    assert len(regions) == 1
    assert "---" not in protected
    assert protected.endswith("# New Query")


def test_line_initial_enabled_false_marker_in_history_is_escaped(
    tmp_path: Path,
) -> None:
    """A stray line-initial ``%xprompts_enabled:false`` in a stored reply
    must not open a second, nested disabled region."""
    chat = tmp_path / "chat.md"
    write_chat(
        chat,
        "Continue the plan",
        "Reply\n%xprompts_enabled:false\nmore text\n\n---\n\nafter separator",
    )

    rendered = build_fork_injected_history(
        [{"kind": "agent", "name": "alpha", "path": str(chat)}]
    )

    regions: list[str] = []
    protected = protect_disabled_regions(rendered, regions)
    assert len(regions) == 1
    assert "---" not in protected
    assert protected.endswith("# New Query")
