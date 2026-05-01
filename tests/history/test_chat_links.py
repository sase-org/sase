"""Tests for sase.history.chat_links."""

import os
import textwrap

from sase.history.chat_links import (
    append_links_to_chat,
    build_linked_chats_section,
    format_plan_as_response,
)

SAMPLE_LINKS = [
    (".plan", "~/.sase/chats/branch-ace_run-a.plan-260327_152207.md"),
    (".coder", "~/.sase/chats/branch-ace_run-a.coder-260327_153045.md"),
]


class TestBuildLinkedChatsSection:
    def test_basic_list(self) -> None:
        result = build_linked_chats_section(SAMPLE_LINKS)
        assert "## Linked Chats" in result
        assert "- 1. .plan" in result
        assert "- 2. .coder" in result

    def test_highlights_current(self) -> None:
        result = build_linked_chats_section(SAMPLE_LINKS, current_role=".plan")
        assert "- **1. .plan**" in result
        # Other entry should NOT be bold
        assert "- 2. .coder" in result

    def test_preserves_legacy_code_links(self) -> None:
        result = build_linked_chats_section(
            [(".code", "~/.sase/chats/branch-ace_run-a.code-260327_153045.md")]
        )
        assert "- 1. .code" in result
        assert "a.code-260327_153045.md" in result

    def test_single_entry(self) -> None:
        result = build_linked_chats_section([(".plan", "~/path.md")])
        assert "- 1. .plan — `~/path.md`" in result


class TestAppendLinksToChat:
    def test_inserts_after_timestamp(self, tmp_path: object) -> None:
        chat_file = os.path.join(str(tmp_path), "chat.md")
        original = textwrap.dedent("""\
            # Chat History - ace-run

            **Timestamp:** 2026-03-27 15:22:07 UTC

            ## Prompt

            Do the thing.

            ## Response

            Done.
        """)
        with open(chat_file, "w") as f:
            f.write(original)

        links_section = build_linked_chats_section(SAMPLE_LINKS)
        append_links_to_chat(chat_file, links_section)

        with open(chat_file) as f:
            content = f.read()

        # Links section should appear between timestamp and prompt
        ts_pos = content.index("**Timestamp:**")
        links_pos = content.index("## Linked Chats")
        prompt_pos = content.index("## Prompt")
        assert ts_pos < links_pos < prompt_pos

    def test_replaces_existing(self, tmp_path: object) -> None:
        chat_file = os.path.join(str(tmp_path), "chat.md")
        original = textwrap.dedent("""\
            # Chat History - ace-run

            **Timestamp:** 2026-03-27 15:22:07 UTC

            ## Linked Chats

            - 1. .plan — `~/old.md`

            ## Prompt

            Do the thing.
        """)
        with open(chat_file, "w") as f:
            f.write(original)

        new_links = build_linked_chats_section(SAMPLE_LINKS)
        append_links_to_chat(chat_file, new_links)

        with open(chat_file) as f:
            content = f.read()

        # Old entry replaced
        assert "~/old.md" not in content
        # New entries present
        assert "a.plan-260327_152207.md" in content
        assert "a.coder-260327_153045.md" in content
        # Only one linked-chats section
        assert content.count("## Linked Chats") == 1

    def test_missing_file_is_noop(self) -> None:
        # Should not raise
        append_links_to_chat("/nonexistent/chat.md", "## Linked Chats\n")


class TestFormatPlanAsResponse:
    def test_basic_formatting(self, tmp_path: object) -> None:
        plan_file = os.path.join(str(tmp_path), "plan.md")
        with open(plan_file, "w") as f:
            f.write("# My Plan\n\n## Step 1\n\nDo A.\n\n## Step 2\n\nDo B.\n")

        result = format_plan_as_response(plan_file)
        assert "*Plan submitted for review.*" in result
        assert f"**Plan file:** `{plan_file}`" in result
        assert "> # My Plan" in result
        assert "> Do A." in result

    def test_short_plan(self, tmp_path: object) -> None:
        plan_file = os.path.join(str(tmp_path), "short.md")
        with open(plan_file, "w") as f:
            f.write("# Short Plan\n\nJust one thing.\n")

        result = format_plan_as_response(plan_file)
        assert "*Plan submitted for review.*" in result
        # Short plan should NOT have "See full plan" trailer
        assert "*See full plan file for details.*" not in result

    def test_strips_frontmatter(self, tmp_path: object) -> None:
        plan_file = os.path.join(str(tmp_path), "fm.md")
        with open(plan_file, "w") as f:
            f.write("---\ntitle: Plan\nstatus: draft\n---\n# Actual Content\n\nBody.\n")

        result = format_plan_as_response(plan_file)
        assert "> # Actual Content" in result
        assert "title:" not in result
        assert "status:" not in result

    def test_missing_file(self) -> None:
        result = format_plan_as_response("/nonexistent/plan.md")
        assert "*Plan submitted for review.*" in result
        assert "**Plan file:**" in result

    def test_long_plan_truncates(self, tmp_path: object) -> None:
        plan_file = os.path.join(str(tmp_path), "long.md")
        lines = [f"Line {i}" for i in range(1, 25)]
        with open(plan_file, "w") as f:
            f.write("\n".join(lines) + "\n")

        result = format_plan_as_response(plan_file)
        assert "*See full plan file for details.*" in result
        # Should have exactly 10 preview lines
        assert result.count("> Line") == 10
