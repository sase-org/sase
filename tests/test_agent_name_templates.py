"""Tests for generic agent-name templates."""

from __future__ import annotations

from itertools import islice

import pytest

from sase.agent.names import (
    AgentNameTemplateNotFoundError,
    InvalidAgentNameTemplateError,
    AgentNameNamespaceReservationIndex,
    agent_name_template_base,
    agent_name_template_namespace_template,
    allocate_agent_name_template,
    compare_agent_name_template_tokens,
    is_agent_name_template,
    iter_agent_name_template_tokens,
    latest_agent_name_template,
    match_agent_name_template,
    parse_agent_name_template,
    render_agent_name_template_namespace,
    render_agent_name_template,
    require_latest_agent_name_template,
)


def test_detects_exactly_one_marker() -> None:
    assert is_agent_name_template("@") is True
    assert is_agent_name_template("build-@") is True
    assert is_agent_name_template("@.cld") is True
    assert is_agent_name_template("research.@.final") is True
    assert is_agent_name_template("build") is False
    assert is_agent_name_template("build-@-@") is False


def test_parse_rejects_multiple_markers() -> None:
    with pytest.raises(InvalidAgentNameTemplateError, match="exactly one"):
        parse_agent_name_template("build-@-@")


def test_template_base_is_stable_reference_key() -> None:
    assert agent_name_template_base("@") == "@"
    assert agent_name_template_base("build-@") == "build"
    assert agent_name_template_base("@.cld") == "cld"
    assert agent_name_template_base("research.@.final") == "research.final"


def test_renders_template_shapes() -> None:
    assert render_agent_name_template("@", "0") == "0"
    assert render_agent_name_template("@", "1") == "1"
    assert render_agent_name_template("build-@", "0") == "build-0"
    assert render_agent_name_template("build-@", "1") == "build-1"
    assert render_agent_name_template("@.cld", "0") == "0.cld"
    assert render_agent_name_template("@.cld", "1") == "1.cld"
    assert render_agent_name_template("research.@.final", "0") == "research.0.final"
    assert render_agent_name_template("research.@.final", "1") == "research.1.final"


def test_derives_namespace_template_shapes() -> None:
    assert agent_name_template_namespace_template("@") == "@"
    assert agent_name_template_namespace_template("@.cld") == "@"
    assert agent_name_template_namespace_template("foo-@") == "foo-@"
    assert agent_name_template_namespace_template("foo.@.bar") == "foo.@"
    assert agent_name_template_namespace_template("foo.@x.bar") == "foo.@x"
    assert render_agent_name_template_namespace("foo.@x.bar", "0") == "foo.0x"


def test_matches_template_tokens() -> None:
    assert match_agent_name_template("build-@", "build-1") == "1"
    assert match_agent_name_template("build-@", "build-a") == "a"
    assert match_agent_name_template("build-@", "other-1") is None
    assert match_agent_name_template("@.cld", "00.cld") == "00"
    assert match_agent_name_template("research.@.final", "research.z.final") == "z"
    assert match_agent_name_template("@", "not.auto") is None


def test_compares_tokens_by_auto_sequence_order() -> None:
    assert compare_agent_name_template_tokens("9", "a") < 0
    assert compare_agent_name_template_tokens("z", "00") < 0
    assert compare_agent_name_template_tokens("09", "0a") < 0
    assert compare_agent_name_template_tokens("10", "0z") > 0


def test_token_iterator_uses_auto_sequence() -> None:
    assert list(islice(iter_agent_name_template_tokens(), 12)) == [
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "a",
        "b",
    ]


def test_allocates_lowest_available_rendered_name() -> None:
    reserved = {"build-0", "build-2"}

    assert allocate_agent_name_template("build-@", reserved=reserved) == "build-1"
    assert allocate_agent_name_template("build-@", reserved=reserved) == "build-3"
    assert reserved == {"build-0", "build-1", "build-2", "build-3"}


def test_allocates_by_namespace_not_just_rendered_name() -> None:
    assert allocate_agent_name_template("@.cld", reserved={"0"}) == "1.cld"
    assert allocate_agent_name_template("@.cld", reserved={"0.cdx"}) == "1.cld"
    assert allocate_agent_name_template("foo.@.bar", reserved={"foo.0"}) == "foo.1.bar"
    assert (
        allocate_agent_name_template("foo.@.bar", reserved={"foo.0.any"}) == "foo.1.bar"
    )
    assert allocate_agent_name_template("foo-@", reserved={"foo-0.any"}) == "foo-1"


def test_namespace_index_uses_dotted_prefixes_not_raw_string_prefixes() -> None:
    index = AgentNameNamespaceReservationIndex.from_names({"research.10"})

    assert index.candidate_available("research.1.final", "research.1") is True
    assert index.candidate_available("research.10.final", "research.10") is False


def test_latest_uses_auto_sequence_order() -> None:
    names = {
        "build",
        "build-0",
        "build-9",
        "build-a",
        "build-z",
        "build-00",
        "build-01",
        "other-z",
    }

    assert latest_agent_name_template("build-@", names=names) == "build-01"


def test_require_latest_raises_typed_error() -> None:
    with pytest.raises(AgentNameTemplateNotFoundError, match="review-@"):
        require_latest_agent_name_template("review-@", names={"review", "review.x"})
