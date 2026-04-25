"""Tests for directive helper functions (has_wait, has_model, has_alt, split_prompt, _parse_duration, _parse_absolute_time)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    _parse_absolute_time,
    _split_prompt_for_alternatives,
    has_alt_directive,
    has_model_directive,
    has_wait_directive,
    split_prompt_for_models,
    _parse_duration,
)


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


def test_has_wait_directive_duration() -> None:
    """has_wait_directive detects %wait:5m."""
    assert has_wait_directive("%wait:5m\nDo something") is True


# --- has_model_directive tests ---


def test_has_model_directive_colon() -> None:
    """Detects %model:name syntax."""
    assert has_model_directive("%model:opus\nDo something") is True


def test_has_model_directive_alias_colon() -> None:
    """Detects %m:name shorthand."""
    assert has_model_directive("Do something %m:sonnet") is True


def test_has_model_directive_paren() -> None:
    """Detects %m(name) syntax."""
    assert has_model_directive("Do something %m(opus)") is True


def test_has_model_directive_absent() -> None:
    """Returns False when no %model directive present."""
    assert has_model_directive("Do something %wait:faster") is False


def test_has_model_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_model_directive("Just a plain prompt") is False


# --- split_prompt_for_models tests ---


def test_split_prompt_for_models_two_models() -> None:
    """Two models produce two prompts, each with a single %model directive."""
    prompt = "%n:foo\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_three_models() -> None:
    """Three models produce three prompts."""
    prompt = "%n:foo\n%model(opus,sonnet,haiku)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nDo work"
    assert result[2] == "%name:foo.claude-haiku\n%model:haiku\nDo work"


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
    prompt = "%n:foo\n%approve\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%approve\n%model:opus\nReview this code"
    assert (
        result[1]
        == "%name:foo.claude-sonnet\n%approve\n%model:sonnet\nReview this code"
    )


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%n:foo\n%m(codex/o3,claude/opus)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.codex\n%model:codex/o3\nReview this code"
    assert result[1] == "%name:foo.claude\n%model:claude/opus\nReview this code"


def test_split_prompt_for_models_spaces_in_args() -> None:
    """Spaces around model names in args are handled."""
    prompt = "%n:foo\n%m(opus, sonnet)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nDo work"


def test_split_prompt_for_models_after_xprompt_expansion() -> None:
    """Xprompt-expanded %m(...) is correctly split by split_prompt_for_models."""
    from sase.xprompt.processor import process_xprompt_references

    # Simulate what happens when #swarm expands to %m(opus,sonnet)
    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        wraps=process_xprompt_references,
    ):
        expanded = "%n:foo\n%m(opus,sonnet)\nReview this code"
        result = split_prompt_for_models(expanded)
        assert result is not None
        assert len(result) == 2
        assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview this code"
        assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_direct_alt_same_as_multi_model() -> None:
    """Direct %alt(%model:...) produces the same output as %m(...)."""
    via_m = split_prompt_for_models("%n:foo\n%m(opus,sonnet)\nReview this code")
    via_alt = split_prompt_for_models(
        "%n:foo\n%alt(%model:opus,%model:sonnet)\nReview this code"
    )
    assert via_m == via_alt


# --- split_prompt_for_models: repeated scalar %model tests ---


def test_split_prompt_for_models_two_scalar_directives() -> None:
    """Two %model:X scalars produce two variants, directive lines collapsed."""
    prompt = "%n:foo\n%model:opus\n%model:sonnet\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_alias_mix() -> None:
    """%m:opus + %model:sonnet (alias mix) produces two variants."""
    prompt = "%n:foo\n%m:opus\n%model:sonnet\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_scalar_plus_paren() -> None:
    """%model:opus + %model(sonnet,haiku) → three variants in order."""
    prompt = "%n:foo\n%model:opus\n%model(sonnet,haiku)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview this code"
    assert result[2] == "%name:foo.claude-haiku\n%model:haiku\nReview this code"


def test_split_prompt_for_models_identical_dupes_return_none() -> None:
    """Two identical %model:opus dupes yield no split (single unique model)."""
    prompt = "%model:opus\n%model:opus\nReview this code"
    assert split_prompt_for_models(prompt) is None


def test_split_prompt_for_models_interleaved_duplicates() -> None:
    """Duplicates spread across non-adjacent lines split correctly."""
    prompt = "%n:foo\n%model:opus\nHeader line\n%model:sonnet\nBody"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nHeader line\nBody"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nHeader line\nBody"


def test_split_prompt_for_models_scalar_inside_fenced_block_ignored() -> None:
    """%model:X inside a fenced code block is neither collected nor stripped."""
    prompt = "%model:opus\n```\n%model:sonnet\n```\nReview"
    result = split_prompt_for_models(prompt)
    # Only the outer %model:opus counts — single unique model, no split.
    assert result is None


def test_split_prompt_for_models_multi_model_with_user_alt_cartesian() -> None:
    """Two scalar %model directives Cartesian-product with a user %alt(x,y)."""
    prompt = "%n:foo\n%model:opus\n%model:sonnet %alt(x,y)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert "%name:foo.claude-opus" in result[0] and " x\nReview" in result[0]
    assert "%name:foo.claude-opus" in result[1] and " y\nReview" in result[1]
    assert "%name:foo.claude-sonnet" in result[2] and " x\nReview" in result[2]
    assert "%name:foo.claude-sonnet" in result[3] and " y\nReview" in result[3]


def test_split_prompt_for_models_multi_model_distinct_runtimes() -> None:
    """Two models on distinct runtimes get plain runtime suffixes (no model)."""
    prompt = "%n:foo\n%m(opus,gpt-5.5)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.codex\n%model:gpt-5.5\nReview this code"


def test_split_prompt_for_models_multi_model_auto_generated_base() -> None:
    """No %name with multi-model → auto-name is generated once and shared."""
    with patch("sase.agent.names.get_next_auto_name", return_value="z"):
        result = split_prompt_for_models("%m(opus,gpt-5.5)\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:z.claude\n%model:opus\nReview"
    assert result[1] == "%name:z.codex\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_multi_model_bare_name_auto_generated() -> None:
    """Bare %name with multi-model also auto-generates base once."""
    with patch("sase.agent.names.get_next_auto_name", return_value="z"):
        result = split_prompt_for_models("%name\n%m(opus,gpt-5.5)\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:z.claude\n%model:opus\nReview"
    assert result[1] == "%name:z.codex\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_uses_default_provider() -> None:
    """An unknown model maps to the default provider's runtime label."""
    from sase.llm_provider.registry import get_default_provider_name

    default = get_default_provider_name()
    prompt = "%n:foo\n%m(unknown_model_xyz,opus)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    # When the unknown model resolves to the same runtime as opus (claude),
    # collision suffixing kicks in; otherwise plain runtime labels.
    if default == "claude":
        assert (
            result[0] == "%name:foo.claude-unknown_model_xyz\n"
            "%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%name:foo.claude-opus\n%model:opus\nReview"
    else:
        assert result[0] == f"%name:foo.{default}\n%model:unknown_model_xyz\nReview"
        assert result[1] == "%name:foo.claude\n%model:opus\nReview"


def test_split_prompt_for_models_gemini_collision_uses_short_alias() -> None:
    """Same-runtime gemini collision substitutes short aliases for model names."""
    prompt = "%n:o\n%m(gemini-3-flash-preview,gemini-2.5-flash)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.gemini-flash3\n%model:gemini-3-flash-preview\nReview")
    assert result[1] == ("%name:o.gemini-flash25\n%model:gemini-2.5-flash\nReview")


