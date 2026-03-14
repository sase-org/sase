"""Tests for prompt directive extraction (%name tag system)."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    PromptDirectives,
    extract_prompt_directives,
    has_wait_directive,
    split_prompt_for_models,
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


# --- Duplicate directive error ---


# --- Edge cases ---


# --- Alias tests ---


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


# --- %name directive tests ---


# --- %wait directive tests ---


def test_approve_bare() -> None:
    """%approve (bare) sets approve=True."""
    prompt = "%approve\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_plus() -> None:
    """%approve+ sets approve=True."""
    prompt = "%approve+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_alias() -> None:
    """%a (alias) sets approve=True."""
    prompt = "%a\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_default_false() -> None:
    """Default approve is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.approve is False


def test_approve_with_other_directives() -> None:
    """%approve combined with %model works."""
    prompt = "%approve\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True
    assert directives.model == "opus"


def test_approve_duplicate_raises() -> None:
    """Duplicate %approve raises DirectiveError."""
    prompt = "%approve\n%approve\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%approve'"):
        extract_prompt_directives(prompt)


def test_wait_directive_multiple() -> None:
    """Two %wait lines yield wait=['a', 'b']."""
    prompt = "%wait:a\n%wait:b\nDo some work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do some work"
    assert directives.wait == ["a", "b"]


