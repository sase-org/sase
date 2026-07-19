"""Tests for split_prompt_for_alternatives and the %(...) / %{...} shorthands."""

import pytest

from sase.xprompt._exceptions import DirectiveError
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
    assert result[1] == "Review this code"


def testsplit_prompt_for_alternatives_zero_args_returns_none() -> None:
    """Zero args returns None."""
    assert split_prompt_for_alternatives("%alt()\nDo work") is None


def testsplit_prompt_for_alternatives_no_alt_returns_none() -> None:
    """No %alt directive returns None."""
    assert split_prompt_for_alternatives("Just a prompt") is None


def testsplit_prompt_for_alternatives_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%auto\n%alt(%m:opus,%m:sonnet)\nReview this code"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%auto\n%m:opus\nReview this code"
    assert result[1] == "%auto\n%m:sonnet\nReview this code"


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
    prompt = "%alt(%m:opus %id:reviewer,%m:sonnet %id:coder)\nDo work"
    result = split_prompt_for_alternatives(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%m:opus %id:reviewer\nDo work"
    assert result[1] == "%m:sonnet %id:coder\nDo work"


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


def testsplit_prompt_for_alternatives_shared_named_keys_correlate() -> None:
    """Repeated named keys across alt directives zip into shared slots."""
    prompt = "#gh:sase %{a=Describe | b=Explain} how this repo works %{a=in detail}."
    result = split_prompt_for_alternatives(prompt)

    assert result == [
        "#gh:sase Describe how this repo works in detail.",
        "#gh:sase Explain how this repo works.",
    ]


def testsplit_prompt_for_alternatives_empty_branch_collapses_whitespace() -> None:
    """Empty variants collapse adjacent horizontal whitespace conservatively."""
    assert split_prompt_for_alternatives("works %{extra}.") == [
        "works extra.",
        "works.",
    ]
    assert split_prompt_for_alternatives("%{extra} Review") == [
        "extra Review",
        "Review",
    ]


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
    assert result[2] == "c\nDo work"
    assert result[3] == "d\nDo work"


# --- %{...} brace shorthand tests ---


def testsplit_prompt_for_alternatives_brace_two_branches() -> None:
    """%{a | b} splits on top-level pipes like %alt(a,b)."""
    result = split_prompt_for_alternatives("%{a | b}\nReview")
    assert result == ["a\nReview", "b\nReview"]


def testsplit_prompt_for_alternatives_brace_three_branches() -> None:
    """%{a | b | c} produces three prompts."""
    result = split_prompt_for_alternatives("%{a | b | c}\nReview")
    assert result == ["a\nReview", "b\nReview", "c\nReview"]


def testsplit_prompt_for_alternatives_brace_branch_text_keeps_commas() -> None:
    """Commas inside a brace branch are branch text, not separators."""
    result = split_prompt_for_alternatives("%{foo, bar | baz}")
    assert result == ["foo, bar", "baz"]


def testsplit_prompt_for_alternatives_brace_named_text_blocks() -> None:
    """Named brace branches insert only the [[text block]] values."""
    result = split_prompt_for_alternatives(
        "%{sec=[[security]] | perf=[[performance]]}\nReview"
    )
    assert result == ["security\nReview", "performance\nReview"]


def testsplit_prompt_for_alternatives_brace_single_branch_implicit_empty() -> None:
    """A single brace branch produces with/without variants."""
    result = split_prompt_for_alternatives("before %{a} after")
    assert result == ["before a after", "before after"]


def testsplit_prompt_for_alternatives_brace_nested_pipes_do_not_split() -> None:
    """Pipes inside (), [], or backticks are not top-level separators."""
    result = split_prompt_for_alternatives("%{a (x | y) | b [c | d] | `e | f`}")
    assert result == ["a (x | y)", "b [c | d]", "e | f"]


def testsplit_prompt_for_alternatives_brace_nested_directives() -> None:
    """Nested directives inside brace branches are preserved."""
    result = split_prompt_for_alternatives(
        "%{%m:opus %id:reviewer | %m:sonnet %id:coder}\nDo work"
    )
    assert result == [
        "%m:opus %id:reviewer\nDo work",
        "%m:sonnet %id:coder\nDo work",
    ]


def testsplit_prompt_for_alternatives_brace_composes_cartesian_with_paren() -> None:
    """%{a | b} combined with %alt(x,y) produces the Cartesian product."""
    result = split_prompt_for_alternatives("%{a | b} %alt(x,y)")
    assert result == ["a x", "a y", "b x", "b y"]


def testsplit_prompt_for_alternatives_brace_zero_branches_returns_none() -> None:
    """An empty %{} has no branches and returns None."""
    assert split_prompt_for_alternatives("%{}\nDo work") is None


def testsplit_prompt_for_alternatives_brace_whitespace_only_returns_none() -> None:
    """A padded but unfilled %{  } has no branches and returns None."""
    assert split_prompt_for_alternatives("%{  }\nDo work") is None


def testsplit_prompt_for_alternatives_brace_preserves_other_directives() -> None:
    """Other directives around a %{} brace alt are preserved."""
    result = split_prompt_for_alternatives("%auto\n%{a | b}\nReview")
    assert result == ["%auto\na\nReview", "%auto\nb\nReview"]


def testsplit_prompt_for_alternatives_brace_after_directive_colon() -> None:
    """A brace alt after a directive colon fans out just the directive value."""
    result = split_prompt_for_alternatives("%effort:%{medium | high | xhigh}\nReview")

    assert result == [
        "%effort:medium\nReview",
        "%effort:high\nReview",
        "%effort:xhigh\nReview",
    ]


def testsplit_prompt_for_alternatives_paren_after_directive_colon() -> None:
    """The paren shorthand also works as directive value fan-out."""
    result = split_prompt_for_alternatives("%m:%(opus,sonnet)\nReview")

    assert result == ["%m:opus\nReview", "%m:sonnet\nReview"]


def testsplit_prompt_for_alternatives_brace_unclosed_raises() -> None:
    """An unclosed %{ reports a DirectiveError mentioning the missing close."""
    with pytest.raises(DirectiveError, match=r"%\{"):
        split_prompt_for_alternatives("%{a | b")
