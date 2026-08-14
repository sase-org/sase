"""Tests for disabled region protection in xprompt processing."""

from unittest.mock import MagicMock, patch

from sase.xprompt._disabled_regions import (
    _escape_disabled_region_markers,
    ensure_disabled_region_at_line_start,
    protect_disabled_regions,
    strip_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
    wrap_disabled_region,
)


class TestEnsureDisabledRegionAtLineStart:
    """Tests for prompt-part disabled-marker positioning."""

    def test_mid_line_marker_gets_exactly_one_newline(self) -> None:
        content = " \t%xprompts_enabled:false\nhistory"

        assert ensure_disabled_region_at_line_start(content, False) == (
            "\n \t%xprompts_enabled:false\nhistory"
        )

    def test_line_start_marker_is_unchanged(self) -> None:
        content = "%xprompts_enabled:false\nhistory"

        assert ensure_disabled_region_at_line_start(content, True) == content

    def test_non_marker_content_is_unchanged(self) -> None:
        content = "# New Query"

        assert ensure_disabled_region_at_line_start(content, False) == content

    def test_empty_content_is_unchanged(self) -> None:
        assert ensure_disabled_region_at_line_start("", False) == ""


class TestEscapeAndWrapDisabledRegions:
    """Tests for safe construction of disabled regions from untrusted text."""

    def test_escape_marker_text_neutralizes_open_and_close_markers(self) -> None:
        text = "%xprompts_enabled:false\nbody\n%xprompts_enabled:true"

        assert _escape_disabled_region_markers(text) == (
            "% xprompts_enabled:false\nbody\n% xprompts_enabled:true"
        )

    def test_wrap_disabled_region_escapes_inner_markers(self) -> None:
        wrapped = wrap_disabled_region("body\n%xprompts_enabled:true\n%effort:low")

        assert wrapped == (
            "%xprompts_enabled:false\n"
            "body\n"
            "% xprompts_enabled:true\n"
            "%effort:low\n"
            "%xprompts_enabled:true"
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

    def test_inline_closing_marker(self) -> None:
        """Closing marker at end of a content line (not on its own line)."""
        text = (
            "before\n"
            "%xprompts_enabled:false\n"
            "line one\n"
            "last line text. %xprompts_enabled:true\n"
            "after\n"
        )
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "line one" not in protected
        assert "last line text" not in protected
        assert "before" in protected
        assert "after" in protected
        assert len(regions) == 1
        restored = unprotect_disabled_regions(protected, regions)
        assert restored == text

    def test_inline_closing_marker_no_trailing_newline(self) -> None:
        """Inline closing marker at end of string without trailing newline."""
        text = "%xprompts_enabled:false\nhidden content. %xprompts_enabled:true"
        regions: list[str] = []
        protected = protect_disabled_regions(text, regions)
        assert "hidden content" not in protected
        assert len(regions) == 1


class TestStripDisabledRegionMarkers:
    """Tests for strip_disabled_region_markers."""

    def test_strips_markers_with_leading_whitespace(self) -> None:
        text = " %xprompts_enabled:false\ncontent\n %xprompts_enabled:true\n"
        result = strip_disabled_region_markers(text)
        assert "%xprompts_enabled" not in result
        assert "content" in result

    def test_strips_inline_closing_marker(self) -> None:
        """Inline closing marker is stripped, preserving the rest of the line."""
        text = "content line. %xprompts_enabled:true\n"
        result = strip_disabled_region_markers(text)
        assert "%xprompts_enabled" not in result
        assert result == "content line.\n"

    def test_strips_inline_closing_marker_no_trailing_newline(self) -> None:
        text = "content line. %xprompts_enabled:true"
        result = strip_disabled_region_markers(text)
        assert result == "content line."


class TestStripDisabledRegions:
    """Tests for removing whole disabled regions before validation scans."""

    def test_removes_whole_region(self) -> None:
        text = (
            "before\n"
            "%xprompts_enabled:false\n"
            "{{ missing }}\n"
            "#fake_xprompt\n"
            "%xprompts_enabled:true\n"
            "after\n"
        )

        assert strip_disabled_regions(text) == "before\nafter\n"

    def test_noop_without_markers(self) -> None:
        text = "before\n{{ live }}\nafter\n"

        assert strip_disabled_regions(text) == text

    def test_unclosed_region_is_left_unchanged(self) -> None:
        text = "%xprompts_enabled:false\n{{ missing }}\n"

        assert strip_disabled_regions(text) == text


class TestProcessXpromptReferencesDisabledRegions:
    """Integration: process_xprompt_references skips disabled region content."""

    @patch("sase.xprompt.processor.get_all_xprompts")
    def test_expansion_ensures_disabled_marker_at_line_start(
        self,
        mock_get_xprompts: MagicMock,
    ) -> None:
        """When xprompt expands to content starting with %xprompts_enabled:false
        and is mid-line (after an unexpanded ref), a newline is prepended."""
        from sase.xprompt.models import XPrompt
        from sase.xprompt.processor import process_xprompt_references

        mock_get_xprompts.return_value = {
            "fork_test": XPrompt(
                name="fork_test",
                content=(
                    "%xprompts_enabled:false\n"
                    "# Previous Conversation\n"
                    "some history\n"
                    "%xprompts_enabled:true\n"
                    "# New Query\n"
                ),
            ),
        }
        # Simulate: unexpanded VCS ref followed by #fork_test
        prompt = "#unknown_vcs:sase #fork_test"
        result = process_xprompt_references(prompt)
        # The %xprompts_enabled:false must be at a line start (after \n)
        idx = result.index("%xprompts_enabled:false")
        assert idx == 0 or result[idx - 1] == "\n"


class TestPreprocessPromptLateDisabledRegions:
    """Integration: preprocess_prompt_late strips markers and protects content."""

    @patch(
        "sase.file_references.process_command_substitution",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.file_references.format_with_prettier",
        side_effect=lambda x, **_kw: x,
    )
    @patch(
        "sase.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    @patch(
        "sase.file_references.validate_file_references",
    )
    def test_validate_mode_ignores_at_refs_in_disabled_region_inline_close(
        self,
        mock_validate: MagicMock,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        _mock_cmd_sub: MagicMock,
    ) -> None:
        """@refs inside disabled region with inline closing marker are not validated.

        Regression test: the validator must not see @i18n inside a
        %xprompts_enabled:false region whose closing marker is inline.
        """
        from sase.llm_provider.preprocessing import preprocess_prompt_late

        prompt = (
            "%xprompts_enabled:false\n"
            "use the @i18n attribute.\n"
            "use the @i18n attribute.\n"
            "consistency with the DRX grid system. %xprompts_enabled:true\n"
        )
        preprocess_prompt_late(prompt, file_ref_mode="validate")
        # validate_file_references should be called with prompt that has
        # no @i18n (the disabled region is replaced by a placeholder)
        assert mock_validate.called
        validated_text = mock_validate.call_args[0][0]
        assert "@i18n" not in validated_text

    @patch(
        "sase.file_references.process_command_substitution",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.file_references.format_with_prettier",
        side_effect=lambda x, **_kw: x,
    )
    @patch(
        "sase.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_markers_stripped_when_preceded_by_unexpanded_ref(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        _mock_cmd_sub: MagicMock,
    ) -> None:
        """Markers must be stripped even when preceded by unexpanded refs.

        Regression test: when an unexpanded VCS ref like #git:sase sits on the
        same line as %xprompts_enabled:false, the marker must still be stripped
        as long as it starts on its own line (after the newline fix in
        process_xprompt_references / embedded workflow expansion).
        """
        from sase.llm_provider.preprocessing import preprocess_prompt_late

        # After the newline fix, the prompt looks like:
        # #git:sase \n%xprompts_enabled:false\n...
        prompt = (
            "#git:sase \n"
            "%xprompts_enabled:false\n"
            "# Previous Conversation\n"
            "some history\n"
            "%xprompts_enabled:true\n"
            "# New Query\n"
        )
        result = preprocess_prompt_late(prompt, file_ref_mode="skip")
        assert "%xprompts_enabled" not in result
        assert "# Previous Conversation" in result
        assert "# New Query" in result

    @patch("sase.file_references.process_command_substitution")
    @patch(
        "sase.file_references.format_with_prettier",
        side_effect=lambda x, **_kw: x,
    )
    @patch(
        "sase.file_references.strip_html_comments",
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

    @patch(
        "sase.file_references.process_command_substitution",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.file_references.format_with_prettier",
        side_effect=lambda x, **_kw: x,
    )
    @patch(
        "sase.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_early_then_late_preserves_disabled_region_protection(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        _mock_cmd_sub: MagicMock,
    ) -> None:
        """Full two-phase pipeline must protect @refs inside disabled regions.

        Regression test: preprocess_prompt_early used to eagerly strip the
        %xprompts_enabled:false/true markers via extract_prompt_directives,
        which exposed @refs inside the region to validate_file_references in
        preprocess_prompt_late — triggering SystemExit on annotations like
        @Input that are not real files.
        """
        from sase.llm_provider.preprocessing import (
            preprocess_prompt_early,
            preprocess_prompt_late,
        )

        prompt = (
            "%xprompts_enabled:false\n"
            "Consider using more inclusive language for these new public"
            " @Input() fields.\n"
            "The getters should be marked with the '@visibleForTemplate'"
            " annotation.\n"
            "%xprompts_enabled:true\n"
        )
        early = preprocess_prompt_early(prompt)
        # Markers must survive the early phase so the late phase can protect
        # the enclosed @refs from validation.
        assert "%xprompts_enabled:false" in early.prompt
        assert "%xprompts_enabled:true" in early.prompt

        # Late phase with file_ref_mode="validate" must NOT raise SystemExit
        # because the @refs are inside a protected disabled region.
        result = preprocess_prompt_late(early.prompt, file_ref_mode="validate")

        # Final output has the markers stripped by preprocess_prompt_late.
        assert "%xprompts_enabled" not in result
