"""Tests for split_prompt_for_alternatives and the %(...) shorthand."""

from sase.xprompt.directives import split_prompt_for_alternatives


def testsplit_prompt_for_alternatives_two_args() -> None:
    """Two alternatives produce two prompts."""
    prompt = "%alt(%m:opus,%m:sonnet)\nReview this code"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus\nReview this code"
    assert result[1] == "%m:sonnet\nReview this code"


def testsplit_prompt_for_alternatives_three_args() -> None:
    """Three alternatives produce three prompts."""
    prompt = "%alt(fast,balanced,thorough)\nAnalyze this"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "fast\nAnalyze this"
    assert result[1] == "balanced\nAnalyze this"
    assert result[2] == "thorough\nAnalyze this"


def testsplit_prompt_for_alternatives_single_arg_splits_with_empty() -> None:
    """Single arg produces two prompts: one with the arg and one without."""
    result = split_prompt_for_alternatives("%alt(only_one)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "only_one\nDo work"
    assert result[1] == "\nDo work"


def testsplit_prompt_for_alternatives_single_arg_own_line() -> None:
    """Single arg on its own line: removal variant has a leading newline."""
    result = split_prompt_for_alternatives("Header\n%alt(extra)\nFooter")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "Header\nextra\nFooter"
    assert result[1] == "Header\n\nFooter"


def testsplit_prompt_for_alternatives_single_arg_nested_directive() -> None:
    """Single arg with nested directive preserves the directive in one variant."""
    result = split_prompt_for_alternatives("%alt(%m:opus) Review this code")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus Review this code"
    assert result[1] == " Review this code"


def testsplit_prompt_for_alternatives_zero_args_returns_none() -> None:
    """Zero args returns None."""
    assert split_prompt_for_alternatives("%alt()\nDo work") is None


def testsplit_prompt_for_alternatives_no_alt_returns_none() -> None:
    """No %alt directive returns None."""
    assert split_prompt_for_alternatives("Just a prompt") is None


def testsplit_prompt_for_alternatives_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%approve\n%alt(%m:opus,%m:sonnet)\nReview this code"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%approve\n%m:opus\nReview this code"
    assert result[1] == "%approve\n%m:sonnet\nReview this code"


def testsplit_prompt_for_alternatives_text_block_args() -> None:
    """Text block args [[...]] are expanded."""
    prompt = "%alt([[Focus on security]],[[Focus on performance]])\nReview this code"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "Focus on security\nReview this code"
    assert result[1] == "Focus on performance\nReview this code"


def testsplit_prompt_for_alternatives_named_args_insert_values_only() -> None:
    """Named %alt args use names as metadata and insert only arg values."""
    prompt = "%alt(sec=[[security]],perf=[[performance]])\nReview"
    result = split_prompt_for_alternatives(prompt)

    assert result is not None
    assert result == ["security\nReview", "performance\nReview"]


def testsplit_prompt_for_alternatives_named_shorthand_mixes_numeric_ids() -> None:
    """The %(...) shorthand accepts named and unnamed arguments."""
    result = split_prompt_for_alternatives("%(fast=[[fast pass]], [[slow pass]])")

    assert result is not None
    assert result == ["fast pass", "slow pass"]


def testsplit_prompt_for_alternatives_nested_directives() -> None:
    """Nested directives in args (e.g., %m:opus) are preserved."""
    prompt = "%alt(%m:opus %name:reviewer,%m:sonnet %name:coder)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus %name:reviewer\nDo work"
    assert result[1] == "%m:sonnet %name:coder\nDo work"


def testsplit_prompt_for_alternatives_multiple_alt_cartesian() -> None:
    """Two %alt directives produce Cartesian product (2x2 = 4 prompts)."""
    prompt = "%alt(a,b) %alt(c,d)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "a c\nDo work"
    assert result[1] == "a d\nDo work"
    assert result[2] == "b c\nDo work"
    assert result[3] == "b d\nDo work"


# --- %(...) shorthand tests ---


def testsplit_prompt_for_alternatives_shorthand_two_args() -> None:
    """%(a,b) shorthand produces two prompts like %alt(a,b)."""
    result = split_prompt_for_alternatives("%(a,b)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "a\nDo work"
    assert result[1] == "b\nDo work"


def testsplit_prompt_for_alternatives_shorthand_single_arg() -> None:
    """%(only_one) shorthand produces two prompts (implicit empty variant)."""
    result = split_prompt_for_alternatives("%(only_one)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "only_one\nDo work"
    assert result[1] == "\nDo work"


def testsplit_prompt_for_alternatives_shorthand_mixed_with_alt_cartesian() -> None:
    """%(a,b) combined with %alt(c,d) produces Cartesian product (4 prompts)."""
    prompt = "%(a,b) %alt(c,d)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "a c\nDo work"
    assert result[1] == "a d\nDo work"
    assert result[2] == "b c\nDo work"
    assert result[3] == "b d\nDo work"


def testsplit_prompt_for_alternatives_three_directives() -> None:
    """Three directives produce 2x2x3 = 12 prompts."""
    prompt = "%alt(a,b) %alt(c,d) %alt(e,f,g)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 12
    assert result[0] == "a c e\nDo work"
    assert result[-1] == "b d g\nDo work"


def testsplit_prompt_for_alternatives_single_arg_combined() -> None:
    """Single-arg (implicit empty) combined with another directive (2x2 = 4)."""
    prompt = "%alt(extra) %alt(c,d)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 4
    assert result[0] == "extra c\nDo work"
    assert result[1] == "extra d\nDo work"
    assert result[2] == " c\nDo work"
    assert result[3] == " d\nDo work"
