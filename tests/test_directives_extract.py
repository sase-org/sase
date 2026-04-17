"""Tests for extract_prompt_directives() core behavior, edge cases, and protection."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    PromptDirectives,
    extract_prompt_directives,
)


# --- Pattern matching tests ---


def test_no_directives_passthrough() -> None:
    """Prompt without % is returned unchanged."""
    prompt = "Just a normal prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_model_directive_backtick_arg() -> None:
    """Test %model:`value` backtick syntax."""
    prompt = "%model:`claude-sonnet-4-20250514`\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "claude-sonnet-4-20250514"


def test_model_directive_paren_arg() -> None:
    """Test %model(value) parenthesis syntax."""
    prompt = "%model(opus)\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "opus"


def test_model_directive_plus_syntax() -> None:
    """Test %model+ syntax (sets arg to 'true')."""
    prompt = "%model+\nSome prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Some prompt"
    assert directives.model == "true"


def test_model_directive_no_arg() -> None:
    """Test %model with no argument yields model=None."""
    prompt = "%model\nSome prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Some prompt"
    assert directives.model is None


# --- Xprompt expansion in directive args ---


def test_xprompt_ref_in_directive_arg() -> None:
    """Test that #xprompt references in directive args are expanded."""
    prompt = "%model:#gemini_small_model\nReview this code"

    with patch(
        "sase.xprompt.directives.process_xprompt_references",
    ) as mock_process:
        mock_process.return_value = "gemini-2.5-flash"
        cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Review this code"
    assert directives.model == "gemini-2.5-flash"
    mock_process.assert_called_once_with("#gemini_small_model")


# --- Unknown directives ---


def test_unknown_directive_left_in_prompt() -> None:
    """Unknown %name patterns are left in the prompt unchanged."""
    prompt = "%unknown:foo\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "%unknown:foo\nRest of prompt"
    assert directives == PromptDirectives()


# --- Alias / edge case tests ---


def test_alias_m_and_model_duplicate_raises() -> None:
    """%m + %model in the same prompt raises DirectiveError."""
    prompt = "%m:opus\n%model:sonnet\nPrompt text"
    with pytest.raises(DirectiveError, match="Duplicate directive '%model'"):
        extract_prompt_directives(prompt)


def test_percent_in_normal_text_not_matched() -> None:
    """Percent signs in normal text (not followed by name) are left alone."""
    prompt = "Use 50% of the data"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Use 50% of the data"
    assert directives == PromptDirectives()


# --- Model provider syntax tests ---


def test_model_directive_colon_provider_syntax() -> None:
    """Test %model:codex/o3 provider/model syntax in colon arg."""
    prompt = "%model:codex/o3\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "codex/o3"


def test_model_directive_colon_provider_syntax_aliases() -> None:
    """Test %m:claude/opus alias with provider/model syntax."""
    prompt = "%m:claude/opus\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "claude/opus"


# --- Fenced code block protection tests ---


def test_directive_inside_fenced_block_ignored() -> None:
    """%model:opus inside triple backticks is not extracted."""
    prompt = "```\n%model:opus\n```"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_directive_inside_quadruple_backtick_block_ignored() -> None:
    """%model:opus inside quadruple backticks is not extracted."""
    prompt = "````\n%model:opus\n````"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_directive_outside_fenced_block_still_extracted() -> None:
    """%model:opus outside code blocks still works when code blocks are present."""
    prompt = "%model:opus\n```\nsome code\n```\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "opus"
    assert "```\nsome code\n```" in cleaned
    assert "%model" not in cleaned


# --- Disabled region protection tests ---


def test_directive_inside_disabled_region_ignored() -> None:
    """%model inside disabled region is not extracted."""
    prompt = (
        "%model:new_model\n"
        "%xprompts_enabled:false\n"
        "old prompt %model:old_model\n"
        "%xprompts_enabled:true\n"
        "Rest of prompt"
    )
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "new_model"
    assert "%model:new_model" not in cleaned
    assert "old prompt %model:old_model" in cleaned
    assert "Rest of prompt" in cleaned


def test_only_directive_inside_disabled_region_extracts_nothing() -> None:
    """%model only inside disabled region -> no model directive."""
    prompt = (
        "%xprompts_enabled:false\n"
        "old prompt %model:old_model\n"
        "%xprompts_enabled:true\n"
        "Rest of prompt"
    )
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model is None
    assert "old prompt %model:old_model" in cleaned


def test_disabled_region_markers_stripped_from_output() -> None:
    """Disabled region markers are removed from cleaned output."""
    prompt = (
        "%xprompts_enabled:false\nsome content\n%xprompts_enabled:true\nRest of prompt"
    )
    cleaned, _ = extract_prompt_directives(prompt)
    assert "%xprompts_enabled" not in cleaned
    assert "some content" in cleaned


def test_disabled_region_markers_preserved_when_flag_false() -> None:
    """With strip_disabled_markers=False, markers remain in the cleaned output.

    This path is used by preprocess_prompt_early so that preprocess_prompt_late
    can still protect the disabled region contents from later pipeline steps.
    """
    prompt = (
        "%model:opus\n"
        "%xprompts_enabled:false\n"
        "some @Input content\n"
        "%xprompts_enabled:true\n"
        "Rest of prompt"
    )
    cleaned, directives = extract_prompt_directives(
        prompt, strip_disabled_markers=False
    )
    assert directives.model == "opus"
    assert "%xprompts_enabled:false" in cleaned
    assert "%xprompts_enabled:true" in cleaned
    assert "some @Input content" in cleaned
    assert "Rest of prompt" in cleaned