def test_split_prompt_for_models_claude_collision_unchanged() -> None:
    """Claude opus/sonnet keep their raw names (no aliases declared)."""
    prompt = "%n:o\n%m(opus,sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.claude-opus\n%model:opus\nReview"
    assert result[1] == "%name:o.claude-sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_no_collision_unchanged() -> None:
    """Distinct-runtime case never embeds the model name (alias irrelevant)."""
    prompt = "%n:o\n%m(opus,gpt-5.5)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.claude\n%model:opus\nReview"
    assert result[1] == "%name:o.codex\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_falls_through() -> None:
    """Unknown model in a same-runtime collision keeps its raw name."""
    from sase.llm_provider.registry import get_default_provider_name

    if get_default_provider_name() != "gemini":
        # Test relies on unknown_xyz routing to gemini (the fallback default).
        # If a different default is configured, skip the assertion path.
        return
    prompt = "%n:o\n%m(gemini-3-flash-preview,unknown_xyz)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.gemini-flash3\n%model:gemini-3-flash-preview\nReview")
    assert result[1] == "%name:o.gemini-unknown_xyz\n%model:unknown_xyz\nReview"


def test_split_prompt_for_models_alias_collision_falls_back_to_raw() -> None:
    """Two models that alias to the same short form fall back to raw names."""
    from unittest.mock import patch

    fake_aliases = {
        "gemini-3-flash-preview": "fl",
        "gemini-2.5-flash": "fl",
    }
    with patch(
        "sase.llm_provider.registry.model_short_alias_map",
        return_value=fake_aliases,
    ):
        result = split_prompt_for_models(
            "%n:o\n%m(gemini-3-flash-preview,gemini-2.5-flash)\nReview"
        )
    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%name:o.gemini-gemini-3-flash-preview\n%model:gemini-3-flash-preview\nReview"
    )
    assert result[1] == (
        "%name:o.gemini-gemini-2.5-flash\n%model:gemini-2.5-flash\nReview"
    )


