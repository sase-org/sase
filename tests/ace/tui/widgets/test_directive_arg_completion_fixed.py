"""Fixed-value directive argument completion (effort/auto, queue, misc).

Split from ``test_directive_arg_completion``; shared builders live in
``_directive_completion_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    build_directive_clause_candidates,
    classify_directive_completion,
)
from sase.legacy_xprompt_names import LEGACY_XPROMPT_ENABLED_DIRECTIVE_NAME
from sase.macro._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives
from sase.macro.effort import EFFORT_LEVELS_ORDERED

from ._directive_completion_helpers import (
    build_directive_arg_completion_candidates,
    directive_arg_metadata,
)

__all__ = [
    "test_auto_argument_completion_suggests_compatibility_values_without_closing_parser",
    "test_directive_arg_completion_accepts_effort_e_alias",
    "test_directive_arg_completion_builds_fixed_value_candidates",
    "test_directive_arg_completion_filters_case_insensitive_prefixes",
    "test_directive_arg_completion_ignores_open_text_directives",
    "test_directive_arg_completion_metadata_has_descriptions",
    "test_legacy_enabled_directive_offers_bool_values",
    "test_queue_capacity_completion_describes_limit",
    "test_queue_priority_completion_describes_order_and_default",
    "test_repeat_offers_positive_count_examples",
]


def test_directive_arg_completion_builds_fixed_value_candidates() -> None:
    effort_candidates, effort_shared = build_directive_arg_completion_candidates(
        "effort",
        "",
    )
    auto_candidates, auto_shared = build_directive_arg_completion_candidates(
        "auto",
        "",
    )

    assert [candidate.insertion for candidate in effort_candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert [candidate.insertion for candidate in auto_candidates] == list(
        AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )
    assert effort_shared == ""
    assert auto_shared == ""


def test_directive_arg_completion_accepts_effort_e_alias() -> None:
    """``%e:`` offers the canonical effort vocabulary, same as ``%effort:``."""
    e_candidates, e_shared = build_directive_arg_completion_candidates("e", "")

    assert [candidate.insertion for candidate in e_candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert e_shared == ""


def test_directive_arg_completion_filters_case_insensitive_prefixes() -> None:
    effort_candidates, _ = build_directive_arg_completion_candidates("effort", "h")
    auto_candidates, _ = build_directive_arg_completion_candidates("auto", "t")
    xhigh_candidates, _ = build_directive_arg_completion_candidates("effort", "XH")

    assert [candidate.insertion for candidate in effort_candidates] == ["high"]
    assert [candidate.insertion for candidate in auto_candidates] == ["tale"]
    assert [candidate.insertion for candidate in xhigh_candidates] == ["xhigh"]


def test_directive_arg_completion_ignores_open_text_directives() -> None:
    candidates, shared = build_directive_arg_completion_candidates("name", "")

    assert candidates == []
    assert shared == ""


def test_queue_priority_completion_describes_order_and_default() -> None:
    text = "%queue(pri"
    clause = classify_directive_completion(text, len(text))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(clause)

    assert [candidate.insertion for candidate in candidates] == ["priority="]
    assert directive_arg_metadata(candidates[0]).description == (
        "Lower values start first; the default is 10"
    )


def test_queue_capacity_completion_describes_limit() -> None:
    text = "%queue(cap"
    clause = classify_directive_completion(text, len(text))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(clause)

    assert [candidate.insertion for candidate in candidates] == ["capacity="]
    assert directive_arg_metadata(candidates[0]).description == (
        "This launch's capacity budget, replacing max_running_agents, "
        "or <M>x multiplier of this machine's max_running_agents budget"
    )


def test_directive_arg_completion_metadata_has_descriptions() -> None:
    candidates, _ = build_directive_arg_completion_candidates("auto", "")

    assert all(
        directive_arg_metadata(candidate).description for candidate in candidates
    )
    assert all(
        isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
        for candidate in candidates
    )


def test_auto_argument_completion_suggests_compatibility_values_without_closing_parser() -> (
    None
):
    # Keep these suggestions aligned with Rust directive_argument_candidates("auto")
    # in sase-core. They are the closed launch grammar, including the
    # manual/off spellings that disable automatic approval.
    assert AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS == (
        "plan",
        "tale",
        "epic",
        "manual",
        "off",
    )
    candidates, _ = build_directive_arg_completion_candidates("auto", "")
    assert tuple(candidate.insertion for candidate in candidates) == (
        AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )

    with pytest.raises(DirectiveError, match="Invalid %auto spelling"):
        extract_prompt_directives("%auto:foo\nDo the work")


def test_legacy_enabled_directive_offers_bool_values() -> None:
    candidates, _ = build_directive_arg_completion_candidates(
        LEGACY_XPROMPT_ENABLED_DIRECTIVE_NAME, ""
    )

    assert [candidate.insertion for candidate in candidates] == ["false", "true"]
    assert all(
        directive_arg_metadata(candidate).description for candidate in candidates
    )


def test_repeat_offers_positive_count_examples() -> None:
    candidates, _ = build_directive_arg_completion_candidates("repeat", "")

    assert [candidate.insertion for candidate in candidates] == ["2", "3"]