def test_name_bare_auto_generates() -> None:
    """Bare %name auto-generates a name via get_next_auto_name()."""
    prompt = "%name\nDo work"
    with patch(
        "sase.agent_names.get_next_auto_name",
        return_value="a",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "a"


def test_name_bare_alias_auto_generates() -> None:
    """Bare %n auto-generates a name."""
    prompt = "%n\nDo work"
    with patch(
        "sase.agent_names.get_next_auto_name",
        return_value="b",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"


def test_wait_bare_resolves_to_previous_agent() -> None:
    """Bare %wait resolves to the most recently named previous agent."""
    prompt = "%name:foo\n%wait\nDo work"
    with patch(
        "sase.agent_names.get_most_recent_agent_name",
        return_value="prev",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.wait == ["prev"]


def test_wait_bare_with_bare_name_does_not_self_wait() -> None:
    """Bare %wait + bare %name does NOT wait for itself."""
    prompt = "%name\n%wait\nDo work"
    with (
        patch(
            "sase.agent_names.get_next_auto_name",
            return_value="b",
        ),
        patch(
            "sase.agent_names.get_most_recent_agent_name",
            return_value="a",
        ),
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"
    assert directives.wait == ["a"]


def test_wait_bare_no_previous_agent_raises() -> None:
    """Bare %wait with no previously named agent raises DirectiveError."""
    prompt = "%wait\nDo work"
    with patch(
        "sase.agent_names.get_most_recent_agent_name",
        return_value=None,
    ):
        with pytest.raises(DirectiveError, match="no previously.*named agent"):
            extract_prompt_directives(prompt)


def test_wait_mixed_bare_and_explicit() -> None:
    """Mix of bare and explicit %wait works."""
    prompt = "%name:foo\n%wait:bar\n%wait\nDo work"
    with patch(
        "sase.agent_names.get_most_recent_agent_name",
        return_value="prev",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["bar", "prev"]


# --- %plan directive tests ---


def test_plan_bare() -> None:
    """%plan (bare) sets plan=True."""
    prompt = "%plan\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_plus() -> None:
    """%plan+ sets plan=True."""
    prompt = "%plan+\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_alias() -> None:
    """%p (alias) sets plan=True."""
    prompt = "%p\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_default_false() -> None:
    """Default plan is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.plan is False


def test_plan_with_approve() -> None:
    """%plan combined with %approve both work together."""
    prompt = "%plan\n%approve\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True
    assert directives.approve is True


def test_plan_duplicate_raises() -> None:
    """Duplicate %plan raises DirectiveError."""
    prompt = "%plan\n%plan\nFix the bug"
    with pytest.raises(DirectiveError, match="Duplicate directive '%plan'"):
        extract_prompt_directives(prompt)


# --- %hide directive tests ---


def test_hide_bare() -> None:
    """%hide (bare) sets hide=True."""
    prompt = "%hide\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_plus() -> None:
    """%hide+ sets hide=True."""
    prompt = "%hide+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_alias() -> None:
    """%h (alias) sets hide=True."""
    prompt = "%h\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_default_false() -> None:
    """Default hide is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.hide is False


def test_hide_with_other_directives() -> None:
    """%hide combined with %model works."""
    prompt = "%hide\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True
    assert directives.model == "opus"


def test_hide_duplicate_raises() -> None:
    """Duplicate %hide raises DirectiveError."""
    prompt = "%hide\n%hide\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%hide'"):
        extract_prompt_directives(prompt)


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


# --- has_wait_directive tests ---


def test_has_wait_directive_colon() -> None:
    """Detects %wait:name syntax."""
    assert has_wait_directive("Do something %wait:faster") is True


def test_has_wait_directive_alias() -> None:
    """Detects %w:name shorthand."""
    assert has_wait_directive("Do something %w:faster") is True


def test_has_wait_directive_paren() -> None:
    """Detects %wait(name) syntax."""
    assert has_wait_directive("Do something %wait(faster)") is True


def test_has_wait_directive_plus() -> None:
    """Detects %wait+ and %w+ syntax."""
    assert has_wait_directive("Do something %wait+") is True
    assert has_wait_directive("Do something %w+") is True


def test_has_wait_directive_start_of_line() -> None:
    """Detects %wait at start of line."""
    assert has_wait_directive("%wait:faster\nDo something") is True


def test_has_wait_directive_absent() -> None:
    """Returns False when no %wait directive present."""
    assert has_wait_directive("Do something %model:opus") is False


def test_has_wait_directive_bare() -> None:
    """Detects bare %wait (no argument)."""
    assert has_wait_directive("%wait\nDo something") is True
    assert has_wait_directive("Do something %wait") is True
    assert has_wait_directive("Do something %w\nmore") is True


def test_has_wait_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_wait_directive("Just a plain prompt") is False


# --- split_prompt_for_models tests ---


def test_split_prompt_for_models_two_models() -> None:
    """Two models produce two prompts, each with a single %model directive."""
    prompt = "%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:opus\nReview this code"
    assert result[1] == "%model:sonnet\nReview this code"


def test_split_prompt_for_models_three_models() -> None:
    """Three models produce three prompts."""
    prompt = "%model(opus,sonnet,haiku)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%model:opus\nDo work"
    assert result[1] == "%model:sonnet\nDo work"
    assert result[2] == "%model:haiku\nDo work"


def test_split_prompt_for_models_single_model_returns_none() -> None:
    """Single model in parens returns None (not multi-model)."""
    assert split_prompt_for_models("%m(opus)\nDo work") is None


def test_split_prompt_for_models_no_directive_returns_none() -> None:
    """No model directive returns None."""
    assert split_prompt_for_models("Just a prompt") is None


def test_split_prompt_for_models_colon_syntax_returns_none() -> None:
    """Colon syntax is single model, returns None."""
    assert split_prompt_for_models("%m:opus\nDo work") is None


def test_split_prompt_for_models_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%approve\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%approve\n%model:opus\nReview this code"
    assert result[1] == "%approve\n%model:sonnet\nReview this code"


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


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%m(codex/o3,claude/opus)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:codex/o3\nReview this code"
    assert result[1] == "%model:claude/opus\nReview this code"


def test_split_prompt_for_models_spaces_in_args() -> None:
    """Spaces around model names in args are handled."""
    prompt = "%m(opus, sonnet)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:opus\nDo work"
    assert result[1] == "%model:sonnet\nDo work"


def test_split_prompt_for_models_after_xprompt_expansion() -> None:
    """Xprompt-expanded %m(...) is correctly split by split_prompt_for_models."""
    from sase.xprompt.processor import process_xprompt_references

    # Simulate what happens when #swarm expands to %m(opus,sonnet)
    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        wraps=process_xprompt_references,
    ):
        expanded = "%m(opus,sonnet)\nReview this code"
        result = split_prompt_for_models(expanded)
        assert result is not None
        assert len(result) == 2
        assert result[0] == "%model:opus\nReview this code"
        assert result[1] == "%model:sonnet\nReview this code"
