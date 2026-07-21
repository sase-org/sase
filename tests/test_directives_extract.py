"""Tests for extract_prompt_directives() core behavior, edge cases, and protection."""

import re
from types import MappingProxyType
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


@pytest.mark.parametrize(
    ("source", "model", "overrides"),
    [
        ("%m(opus, coder=sonnet)", "opus", {"coder": "sonnet"}),
        ("%m(coder=sonnet)", None, {"coder": "sonnet"}),
        (
            "%m(opus@high, coder=@medium_phase_worker)",
            "opus",
            {"coder": "@medium_phase_worker"},
        ),
        (
            '%model(claude/models/opus, coder="provider/model with spaces")',
            "claude/models/opus",
            {"coder": "provider/model with spaces"},
        ),
    ],
)
def test_model_directive_alias_overrides_are_parsed(
    source: str,
    model: str | None,
    overrides: dict[str, str],
) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nReview")

    assert cleaned == "Review"
    assert directives.model == model
    assert dict(directives.model_alias_overrides) == overrides
    assert isinstance(directives.model_alias_overrides, MappingProxyType)
    if "@high" in source:
        assert directives.reasoning_effort == "high"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("%m(opus, foo=sonnet)", "Unknown model alias 'foo'"),
        ("%m(opus, @coder=sonnet)", "keys are bare"),
        (
            "%m(opus, coder=medium_phase_worker)",
            "did you mean @medium_phase_worker",
        ),
        ("%m(opus, coder=@missing)", "is not a known model alias"),
        ("%m(opus, coder=sonnet@high)", "cannot set reasoning effort"),
        ("%m(opus, coder=)", "requires a model value"),
        ("%m(opus, coder=a, coder=b)", "Duplicate keyword argument 'coder'"),
        ("%m:coder=sonnet", "require the parenthesized form"),
        ("%m(opus, coder=@coder)", "cannot reference itself"),
    ],
)
def test_model_directive_alias_override_validation(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=re.escape(message)):
        extract_prompt_directives(f"{source}\nReview")


def test_model_directive_alias_kwargs_do_not_count_as_positional_models() -> None:
    with pytest.raises(DirectiveError, match=r"%m\(opus, sonnet, coder=haiku\)"):
        extract_prompt_directives("%m(opus, sonnet, coder=haiku)\nReview")


def test_model_directive_alias_override_expands_xprompt_reference() -> None:
    with patch(
        "sase.xprompt.directives.process_xprompt_references",
        return_value="sonnet",
    ) as process:
        _, directives = extract_prompt_directives("%m(opus, coder=#fast)\nReview")

    assert dict(directives.model_alias_overrides) == {"coder": "sonnet"}
    process.assert_called_once_with("#fast")


@pytest.mark.parametrize("directive", ["%model", "%m"])
def test_model_directive_quoted_paren_provider_model_with_spaces_and_parens(
    directive: str,
) -> None:
    """Quoted paren args preserve exact provider/model values."""
    prompt = f'{directive}("agy/Gemini 3.5 Flash (High)")\nReview this code'
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.model == "agy/Gemini 3.5 Flash (High)"


def test_model_directive_paren_multi_arg_rejected() -> None:
    """Multi-argument %model(...) raises with the migration syntax."""
    prompt = "%model(opus,sonnet)\nReview this code"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        extract_prompt_directives(prompt)


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


def test_model_colon_arg_with_comma_is_single_value() -> None:
    """Single-value %model:a,b keeps the whole string and leaves no stray text."""
    prompt = "%model:a,b\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.model == "a,b"


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


def test_model_alias_requires_at_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "other": {
                        "model": "claude/opus",
                        "description": "Other model.",
                    }
                }
            }
        },
    )

    _, directives = extract_prompt_directives("%m:@other\nReview")

    assert directives.model == "other"


def test_model_bare_alias_raises_with_migration_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "other": {
                        "model": "claude/opus",
                        "description": "Other model.",
                    }
                }
            }
        },
    )

    with pytest.raises(
        DirectiveError,
        match=r"Model aliases must be prefixed with @ .* did you mean @other",
    ):
        extract_prompt_directives("%m:other\nReview")


def test_model_role_alias_requires_at_prefix() -> None:
    _, directives = extract_prompt_directives("%m:@medium_phase_worker\nReview")
    assert directives.model == "medium_phase_worker"

    with pytest.raises(
        DirectiveError,
        match=(
            r"Model aliases must be prefixed with @ .* "
            r"did you mean @medium_phase_worker"
        ),
    ):
        extract_prompt_directives("%m:medium_phase_worker\nReview")


def test_model_retired_worker_alias_is_not_known() -> None:
    """``@worker`` was retired in epic sase-5d phase 4 and no longer resolves."""
    with pytest.raises(
        DirectiveError,
        match=r"'@worker' is not a known model alias",
    ):
        extract_prompt_directives("%m:@worker\nReview")


def test_model_retired_phase_worker_alias_is_not_known() -> None:
    with pytest.raises(
        DirectiveError,
        match=r"'@phase_worker' is not a known model alias",
    ):
        extract_prompt_directives("%m:@phase_worker\nReview")


def test_model_custom_phase_worker_alias_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "phase_worker": {
                        "model": "claude/sonnet",
                        "description": "Explicit custom phase role.",
                    }
                }
            }
        },
    )

    _, directives = extract_prompt_directives("%m:@phase_worker\nReview")
    assert directives.model == "phase_worker"


