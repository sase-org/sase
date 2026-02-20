"""Tests for prompt directive extraction (%name tag system)."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


# --- Pattern matching tests ---


def test_no_directives_passthrough() -> None:
    """Prompt without % is returned unchanged."""
    prompt = "Just a normal prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_no_percent_fast_path() -> None:
    """Prompt without any % character takes the fast path."""
    prompt = "No percent sign here"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "No percent sign here"
    assert directives.model is None


def test_simple_model_directive() -> None:
    """Test %model:value colon syntax."""
    prompt = "%model:sonnet\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "sonnet"


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


def test_plain_arg_no_xprompt_expansion() -> None:
    """Test that args without # skip xprompt expansion."""
    prompt = "%model:sonnet\nHello"

    with patch(
        "sase.xprompt.directives.process_xprompt_references",
    ) as mock_process:
        cleaned, directives = extract_prompt_directives(prompt)

    # Should NOT call process_xprompt_references for args without #
    mock_process.assert_not_called()
    assert directives.model == "sonnet"


# --- Unknown directives ---


def test_unknown_directive_left_in_prompt() -> None:
    """Unknown %name patterns are left in the prompt unchanged."""
    prompt = "%unknown:foo\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "%unknown:foo\nRest of prompt"
    assert directives == PromptDirectives()


def test_unknown_and_known_directives_mixed() -> None:
    """Known directives are extracted; unknown ones stay."""
    prompt = "%model:opus\n%unknown:bar\nPrompt text"
    cleaned, directives = extract_prompt_directives(prompt)
    assert "%unknown:bar" in cleaned
    assert "Prompt text" in cleaned
    assert directives.model == "opus"


# --- Duplicate directive error ---


def test_duplicate_known_directive_raises() -> None:
    """Duplicate known directives raise DirectiveError."""
    prompt = "%model:opus\n%model:sonnet\nPrompt text"
    with pytest.raises(DirectiveError, match="Duplicate directive '%model'"):
        extract_prompt_directives(prompt)


# --- Edge cases ---


def test_directive_mid_line() -> None:
    """Directive after whitespace mid-line is still matched."""
    prompt = "text %model:opus\nMore text"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "opus"
    assert "text" in cleaned
    assert "More text" in cleaned


def test_directive_with_dots_in_arg() -> None:
    """Colon args can contain dots (e.g., model names)."""
    prompt = "%model:gemini-2.5-flash\nPrompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "gemini-2.5-flash"
    assert cleaned == "Prompt"


def test_directive_with_slash_in_arg() -> None:
    """Colon args can contain slashes (e.g., namespace/model)."""
    prompt = "%model:google/gemini-2.5-flash\nPrompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "google/gemini-2.5-flash"
    assert cleaned == "Prompt"


def test_empty_prompt() -> None:
    """Empty prompt returns empty with default directives."""
    cleaned, directives = extract_prompt_directives("")
    assert cleaned == ""
    assert directives == PromptDirectives()


# --- Alias tests ---


def test_alias_m_resolves_to_model() -> None:
    """%m:sonnet works the same as %model:sonnet."""
    prompt = "%m:sonnet\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "sonnet"


def test_alias_m_no_arg_yields_none() -> None:
    """%m with no argument yields model=None."""
    prompt = "%m\nSome prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Some prompt"
    assert directives.model is None


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


# --- Escape sequence tests (%%name → %name) ---


def test_double_percent_known_directive_not_extracted() -> None:
    """%%model is not extracted as a directive; unescaped to %model in output."""
    prompt = "%%model:sonnet\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model is None
    assert "%model:sonnet" in cleaned
    assert "Rest of prompt" in cleaned


def test_double_percent_unknown_preserved_as_single() -> None:
    """%%unknown is unescaped to %unknown in the output."""
    prompt = "%%unknown\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "%unknown\nRest of prompt"
    assert directives == PromptDirectives()


def test_double_percent_with_known_directive_still_works() -> None:
    """%%escaped is unescaped while real %model directive is still extracted."""
    prompt = "%model:opus\n%%model:sonnet in the prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.model == "opus"
    assert "%model:sonnet in the prompt" in cleaned
