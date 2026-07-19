"""Tests for reasoning-effort parsing (Phase 1 of the xprompt effort epic).

Covers the shared ``split_model_effort`` helper, ``%effort`` directive and
``%model:<model>@<effort>`` suffix extraction, the conflict rule, fan-out
naming with effort suffixes, and effort stripping in history previews.
"""

import pytest

from sase.history.prompt_metadata import (
    clean_prompt_preview,
    summarize_prompt_for_preview,
)
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    extract_prompt_directives,
    split_prompt_for_models,
    strip_known_directives,
)
from sase.xprompt.effort import (
    EFFORT_LEVELS,
    EFFORT_LEVELS_ORDERED,
    is_valid_effort,
    split_model_effort,
)

# --- split_model_effort + vocabulary ---


def test_effort_vocabulary_is_canonical() -> None:
    """The canonical vocabulary matches the design spec, frozenset + ordering."""
    assert EFFORT_LEVELS == frozenset(EFFORT_LEVELS_ORDERED)
    assert EFFORT_LEVELS == {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
    # Ordered least-to-most for human-readable messages.
    assert EFFORT_LEVELS_ORDERED[0] == "none"
    assert EFFORT_LEVELS_ORDERED[-1] == "max"


def test_is_valid_effort() -> None:
    assert is_valid_effort("xhigh")
    assert is_valid_effort("none")
    assert not is_valid_effort("xhig")
    assert not is_valid_effort("")
    assert not is_valid_effort("XHIGH")


def test_split_model_effort_splits_known_trailing_level() -> None:
    assert split_model_effort("opus@xhigh") == ("opus", "xhigh")
    assert split_model_effort("codex/gpt-5.6-sol@xhigh") == (
        "codex/gpt-5.6-sol",
        "xhigh",
    )
    assert split_model_effort("opus@max") == ("opus", "max")


def test_split_model_effort_leaves_unknown_trailing_token() -> None:
    """A trailing ``@token`` that is not a known level is preserved."""
    assert split_model_effort("foo@bar") == ("foo@bar", None)
    assert split_model_effort("model@v2") == ("model@v2", None)


def test_split_model_effort_no_at_sign() -> None:
    assert split_model_effort("opus") == ("opus", None)


def test_split_model_effort_leading_at_not_split() -> None:
    """An ``@`` with no model name before it is not a split point."""
    assert split_model_effort("@high") == ("@high", None)


def test_split_model_effort_only_last_token_considered() -> None:
    """Only the final ``@token`` is examined; earlier ``@`` stays in the model."""
    assert split_model_effort("a@b@high") == ("a@b", "high")
    assert split_model_effort("a@high@b") == ("a@high@b", None)


# --- %effort directive extraction ---


def test_effort_directive_colon_arg() -> None:
    prompt = "%effort:xhigh\nReview this code"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review this code"
    assert directives.reasoning_effort == "xhigh"
    assert directives.model is None


def test_effort_directive_paren_arg() -> None:
    prompt = "%effort(high)\nReview"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Review"
    assert directives.reasoning_effort == "high"


def test_effort_directive_stripped_from_prompt() -> None:
    """The %effort span is removed from the cleaned prompt entirely."""
    cleaned, _ = extract_prompt_directives("%effort:max\nDo the work")
    assert "%effort" not in cleaned
    assert cleaned == "Do the work"


def test_no_effort_directive_defaults_none() -> None:
    _, directives = extract_prompt_directives("Just a prompt")
    assert directives.reasoning_effort is None


def test_effort_directive_e_alias_colon_arg() -> None:
    """``%e`` is the advertised alias for ``%effort`` and sets the effort level."""
    cleaned, directives = extract_prompt_directives("%e:xhigh\nReview this code")
    assert cleaned == "Review this code"
    assert directives.reasoning_effort == "xhigh"
    assert directives.model is None


def test_effort_directive_e_alias_paren_arg() -> None:
    """``%e(<level>)`` works exactly like ``%effort(<level>)``."""
    _, directives = extract_prompt_directives("%e(high)\nReview")
    assert directives.reasoning_effort == "high"


def test_effort_directive_e_alias_bare_requires_level() -> None:
    """Bare ``%e`` raises the canonical effort message, not the removed-%edit one."""
    with pytest.raises(DirectiveError, match="requires a level argument"):
        extract_prompt_directives("%e\nReview")


def test_duplicate_effort_e_alias_reports_canonical_directive() -> None:
    """``%e:low`` + ``%effort:high`` are both the canonical ``%effort`` directive."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%effort'"):
        extract_prompt_directives("%e:low\n%effort:high\nReview")


def test_effort_e_alias_conflicts_with_model_suffix() -> None:
    """``%e`` participates in the canonical ``%effort`` conflict check."""
    with pytest.raises(DirectiveError, match="Conflicting effort levels"):
        extract_prompt_directives("%model:opus@low\n%e:xhigh\nReview")


def test_effort_directive_unknown_level_raises() -> None:
    with pytest.raises(DirectiveError, match="Unknown effort level 'bogus'"):
        extract_prompt_directives("%effort:bogus\nReview")


def test_effort_directive_bare_raises() -> None:
    with pytest.raises(DirectiveError, match="requires a level argument"):
        extract_prompt_directives("%effort\nReview")


def test_duplicate_effort_directive_raises() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%effort'"):
        extract_prompt_directives("%effort:low\n%effort:high\nReview")


# --- %model:<model>@<effort> suffix split ---


def test_model_suffix_split_colon() -> None:
    cleaned, directives = extract_prompt_directives(
        "%model:codex/gpt-5.6-sol@xhigh\nReview"
    )
    assert cleaned == "Review"
    assert directives.model == "codex/gpt-5.6-sol"
    assert directives.reasoning_effort == "xhigh"


def test_model_suffix_split_alias_colon() -> None:
    _, directives = extract_prompt_directives("%m:opus@xhigh\nReview")
    assert directives.model == "opus"
    assert directives.reasoning_effort == "xhigh"


def test_model_suffix_split_paren() -> None:
    _, directives = extract_prompt_directives("%model(opus@low)\nReview")
    assert directives.model == "opus"
    assert directives.reasoning_effort == "low"


def test_model_unknown_suffix_stays_in_model() -> None:
    """A non-effort ``@token`` stays part of the model and yields no effort."""
    _, directives = extract_prompt_directives("%model:foo@bar\nReview")
    assert directives.model == "foo@bar"
    assert directives.reasoning_effort is None


def test_model_backtick_literal_bypasses_split() -> None:
    """Backtick-literal models keep their ``@`` and produce no effort."""
    _, directives = extract_prompt_directives("%model:`weird@max`\nReview")
    assert directives.model == "weird@max"
    assert directives.reasoning_effort is None


# --- conflict rule between %effort and @effort ---


def test_effort_conflict_raises() -> None:
    with pytest.raises(DirectiveError, match="Conflicting effort levels"):
        extract_prompt_directives("%model:opus@low\n%effort:xhigh\nReview")


def test_effort_equal_values_allowed() -> None:
    _, directives = extract_prompt_directives(
        "%model:opus@xhigh\n%effort:xhigh\nReview"
    )
    assert directives.model == "opus"
    assert directives.reasoning_effort == "xhigh"


def test_effort_directive_with_clean_model_no_conflict() -> None:
    """A %effort directive alongside a model with no suffix is fine."""
    _, directives = extract_prompt_directives("%effort:high\n%model:codex/o3\nReview")
    assert directives.model == "codex/o3"
    assert directives.reasoning_effort == "high"


# --- strip / history-preview behavior ---


def test_strip_known_directives_removes_effort() -> None:
    result = strip_known_directives("%effort:xhigh Do the thing")
    assert "%effort" not in result
    assert result.strip() == "Do the thing"


def test_clean_prompt_preview_strips_effort() -> None:
    assert clean_prompt_preview("%effort:xhigh\nReview the diff") == "Review the diff"


def test_strip_known_directives_removes_e_alias() -> None:
    result = strip_known_directives("%e:xhigh Do the thing")
    assert "%e" not in result
    assert result.strip() == "Do the thing"


def test_clean_prompt_preview_strips_e_alias() -> None:
    assert clean_prompt_preview("%e:xhigh\nReview the diff") == "Review the diff"


def test_preview_directive_tokens_include_effort() -> None:
    summary = summarize_prompt_for_preview("%effort:xhigh\nReview")
    assert "%effort:xhigh" in summary.directives


def test_preview_directive_tokens_summarize_e_alias_as_effort() -> None:
    """A ``%e:`` span is summarized under the canonical ``%effort`` name."""
    summary = summarize_prompt_for_preview("%e:xhigh\nReview")
    assert "%effort:xhigh" in summary.directives


# --- per-branch fan-out naming with @effort ---


def test_fanout_same_runtime_strips_effort_from_names() -> None:
    """Per-branch effort keeps clean fan-out names; bodies preserve the suffix."""
    result = split_prompt_for_models("%i:foo\n%{%m:opus@xhigh | %m:sonnet@low}\nReview")
    assert result == [
        "%id:foo.cld_opus\n%m:opus@xhigh\nReview",
        "%id:foo.cld_sonnet\n%m:sonnet@low\nReview",
    ]


def test_fanout_distinct_runtime_strips_effort_from_names() -> None:
    result = split_prompt_for_models(
        "%i:foo\n%{%m:opus@xhigh | %m:gpt-5.6-sol@low}\nReview"
    )
    assert result == [
        "%id:foo.cld\n%m:opus@xhigh\nReview",
        "%id:foo.cdx\n%m:gpt-5.6-sol@low\nReview",
    ]


def test_fanout_branch_bodies_round_trip_to_effort() -> None:
    """Each fan-out body re-extracts to the clean model + its branch effort."""
    result = split_prompt_for_models("%{%m:opus@xhigh | %m:sonnet@low}\nReview")
    assert result is not None
    efforts = []
    for body in result:
        _, directives = extract_prompt_directives(body.split("\n", 1)[1])
        efforts.append((directives.model, directives.reasoning_effort))
    assert efforts == [("opus", "xhigh"), ("sonnet", "low")]


def test_effort_value_fanout_round_trips_to_effort() -> None:
    """%effort:%{...} fans out before per-slot directive extraction."""
    result = split_prompt_for_models(
        "%i:foo\n%m:opus %effort:%{medium | high | xhigh}\nReview"
    )

    assert result is not None
    assert [variant.splitlines()[0] for variant in result] == [
        "%id:foo.1",
        "%id:foo.2",
        "%id:foo.3",
    ]
    efforts = []
    for body in result:
        _, directives = extract_prompt_directives(body)
        efforts.append((directives.model, directives.reasoning_effort))
    assert efforts == [
        ("opus", "medium"),
        ("opus", "high"),
        ("opus", "xhigh"),
    ]
