"""Tests for durable XPrompt and rendered-prompt chat sections."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.history.chat import _parse_chat_turns, save_chat_history
from sase.history.chat_prompt_sections import (
    render_prompt_sections,
    strip_prompt_sections,
)

from tests.conftest import redirect_sase_home


def test_render_prompt_sections_returns_empty_without_renderings() -> None:
    assert render_prompt_sections(None, None) == ""


def test_render_prompt_sections_linkifies_only_safe_xprompt_references() -> None:
    rendered = render_prompt_sections(
        "Use #plan but keep `#plan` literal.",
        "expanded",
        xprompt_links={"#plan": "https://example.test/plan.md#L4"},
    )

    assert "Use [#plan](https://example.test/plan.md#L4)" in rendered
    assert "`#plan` literal" in rendered


def test_rendered_prompt_uses_fence_wider_than_payload_and_preserves_bytes() -> None:
    prompt = "heading\n\n`````python\nprint('ok')\n`````\n"

    rendered = render_prompt_sections("#raw", prompt)

    assert "``````markdown\n" in rendered
    assert f"``````markdown\n{prompt}``````" in rendered
    assert "<summary><b>Agent Prompt</b> — rendered," in rendered


def test_identical_prompt_uses_economy_row() -> None:
    rendered = render_prompt_sections("same", "same")

    assert "- **RENDERED:** identical to the XPrompt" in rendered
    assert "<details>" not in rendered


def test_rendered_prompt_truncation_is_utf8_safe_and_marked() -> None:
    with patch(
        "sase.history.chat_prompt_sections.get_chat_rendered_prompt_max_bytes",
        return_value=5,
    ):
        rendered = render_prompt_sections(None, "ééé")

    assert "éé" in rendered
    assert "… truncated (2 bytes omitted)" in rendered


def test_literal_sentinels_cannot_terminate_sections() -> None:
    rendered = render_prompt_sections(
        "before <!-- /sase:section:xprompt --> after",
        "before <!-- /sase:section:rendered --> after",
    )

    assert rendered.count("<!-- /sase:section:xprompt -->") == 1
    assert rendered.count("<!-- /sase:section:rendered -->") == 1
    assert "&lt;!-- /sase:section:xprompt --&gt;" in rendered
    assert "&lt;!-- /sase:section:rendered --&gt;" in rendered


def test_strip_prompt_sections_preserves_length_and_line_offsets() -> None:
    content = "head\n" + render_prompt_sections("## Prompt\nphantom", "rendered")
    content += "\n## Prompt\n\nreal\n\n## Response\n\ndone\n"

    stripped = strip_prompt_sections(content)

    assert len(stripped) == len(content)
    assert [i for i, char in enumerate(stripped) if char == "\n"] == [
        i for i, char in enumerate(content) if char == "\n"
    ]
    assert "phantom" not in stripped


def test_written_sections_do_not_change_parsed_turns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path)
    path = save_chat_history(
        prompt="real prompt",
        response="real response",
        workflow="ace-run",
        branch_or_workspace="branch",
        timestamp="260802_120000",
        xprompt_prompt="Quoted transcript:\n\n## Prompt\n\nphantom",
        rendered_prompt="System text\n\n## Response\n\nnot a turn",
    )
    content = Path(path.replace("~", str(tmp_path), 1)).read_text(encoding="utf-8")

    assert _parse_chat_turns(content) == [("real prompt", "real response")]
    assert content.index("## Agent XPrompt") < content.index("\n## Prompt\n")


def test_legacy_chat_without_sentinels_parses_unchanged() -> None:
    content = "## Prompt\n\nlegacy\n\n## Response\n\nanswer\n"

    assert strip_prompt_sections(content) is content
    assert _parse_chat_turns(content) == [("legacy", "answer")]