@pytest.mark.parametrize("model", ["opus", "claude/opus"])
def test_model_at_prefix_on_non_alias_raises(model: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=rf"'@{re.escape(model)}' is not a known model alias",
    ):
        extract_prompt_directives(f"%m:@{model}\nReview")


def test_model_alias_prefix_composes_with_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "other": {
                        "model": "claude/opus",
                        "description": "Other model.",
                    }
                }
            }
        },
    )

    _, directives = extract_prompt_directives("%m:@other@xhigh\nReview")

    assert directives.model == "other"
    assert directives.reasoning_effort == "xhigh"


def test_model_literal_bypasses_alias_prefix_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "other": {
                        "model": "claude/opus",
                        "description": "Other model.",
                    }
                }
            }
        },
    )

    _, directives = extract_prompt_directives("%model:`@other`\nReview")

    assert directives.model == "@other"


def test_model_alias_prefix_strips_before_xprompt_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "agy_flash": {
                        "model": "agy/Gemini 3.5 Flash (High)",
                        "description": "Antigravity flash preset.",
                    }
                }
            }
        },
    )

    with patch("sase.xprompt.directives.process_xprompt_references") as mock_process:
        mock_process.return_value = "agy_flash"
        _, directives = extract_prompt_directives("%m:@#agy\nReview")

    assert directives.model == "agy_flash"
    mock_process.assert_called_once_with("#agy")


# --- Unknown directives ---


def test_unknown_directive_left_in_prompt() -> None:
    """Unknown %id patterns are left in the prompt unchanged."""
    prompt = "%unknown:foo\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "%unknown:foo\nRest of prompt"
    assert directives == PromptDirectives()


# --- Alias / edge case tests ---


def test_alias_m_and_model_duplicate_rejected() -> None:
    """%m + %model in the same prompt is duplicate model misuse."""
    prompt = "%m:opus\n%model:sonnet\nPrompt text"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        extract_prompt_directives(prompt)


def test_identical_duplicate_model_directives_rejected() -> None:
    """Two %model:opus directives are duplicate model misuse."""
    prompt = "%model:opus\n%model:opus\nPrompt text"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:opus\} instead",
    ):
        extract_prompt_directives(prompt)


def test_raw_alt_model_branches_are_not_top_level_model_metadata() -> None:
    """Raw model branches inside %{...} are ignored until fan-out splitting."""
    prompt = "%{%m:opus | %m:sonnet}\nPrompt text"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.model is None


def test_duplicate_non_model_directive_still_raises() -> None:
    """Non-model duplicate directives continue to raise DirectiveError."""
    prompt = "%hide\n%hide\nPrompt text"
    with pytest.raises(DirectiveError, match="Duplicate directive '%hide'"):
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


# --- tribe= keyword on %id ---


def test_id_tribe_keyword_with_explicit_id() -> None:
    prompt = "%id(reviewer, tribe=review)\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.name == "reviewer"
    assert directives.name_explicit is True
    assert directives.tribe == "review"


def test_id_tribe_keyword_accepts_dotted_bead_id() -> None:
    prompt = "%id(reviewer, tribe=sase-42.3)\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.tribe == "sase-42.3"


def test_id_tribe_keyword_without_id_auto_names() -> None:
    with patch("sase.agent.names.get_next_auto_name", return_value="auto7"):
        cleaned, directives = extract_prompt_directives("%id(tribe=exp)\nFix the bug")

    assert cleaned == "Fix the bug"
    assert directives.name == "auto7"
    assert directives.name_explicit is False
    assert directives.tribe == "exp"


def test_id_tribe_keyword_supports_force_reuse() -> None:
    prompt = "%id(!reviewer, tribe=release)\nFix"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix"
    assert directives.name == "reviewer"
    assert directives.name_force_reuse is True
    assert directives.tribe == "release"


def test_id_tribe_keyword_rejects_at_prefix() -> None:
    with pytest.raises(DirectiveError, match="must not start with '@'"):
        extract_prompt_directives('%id(reviewer, tribe="@review")\nDo it')


def test_id_tribe_keyword_rejects_invalid_chars() -> None:
    with pytest.raises(DirectiveError, match="must match"):
        extract_prompt_directives('%id(reviewer, tribe="has space")\nDo it')


def test_id_tribe_keyword_empty_is_error() -> None:
    with pytest.raises(DirectiveError, match="requires a non-empty tribe name"):
        extract_prompt_directives("%id(tribe=)\nDo it")


@pytest.mark.parametrize("source", ["%tribe:review", "%t:review", "%tribe(review)"])
def test_removed_tribe_directives_raise_migration_error(source: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"%tribe.*%t.*removed.*%id\(tribe=<tribe>\).*#tribe",
    ):
        extract_prompt_directives(f"{source}\nDo it")


def test_tribe_directive_default_none() -> None:
    """When ``%tribe`` is not present, directives.tribe is None."""
    _, directives = extract_prompt_directives("Just a prompt")
    assert directives.tribe is None


def test_legacy_tag_directive_left_in_prompt() -> None:
    """``%tag:<name>`` is no longer a directive — left in the prompt unchanged."""
    prompt = "%tag:foo\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "%tag:foo\nRest of prompt"
    assert directives.tribe is None


def test_group_directive_and_g_alias_are_removed() -> None:
    """The old group spellings are left in the prompt unchanged."""
    prompt = "%group:review\n%g:exp\nRest of prompt"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.tribe is None