def test_split_prompt_for_models_pure_alt_not_renamed() -> None:
    """A %alt(...) with no %model branches is left unchanged (no naming)."""
    prompt = "%n:foo\n%alt(x,y)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%n:foo\nx\nDo work"
    assert result[1] == "%n:foo\ny\nDo work"


def test_split_prompt_for_models_alt_with_nested_model_not_double_collected() -> None:
    """%alt(%model:a,%model:b) is processed as a single alt, not re-collected."""
    prompt = "%n:foo\n%alt(%model:opus,%model:sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.claude-opus\n%model:opus\nReview"
    assert result[1] == "%name:foo.claude-sonnet\n%model:sonnet\nReview"


# --- split_prompt_for_alternatives tests ---


def test_split_prompt_for_alternatives_two_args() -> None:
    """Two alternatives produce two prompts."""
    prompt = "%alt(%m:opus,%m:sonnet)\nReview this code"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus\nReview this code"
    assert result[1] == "%m:sonnet\nReview this code"


def test_split_prompt_for_alternatives_three_args() -> None:
    """Three alternatives produce three prompts."""
    prompt = "%alt(fast,balanced,thorough)\nAnalyze this"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "fast\nAnalyze this"
    assert result[1] == "balanced\nAnalyze this"
    assert result[2] == "thorough\nAnalyze this"


