"""Tests for disabled region protection in xprompt processing."""

from unittest.mock import MagicMock, patch

from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import process_xprompt_references


class TestProtectUnprotectRoundTrip:
    """Tests for protect_disabled_regions / unprotect_disabled_regions."""

    def test_no_markers(self) -> None:
        regions: list[str] = []
        result = protect_disabled_regions("hello world", regions)
        assert result == "hello world"
        assert regions == []

    def test_single_region_round_trip(self) -> None:
        original = (
            "before\n"
            "%xprompts_enabled:false\n"
            "protected content\n"
            "%xprompts_enabled:true\n"
            "after"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(original, regions)
        assert len(regions) == 1
        assert "protected content" not in protected
        assert "before" in protected
        assert "after" in protected
        restored = unprotect_disabled_regions(protected, regions)
        assert restored == original

    def test_multiple_regions_round_trip(self) -> None:
        original = (
            "a\n"
            "%xprompts_enabled:false\n"
            "region1\n"
            "%xprompts_enabled:true\n"
            "b\n"
            "%xprompts_enabled:false\n"
            "region2\n"
            "%xprompts_enabled:true\n"
            "c"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(original, regions)
        assert len(regions) == 2
        assert "region1" not in protected
        assert "region2" not in protected
        restored = unprotect_disabled_regions(protected, regions)
        assert restored == original

    def test_content_outside_regions_preserved(self) -> None:
        text = (
            "outside1\n"
            "%xprompts_enabled:false\n"
            "inside\n"
            "%xprompts_enabled:true\n"
            "outside2"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "outside1" in protected
        assert "outside2" in protected

    def test_xprompt_ref_hidden_after_protection(self) -> None:
        text = (
            "outside\n"
            "%xprompts_enabled:false\n"
            "#my_xprompt some text\n"
            "%xprompts_enabled:true\n"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "#my_xprompt" not in protected

    def test_directive_hidden_after_protection(self) -> None:
        text = "%xprompts_enabled:false\n%model:gpt-4\n%xprompts_enabled:true\n"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "%model:gpt-4" not in protected

    def test_command_sub_hidden_after_protection(self) -> None:
        text = "%xprompts_enabled:false\n$(echo hello)\n%xprompts_enabled:true\n"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "$(echo hello)" not in protected


class TestStripDisabledRegionMarkers:
    """Tests for strip_disabled_region_markers."""

    def test_strip_markers(self) -> None:
        text = "before\n%xprompts_enabled:false\ncontent\n%xprompts_enabled:true\nafter"
        result = strip_disabled_region_markers(text)
        assert "%xprompts_enabled" not in result
        assert "before\ncontent\nafter" == result

    def test_strip_markers_with_trailing_spaces(self) -> None:
        text = "%xprompts_enabled:false  \ncontent\n%xprompts_enabled:true\t\n"
        result = strip_disabled_region_markers(text)
        assert "%xprompts_enabled" not in result
        assert result == "content\n"

    def test_no_markers(self) -> None:
        text = "no markers here"
        assert strip_disabled_region_markers(text) == text


class TestProcessXpromptReferencesDisabledRegions:
    """Integration: process_xprompt_references skips disabled region content."""

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_ref_inside_disabled_region_not_expanded(
        self, mock_get_all: MagicMock
    ) -> None:
        mock_get_all.return_value = {
            "greeting": XPrompt(name="greeting", content="Hello!"),
        }
        prompt = (
            "before\n%xprompts_enabled:false\n#greeting\n%xprompts_enabled:true\nafter"
        )
        result = process_xprompt_references(prompt)
        assert "#greeting" in result
        assert "Hello!" not in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_ref_outside_disabled_region_still_expanded(
        self, mock_get_all: MagicMock
    ) -> None:
        mock_get_all.return_value = {
            "greeting": XPrompt(name="greeting", content="Hello!"),
        }
        prompt = (
            "#greeting\n%xprompts_enabled:false\nprotected\n%xprompts_enabled:true\n"
        )
        result = process_xprompt_references(prompt)
        assert "Hello!" in result
        assert "protected" in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_code_blocks_inside_disabled_regions(self, mock_get_all: MagicMock) -> None:
        mock_get_all.return_value = {
            "foo": XPrompt(name="foo", content="FOO"),
        }
        prompt = "%xprompts_enabled:false\n```\n#foo\n```\n%xprompts_enabled:true\n"
        result = process_xprompt_references(prompt)
        assert "#foo" in result
        assert "FOO" not in result

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_markers_preserved_after_xprompt_processing(
        self, mock_get_all: MagicMock
    ) -> None:
        """Markers survive xprompt processing for downstream stages."""
        mock_get_all.return_value = {}
        prompt = "%xprompts_enabled:false\ncontent\n%xprompts_enabled:true\n"
        result = process_xprompt_references(prompt)
        assert "%xprompts_enabled:false" in result
        assert "%xprompts_enabled:true" in result


class TestPreprocessPromptLateDisabledRegions:
    """Integration: preprocess_prompt_late strips markers and protects content."""

    @patch("sase.gemini_wrapper.file_references.process_command_substitution")
    @patch(
        "sase.gemini_wrapper.file_references.format_with_prettier",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.gemini_wrapper.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_markers_stripped_from_final_output(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        mock_cmd_sub: MagicMock,
    ) -> None:
        from sase.llm_provider.preprocessing import preprocess_prompt_late

        mock_cmd_sub.side_effect = lambda x: x
        prompt = (
            "before\n%xprompts_enabled:false\nprotected\n%xprompts_enabled:true\nafter"
        )
        result = preprocess_prompt_late(prompt, file_ref_mode="skip")
        assert "%xprompts_enabled" not in result
        assert "before" in result
        assert "protected" in result
        assert "after" in result

    @patch("sase.gemini_wrapper.file_references.process_command_substitution")
    @patch(
        "sase.gemini_wrapper.file_references.format_with_prettier",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.gemini_wrapper.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_disabled_region_content_not_command_substituted(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        mock_cmd_sub: MagicMock,
    ) -> None:
        from sase.llm_provider.preprocessing import preprocess_prompt_late

        # Track what text gets passed to command substitution
        cmd_sub_inputs: list[str] = []

        def track_cmd_sub(text: str) -> str:
            cmd_sub_inputs.append(text)
            return text

        mock_cmd_sub.side_effect = track_cmd_sub
        prompt = (
            "%xprompts_enabled:false\n$(dangerous command)\n%xprompts_enabled:true\n"
        )
        preprocess_prompt_late(prompt, file_ref_mode="skip")
        # The command substitution should NOT see the $(dangerous command) text
        for inp in cmd_sub_inputs:
            assert "$(dangerous command)" not in inp
