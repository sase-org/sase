"""Tests for disabled region protection in xprompt processing."""

from unittest.mock import MagicMock, patch


class TestProtectUnprotectRoundTrip:
    """Tests for protect_disabled_regions / unprotect_disabled_regions."""


class TestStripDisabledRegionMarkers:
    """Tests for strip_disabled_region_markers."""


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