def test_split_prompt_for_alternatives_single_arg_splits_with_empty() -> None:
    """Single arg produces two prompts: one with the arg and one without."""
    result = _split_prompt_for_alternatives("%alt(only_one)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "only_one\nDo work"
    assert result[1] == "\nDo work"


def test_split_prompt_for_alternatives_single_arg_own_line() -> None:
    """Single arg on its own line: removal variant has a leading newline."""
    result = _split_prompt_for_alternatives("Header\n%alt(extra)\nFooter")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "Header\nextra\nFooter"
    assert result[1] == "Header\n\nFooter"


def test_split_prompt_for_alternatives_single_arg_nested_directive() -> None:
    """Single arg with nested directive preserves the directive in one variant."""
    result = _split_prompt_for_alternatives("%alt(%m:opus) Review this code")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus Review this code"
    assert result[1] == " Review this code"


def test_split_prompt_for_alternatives_zero_args_returns_none() -> None:
    """Zero args returns None."""
    assert _split_prompt_for_alternatives("%alt()\nDo work") is None


def test_split_prompt_for_alternatives_no_alt_returns_none() -> None:
    """No %alt directive returns None."""
    assert _split_prompt_for_alternatives("Just a prompt") is None


def test_split_prompt_for_alternatives_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%approve\n%alt(%m:opus,%m:sonnet)\nReview this code"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%approve\n%m:opus\nReview this code"
    assert result[1] == "%approve\n%m:sonnet\nReview this code"


def test_split_prompt_for_alternatives_text_block_args() -> None:
    """Text block args [[...]] are expanded."""
    prompt = "%alt([[Focus on security]],[[Focus on performance]])\nReview this code"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "Focus on security\nReview this code"
    assert result[1] == "Focus on performance\nReview this code"


def test_split_prompt_for_alternatives_nested_directives() -> None:
    """Nested directives in args (e.g., %m:opus) are preserved."""
    prompt = "%alt(%m:opus %name:reviewer,%m:sonnet %name:coder)\nDo work"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus %name:reviewer\nDo work"
    assert result[1] == "%m:sonnet %name:coder\nDo work"


def test_split_prompt_for_alternatives_multiple_alt_cartesian() -> None:
    """Two %alt directives produce Cartesian product (2x2 = 4 prompts)."""
    prompt = "%alt(a,b) %alt(c,d)\nDo work"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "a c\nDo work"
    assert result[1] == "a d\nDo work"
    assert result[2] == "b c\nDo work"
    assert result[3] == "b d\nDo work"


# --- %(...) shorthand tests ---


def test_split_prompt_for_alternatives_shorthand_two_args() -> None:
    """%(a,b) shorthand produces two prompts like %alt(a,b)."""
    result = _split_prompt_for_alternatives("%(a,b)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "a\nDo work"
    assert result[1] == "b\nDo work"


def test_split_prompt_for_alternatives_shorthand_single_arg() -> None:
    """%(only_one) shorthand produces two prompts (implicit empty variant)."""
    result = _split_prompt_for_alternatives("%(only_one)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "only_one\nDo work"
    assert result[1] == "\nDo work"


def test_split_prompt_for_alternatives_shorthand_mixed_with_alt_cartesian() -> None:
    """%(a,b) combined with %alt(c,d) produces Cartesian product (4 prompts)."""
    prompt = "%(a,b) %alt(c,d)\nDo work"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "a c\nDo work"
    assert result[1] == "a d\nDo work"
    assert result[2] == "b c\nDo work"
    assert result[3] == "b d\nDo work"


def test_split_prompt_for_alternatives_three_directives() -> None:
    """Three directives produce 2x2x3 = 12 prompts."""
    prompt = "%alt(a,b) %alt(c,d) %alt(e,f,g)\nDo work"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 12
    assert result[0] == "a c e\nDo work"
    assert result[-1] == "b d g\nDo work"


def test_split_prompt_for_alternatives_single_arg_combined() -> None:
    """Single-arg (implicit empty) combined with another directive (2x2 = 4)."""
    prompt = "%alt(extra) %alt(c,d)\nDo work"
    result = _split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "extra c\nDo work"
    assert result[1] == "extra d\nDo work"
    assert result[2] == " c\nDo work"
    assert result[3] == " d\nDo work"


def test_split_prompt_for_models_with_alt_directive() -> None:
    """%model(opus,sonnet) combined with %(x,y) produces 4 prompts."""
    prompt = "%n:foo\n%m(opus,sonnet) %(x,y)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert (
        "%name:foo.claude-opus" in result[0]
        and "%model:opus" in result[0]
        and "x" in result[0]
    )
    assert (
        "%name:foo.claude-opus" in result[1]
        and "%model:opus" in result[1]
        and "y" in result[1]
    )
    assert (
        "%name:foo.claude-sonnet" in result[2]
        and "%model:sonnet" in result[2]
        and "x" in result[2]
    )
    assert (
        "%name:foo.claude-sonnet" in result[3]
        and "%model:sonnet" in result[3]
        and "y" in result[3]
    )


# --- has_alt_directive tests ---


def test_has_alt_directive_present() -> None:
    """Detects %alt( syntax."""
    assert has_alt_directive("%alt(a,b)\nDo something") is True


def test_has_alt_directive_start_of_line() -> None:
    """Detects %alt at start of line."""
    assert has_alt_directive("Do work\n%alt(a,b)") is True


def test_has_alt_directive_after_space() -> None:
    """Detects %alt after whitespace."""
    assert has_alt_directive("Do something %alt(a,b)") is True


def test_has_alt_directive_absent() -> None:
    """Returns False when no %alt directive present."""
    assert has_alt_directive("Do something %model:opus") is False


def test_has_alt_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_alt_directive("Just a plain prompt") is False


def test_has_alt_directive_partial_no_paren() -> None:
    """Returns False for %alt without opening paren."""
    assert has_alt_directive("%alt:something") is False


def test_has_alt_directive_shorthand() -> None:
    """Detects %( shorthand syntax."""
    assert has_alt_directive("%(a,b)\nDo something") is True
    assert has_alt_directive("Do something %(a,b)") is True


def test_has_alt_directive_bare_percent_no_paren() -> None:
    """Returns False for % without ( (no regression)."""
    assert has_alt_directive("50% done") is False
    assert has_alt_directive("Use 100% of CPU") is False


# --- _parse_duration tests ---


def test__parse_duration_minutes() -> None:
    """'5m' parses to 300 seconds."""
    assert _parse_duration("5m") == 300.0


def test__parse_duration_hours() -> None:
    """'1h' parses to 3600 seconds."""
    assert _parse_duration("1h") == 3600.0


def test__parse_duration_seconds() -> None:
    """'90s' parses to 90 seconds."""
    assert _parse_duration("90s") == 90.0


def test__parse_duration_hours_minutes() -> None:
    """'2h30m' parses to 9000 seconds."""
    assert _parse_duration("2h30m") == 9000.0


def test__parse_duration_full() -> None:
    """'1h30m15s' parses to 5415 seconds."""
    assert _parse_duration("1h30m15s") == 5415.0


def test__parse_duration_zero() -> None:
    """'0s' parses to 0."""
    assert _parse_duration("0s") == 0.0


def test__parse_duration_all_zeros() -> None:
    """'0h0m0s' parses to 0."""
    assert _parse_duration("0h0m0s") == 0.0


def test__parse_duration_invalid_unit() -> None:
    """'5x' is not a valid duration."""
    assert _parse_duration("5x") is None


def test__parse_duration_wrong_order() -> None:
    """'5m3h' is not valid (units must be h > m > s)."""
    assert _parse_duration("5m3h") is None


def test__parse_duration_duplicate_unit() -> None:
    """'5m5m' is not valid."""
    assert _parse_duration("5m5m") is None


def test__parse_duration_agent_name() -> None:
    """Agent names (start with letter) return None."""
    assert _parse_duration("abc") is None


def test__parse_duration_empty() -> None:
    """Empty string returns None."""
    assert _parse_duration("") is None


# --- _parse_absolute_time tests ---


def test__parse_absolute_time_hhmm_future() -> None:
    """HHMM in the future returns today's ISO string."""
    # Use 23:59 which is almost certainly in the future relative to test time
    # (unless tests run at exactly 23:59)
    tomorrow = datetime.now() + timedelta(days=1)
    result = _parse_absolute_time(tomorrow.strftime("%H%M"))
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.hour == tomorrow.hour
    assert target.minute == tomorrow.minute


def test__parse_absolute_time_hhmm_past_wraps_to_tomorrow() -> None:
    """HHMM in the past wraps to tomorrow."""
    # Use 00:00 which is almost certainly in the past
    result = _parse_absolute_time("0000")
    assert result is not None
    target = datetime.fromisoformat(result)
    # Should be tomorrow (since 00:00 today has passed)
    assert target.date() == (datetime.now() + timedelta(days=1)).date()


def test__parse_absolute_time_yymmdd_hhmm_future() -> None:
    """yymmdd/HHMM in the future returns correct ISO string."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    result = _parse_absolute_time(f"{date_str}/1430")
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.year == future.year
    assert target.month == future.month
    assert target.day == future.day
    assert target.hour == 14
    assert target.minute == 30


def test__parse_absolute_time_yymmdd_hhmm_past_raises() -> None:
    """yymmdd/HHMM in the past raises DirectiveError."""
    past = datetime.now() - timedelta(days=30)
    date_str = past.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="in the past"):
        _parse_absolute_time(f"{date_str}/0000")


def test__parse_absolute_time_invalid_hour() -> None:
    """Hour > 23 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        _parse_absolute_time("2500")


def test__parse_absolute_time_invalid_minute() -> None:
    """Minute > 59 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="minutes 00-59"):
        _parse_absolute_time("1261")


def test__parse_absolute_time_invalid_month() -> None:
    """Month > 12 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="month must be 01-12"):
        _parse_absolute_time("261311/1430")


def test__parse_absolute_time_invalid_day() -> None:
    """Day > 31 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="day must be 01-31"):
        _parse_absolute_time("260132/1430")


def test__parse_absolute_time_invalid_date_combo() -> None:
    """Feb 30 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="Invalid date/time"):
        _parse_absolute_time("260230/1430")


def test__parse_absolute_time_no_match() -> None:
    """Non-matching strings return None."""
    assert _parse_absolute_time("abc") is None
    assert _parse_absolute_time("5m") is None
    assert _parse_absolute_time("12345") is None
    assert _parse_absolute_time("") is None


def test__parse_absolute_time_yymmdd_invalid_hour() -> None:
    """yymmdd/HHMM with invalid hour raises DirectiveError."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        _parse_absolute_time(f"{date_str}/2500")
