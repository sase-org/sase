"""Tests for fenced code block protection in xprompt processing."""

from unittest.mock import MagicMock, patch

from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import process_xprompt_references


class TestProtectUnprotectRoundTrip:
    """Tests for protect_fenced_blocks / unprotect_fenced_blocks."""

    def test_no_code_blocks(self) -> None:
        blocks: list[str] = []
        result = protect_fenced_blocks("hello world", blocks)
        assert result == "hello world"
        assert blocks == []

    def test_single_block_round_trip(self) -> None:
        original = "before\n```\ncode\n```\nafter"
        blocks: list[str] = []
        protected = protect_fenced_blocks(original, blocks)
        assert len(blocks) == 1
        assert "code" not in protected
        restored = unprotect_fenced_blocks(protected, blocks)
        assert restored == original

    def test_multiple_blocks_round_trip(self) -> None:
        original = "a\n```\nblock1\n```\nb\n```py\nblock2\n```\nc"
        blocks: list[str] = []
        protected = protect_fenced_blocks(original, blocks)
        assert len(blocks) == 2
        assert "block1" not in protected
        assert "block2" not in protected
        restored = unprotect_fenced_blocks(protected, blocks)
        assert restored == original

    def test_incremental_extraction(self) -> None:
        """Calling protect twice appends to the same list without conflicts."""
        blocks: list[str] = []
        text1 = "a\n```\nfirst\n```\nb"
        text1 = protect_fenced_blocks(text1, blocks)
        assert len(blocks) == 1

        # Simulate expanded content introducing a new code block
        text2 = text1 + "\n```\nsecond\n```\nc"
        text2 = protect_fenced_blocks(text2, blocks)
        assert len(blocks) == 2

        restored = unprotect_fenced_blocks(text2, blocks)
        assert "first" in restored
        assert "second" in restored

    def test_block_with_language_spec(self) -> None:
        original = "text\n```python\ndef foo():\n    pass\n```\nmore"
        blocks: list[str] = []
        protected = protect_fenced_blocks(original, blocks)
        assert "def foo" not in protected
        restored = unprotect_fenced_blocks(protected, blocks)
        assert restored == original

    def test_xprompt_ref_inside_block_not_visible(self) -> None:
        """#name patterns inside code blocks are hidden after protection."""
        text = "outside\n```\n#my_xprompt some text\n```\n"
        blocks: list[str] = []
        protected = protect_fenced_blocks(text, blocks)
        assert "#my_xprompt" not in protected


class TestProcessXpromptReferencesCodeBlocks:
    """Integration: process_xprompt_references skips code block content."""

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_ref_inside_code_block_not_expanded(self, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = {
            "greeting": XPrompt(name="greeting", content="Hello!"),
        }
        prompt = "before\n```\n#greeting\n```\nafter"
        result = process_xprompt_references(prompt)
        # The #greeting inside the code block should NOT be expanded
        assert "#greeting" in result
        assert "Hello!" not in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_ref_outside_code_block_still_expanded(
        self, mock_get_all: MagicMock
    ) -> None:
        mock_get_all.return_value = {
            "greeting": XPrompt(name="greeting", content="Hello!"),
        }
        prompt = "#greeting\n```\nsome code\n```"
        result = process_xprompt_references(prompt)
        assert "Hello!" in result
        assert "some code" in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_code_block_preserved_in_output(self, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = {
            "greeting": XPrompt(name="greeting", content="Hello!"),
        }
        prompt = "#greeting\n```bash\necho hello\n```"
        result = process_xprompt_references(prompt)
        assert "```bash\necho hello\n```" in result
        assert "Hello!" in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_shorthand_inside_code_block_not_processed(
        self, mock_get_all: MagicMock
    ) -> None:
        """#name: text shorthand inside code blocks should not be converted."""
        mock_get_all.return_value = {
            "todo": XPrompt(
                name="todo",
                content="TODO: {{ task }}",
                inputs=[InputArg(name="task", type=InputType.LINE)],
            ),
        }
        prompt = "text\n```\n#todo: buy milk\n```"
        result = process_xprompt_references(prompt)
        # The shorthand should remain unconverted
        assert "#todo: buy milk" in result
        assert "TODO:" not in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_expanded_xprompt_with_code_block(self, mock_get_all: MagicMock) -> None:
        """Code blocks in expanded xprompt content are protected on next iteration."""
        mock_get_all.return_value = {
            "outer": XPrompt(
                name="outer",
                content="Result:\n```\n#inner should not expand\n```",
            ),
            "inner": XPrompt(name="inner", content="EXPANDED"),
        }
        prompt = "#outer"
        result = process_xprompt_references(prompt)
        # #outer should be expanded, but #inner inside the code block should not
        assert "Result:" in result
        assert "#inner should not expand" in result
        assert "EXPANDED" not in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_multiple_code_blocks_with_refs(self, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = {
            "foo": XPrompt(name="foo", content="FOO"),
            "bar": XPrompt(name="bar", content="BAR"),
        }
        prompt = (
            "#foo outside\n"
            "```\n#foo inside block1\n```\n"
            "between\n"
            "```\n#bar inside block2\n```\n"
        )
        result = process_xprompt_references(prompt)
        assert "FOO outside" in result
        assert "#foo inside block1" in result
        assert "#bar inside block2" in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_no_refs_in_prompt_skips_early(self, mock_get_all: MagicMock) -> None:
        """When there are no # chars at all, skip processing entirely."""
        mock_get_all.return_value = {
            "foo": XPrompt(name="foo", content="FOO"),
        }
        result = process_xprompt_references("no refs here")
        assert result == "no refs here"

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_only_refs_inside_code_blocks(self, mock_get_all: MagicMock) -> None:
        """When all # refs are inside code blocks, none should be expanded."""
        mock_get_all.return_value = {
            "foo": XPrompt(name="foo", content="FOO"),
        }
        prompt = "text\n```\n#foo\n```\nmore text"
        result = process_xprompt_references(prompt)
        assert "#foo" in result
        assert "FOO" not in result
