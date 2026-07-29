"""Tests for generic agent-name templates."""

from __future__ import annotations

from itertools import islice

import pytest

from sase.agent.names import (
    AgentNameTemplateKey,
    AgentNameTemplateNotFoundError,
    InvalidAgentNameTemplateError,
    AgentNameNamespaceReservationIndex,
    agent_name_template_base,
    agent_name_template_key,
    agent_name_template_namespace_template,
    allocate_agent_name_template,
    compare_agent_name_template_tokens,
    is_agent_name_template,
    iter_agent_name_key_markers,
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
    assert render_agent_name_template("@", "a") == "a"
    assert render_agent_name_template("build-@", "0") == "build-0"
    assert render_agent_name_template("build-@", "a") == "build-a"
    assert render_agent_name_template("build.@", "a") == "build.a"
    assert render_agent_name_template("@.cld", "a") == "a.cld"
    assert render_agent_name_template("research.@.final", "0") == "research.0.final"
    assert render_agent_name_template("foo.f@", "0") == "foo.f0"
    assert render_agent_name_template("foo.f@", "a") == "foo.f-a"
    assert render_agent_name_template("foo.f@", "0a") == "foo.f0a"
    assert render_agent_name_template("foo.f@", "a0") == "foo.f-a0"


def test_derives_namespace_template_shapes() -> None:
    assert agent_name_template_namespace_template("@") == "@"
    assert agent_name_template_namespace_template("@.cld") == "@"
    assert agent_name_template_namespace_template("foo-@") == "foo-@"
    assert agent_name_template_namespace_template("foo.@.bar") == "foo.@"
    assert agent_name_template_namespace_template("foo.@x.bar") == "foo.@x"
    assert render_agent_name_template_namespace("foo.@x.bar", "0") == "foo.0x"
    assert render_agent_name_template_namespace("foo.f@x.bar", "a") == "foo.f-ax"


def test_matches_template_tokens() -> None:
    assert match_agent_name_template("build-@", "build-1") == "1"
    assert match_agent_name_template("build-@", "build-a") == "a"
    assert match_agent_name_template("build-@", "other-1") is None
    assert match_agent_name_template("@.cld", "00.cld") == "00"
    assert match_agent_name_template("research.@.final", "research.z.final") == "z"
    assert match_agent_name_template("foo.f@", "foo.f0") == "0"
    assert match_agent_name_template("foo.f@", "foo.f-a") == "a"
    assert match_agent_name_template("foo.f@", "foo.f0a") == "0a"
    assert match_agent_name_template("foo.f@", "foo.f-a0") == "a0"
    assert match_agent_name_template("@", "not.auto") is None


@pytest.mark.parametrize(
    ("template", "concrete"),
    [
        ("foo.f@", "foo.fa"),
        ("foo.f@", "foo.f-0"),
        ("foo.f@", "foo.f--a"),
        ("build-@", "build--a"),
        ("build.@", "build.-a"),
        ("@", "-a"),
    ],
)
def test_matching_rejects_noncanonical_separator_shapes(
    template: str, concrete: str
) -> None:
    assert match_agent_name_template(template, concrete) is None


@pytest.mark.parametrize("template", ["@", "@.cld", "foo.f@", "foo-@", "foo.@"])
@pytest.mark.parametrize("token", ["0", "9", "a", "z", "0a", "a0", "00"])
def test_render_and_match_are_exact_inverses(template: str, token: str) -> None:
    concrete = render_agent_name_template(template, token)
    assert match_agent_name_template(template, concrete) == token


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


def test_allocation_inserts_separator_at_letter_boundary() -> None:
    reserved = {f"foo.f{token}" for token in "0123456789"}

    assert allocate_agent_name_template("foo.f@", reserved=reserved) == "foo.f-a"
    assert allocate_agent_name_template("foo.f@", reserved=reserved) == "foo.f-b"


def test_allocates_by_namespace_not_just_rendered_name() -> None:
    assert allocate_agent_name_template("@.cld", reserved={"0"}) == "1.cld"
    assert allocate_agent_name_template("@.cld", reserved={"0.cdx"}) == "1.cld"
    assert allocate_agent_name_template("foo.@.bar", reserved={"foo.0"}) == "foo.1.bar"
    assert (
        allocate_agent_name_template("foo.@.bar", reserved={"foo.0.any"}) == "foo.1.bar"
    )
    assert allocate_agent_name_template("foo-@", reserved={"foo-0.any"}) == "foo-1"


def test_letter_leading_namespace_reservations_use_inserted_separator() -> None:
    reserved = {
        *(f"foo.f{token}" for token in "0123456789"),
        "foo.f-a.any",
    }

    assert allocate_agent_name_template("foo.f@.bar", reserved=reserved) == (
        "foo.f-b.bar"
    )


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


def test_latest_uses_canonical_conditional_separator_shapes() -> None:
    names = {
        "foo.f0",
        "foo.f9",
        "foo.f-a",
        "foo.f-z",
        "foo.f00",
        "foo.fa",
        "foo.f-0",
    }

    assert latest_agent_name_template("foo.f@", names=names) == "foo.f00"


def test_require_latest_raises_typed_error() -> None:
    with pytest.raises(AgentNameTemplateNotFoundError, match="review-@"):
        require_latest_agent_name_template("review-@", names={"review", "review.x"})


def test_parse_reports_keyed_marker_and_key() -> None:
    parsed = parse_agent_name_template("research.{@1}.cdx")

    assert parsed.prefix == "research."
    assert parsed.suffix == ".cdx"
    assert parsed.marker == "{@1}"
    assert parsed.key == AgentNameTemplateKey(id="1", qualified=False)


def test_parse_reports_qualified_key() -> None:
    parsed = parse_agent_name_template("research.{@swarm.1!}")

    assert parsed.marker == "{@swarm.1!}"
    assert parsed.key == AgentNameTemplateKey(id="swarm.1", qualified=True)


def test_parse_reports_no_key_for_bare_marker() -> None:
    parsed = parse_agent_name_template("build-@")

    assert parsed.marker == "@"
    assert parsed.key is None


def test_agent_name_template_key_wrapper() -> None:
    assert agent_name_template_key("research.{@1}.cdx") == AgentNameTemplateKey(
        id="1", qualified=False
    )
    assert agent_name_template_key("build-@") is None


def test_agent_name_template_key_rejects_invalid_template() -> None:
    with pytest.raises(InvalidAgentNameTemplateError):
        agent_name_template_key("research.{@1}.{@2}")


def test_keyed_template_renders_and_matches_like_a_bare_marker() -> None:
    assert render_agent_name_template("research.{@1}.cdx", "o") == "research.o.cdx"
    assert render_agent_name_template("foo{@1}", "o") == "foo-o"
    assert render_agent_name_template("{@1}.cdx", "o") == "o.cdx"
    assert match_agent_name_template("research.{@1}.cdx", "research.o.cdx") == "o"
    assert match_agent_name_template("research.{@1}.cdx", "other.o.cdx") is None


def test_keyed_template_namespace_keeps_the_marker() -> None:
    assert (
        agent_name_template_namespace_template("research.{@1}.cdx") == "research.{@1}"
    )
    assert render_agent_name_template_namespace("research.{@1}.cdx", "o") == (
        "research.o"
    )


def test_keyed_value_is_recognized_as_a_template() -> None:
    assert is_agent_name_template("research.{@1}.cdx") is True
    assert is_agent_name_template("research.{@1!}") is True
    assert is_agent_name_template("research.cdx") is False


def test_iter_key_markers_finds_prose_and_directive_occurrences() -> None:
    text = "%id:research.{@1}.cdx reads `research.{@1}.cld` then bare @ wins"

    markers = iter_agent_name_key_markers(text)

    assert [marker.id for marker in markers] == ["1", "1", None]
    assert [marker.braced for marker in markers] == [True, True, False]
    assert all(text[marker.start : marker.end] == "{@1}" for marker in markers[:2])
    assert text[markers[2].start : markers[2].end] == "@"


def test_iter_key_markers_reports_qualification() -> None:
    markers = iter_agent_name_key_markers("{@a} and {@b!}")

    assert [(marker.id, marker.qualified) for marker in markers] == [
        ("a", False),
        ("b", True),
    ]


def test_iter_key_markers_ignores_non_marker_braces() -> None:
    assert iter_agent_name_key_markers("{{ prompt }} {@} { @1 } {@-bad}") == []
