"""Tests for disabled region protection in xprompt processing."""

from unittest.mock import MagicMock, patch

from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)


class TestProtectUnprotectRoundTrip:
    """Tests for protect_disabled_regions / unprotect_disabled_regions."""

    def test_basic_roundtrip(self) -> None:
        text = (
            "before\n%xprompts_enabled:false\nsecret\n%xprompts_enabled:true\nafter\n"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "secret" not in protected
        assert "before" in protected
        assert "after" in protected
        restored = unprotect_disabled_regions(protected, regions)
        assert restored == text

    def test_leading_whitespace_before_marker(self) -> None:
        """Markers preceded by whitespace (e.g. after embedded workflow replacement)."""
        text = " %xprompts_enabled:false\n{{ resolve.path }}\n%xprompts_enabled:true\nquery\n"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "resolve" not in protected
        assert "query" in protected
        assert len(regions) == 1

    def test_tab_indented_markers(self) -> None:
        text = "\t%xprompts_enabled:false\nhidden\n\t%xprompts_enabled:true\nvisible\n"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "hidden" not in protected
        assert "visible" in protected


class TestStripDisabledRegionMarkers:
    """Tests for strip_disabled_region_markers."""

    def test_strips_markers_with_leading_whitespace(self) -> None:
        text = " %xprompts_enabled:false\ncontent\n %xprompts_enabled:true\n"
        result = strip_disabled_region_markers(text)
        assert "%xprompts_enabled" not in result
        assert "content" in result


class TestProcessXpromptReferencesDisabledRegions:
    """Integration: process_xprompt_references skips disabled region content."""


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
