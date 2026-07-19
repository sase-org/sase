"""Tests for rootless agent-clan prompt directives."""

from __future__ import annotations

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


@pytest.mark.parametrize(
    ("source", "clan"),
    [
        ("%clan:sase-6g", "sase-6g"),
        ("%clan:research.@", "research.@"),
        ("%c:research.@", "research.@"),
    ],
)
def test_clan_directive_parses_colon_name(source: str, clan: str) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nDo work")

    assert cleaned == "Do work"
    assert directives.clan == clan
    assert directives.clan_declared is True
    assert directives.clan_tribe is None


@pytest.mark.parametrize("directive", ["clan", "c"])
def test_clan_directive_parses_parenthesized_tribe(directive: str) -> None:
    cleaned, directives = extract_prompt_directives(
        f"%{directive}(research.@, tribe=research)\nDo work"
    )

    assert cleaned == "Do work"
    assert directives.clan == "research.@"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "research"
    assert directives.tribe is None


def test_clan_directive_allows_plain_name_directive() -> None:
    _, directives = extract_prompt_directives(
        "%i:research.worker\n%clan:research\nDo work"
    )

    assert directives.name == "research.worker"
    assert directives.clan == "research"


@pytest.mark.parametrize(
    ("source", "name", "clan"),
    [
        ("%id(worker, clan=research)", "research.worker", "research"),
        ("%i(a.b, clan=review)", "review.a.b", "review"),
    ],
)
def test_id_clan_keyword_derives_member_name(
    source: str,
    name: str,
    clan: str,
) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nDo work")

    assert cleaned == "Do work"
    assert directives.name == name
    assert directives.name_explicit is True
    assert directives.name_force_reuse is False
    assert directives.clan == clan
    assert directives.clan_declared is False
    assert directives.clan_tribe is None


def test_id_clan_keyword_preserves_force_reuse() -> None:
    _, directives = extract_prompt_directives("%id(!worker, clan=research)\nDo work")

    assert directives.name == "research.worker"
    assert directives.name_force_reuse is True
    assert directives.clan == "research"


def test_id_clan_keyword_derives_template_metadata() -> None:
    _, directives = extract_prompt_directives("%id(cld, clan=research.@)\nDo work")

    assert directives.name == "research.@.cld"
    assert directives.clan == "research.@"
    assert directives.name_template == "research.@.cld"
    assert directives.name_template_base == "research.cld"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "research.cld"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("%id(clan=research)", "requires exactly one positional member id"),
        ("%id(!, clan=research)", "requires a non-empty member id"),
        ("%id(worker, clan=)", "requires a non-empty clan name"),
        (
            "%id(parent, reviewer, clan=research)",
            "positional family form",
        ),
        (
            "%id(worker, clan=research, clan=other)",
            "Duplicate keyword argument 'clan'",
        ),
        ("%id(worker, tribe=research)", "tribe= keyword.*not supported yet"),
    ],
)
def test_id_clan_keyword_rejects_invalid_argument_shapes(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=message):
        extract_prompt_directives(f"{source}\nDo work")


def test_id_clan_keyword_rejects_multiple_template_markers() -> None:
    with pytest.raises(DirectiveError, match="exactly one '@' marker"):
        extract_prompt_directives("%id(@, clan=research.@)\nDo work")


@pytest.mark.parametrize(
    "prompt",
    [
        "%id(worker, clan=research)\n%tribe:review\nDo work",
        "%tribe:review\n%i(worker, clan=research)\nDo work",
    ],
)
def test_id_clan_keyword_conflicts_with_tribe(prompt: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"joining a clan joins its tribe.*Put tribe= on the clan's %clan",
    ):
        extract_prompt_directives(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "%id(worker, clan=research)\n%clan:research\nDo work",
        "%clan:research\n%i(worker, clan=research)\nDo work",
    ],
)
def test_id_clan_keyword_conflicts_with_clan_declaration(prompt: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"Cannot combine %clan with %id\(\.\.\., clan=\.\.\.\)",
    ):
        extract_prompt_directives(prompt)


@pytest.mark.parametrize("source", ["%clan", "%clan:"])
def test_clan_directive_rejects_empty_name(source: str) -> None:
    with pytest.raises(DirectiveError, match="requires a clan name argument"):
        extract_prompt_directives(f"{source}\nDo work")


def test_clan_directive_parenthesized_name_without_tribe() -> None:
    _, directives = extract_prompt_directives("%clan(foo)\nDo work")

    assert directives.clan == "foo"
    assert directives.clan_tribe is None


def test_clan_directive_rejects_plus_form() -> None:
    with pytest.raises(DirectiveError, match="does not support '\\+'"):
        extract_prompt_directives("%clan+\nDo work")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("%clan(tribe=research)", "requires a clan name"),
        ("%clan(foo, tribe=)", "requires a non-empty tribe"),
        ("%clan(foo, tribe=a, tribe=b)", "Duplicate keyword argument 'tribe'"),
        ("%clan(foo, color=blue)", "Unsupported keyword on %clan: color="),
        ("%clan(foo, bar, tribe=research)", "exactly one positional"),
        ("%clan(foo, tribe=has+space)", "Invalid '%clan' tribe= value"),
        ("%clan(foo, tribe=research", "missing closing"),
    ],
)
def test_clan_directive_rejects_invalid_argument_shapes(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=message):
        extract_prompt_directives(f"{source}\nDo work")


@pytest.mark.parametrize(
    "prompt",
    [
        f"{first}\n{second}\nDo work"
        for clan_alias in ("clan", "c")
        for tribe_alias in ("tribe", "t")
        for clan_form in (f"%{clan_alias}:foo", f"%{clan_alias}(foo)")
        for tribe_form in (
            f"%{tribe_alias}:research",
            f"%{tribe_alias}(research)",
        )
        for first, second in (
            (clan_form, tribe_form),
            (tribe_form, clan_form),
        )
    ],
)
def test_clan_directive_conflicts_with_standalone_tribe(prompt: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"Cannot combine %tribe with %clan; use %clan\(<clan>, tribe=<tribe>\)",
    ):
        extract_prompt_directives(prompt)


def test_clan_directive_rejects_duplicate_alias_occurrence() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%clan'"):
        extract_prompt_directives("%clan:root\n%c:other\nDo work")


def test_clan_directive_conflicts_with_serial_family_attach() -> None:
    prompt = "%i(reviewer, family=parent)\n%clan:parent\nDo work"

    with pytest.raises(
        DirectiveError,
        match=r"Cannot combine %clan with %id\(\.\.\., family=\.\.\.\)",
    ):
        extract_prompt_directives(prompt)


def test_removed_family_directives_are_not_recognized() -> None:
    prompt = "%family:example\n%f:example\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None


def test_clan_directive_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%clan:example\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None


def test_clan_tribe_conflict_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%clan:example\n%tribe:research\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None
    assert directives.tribe is None


def test_clan_directive_inside_disabled_region_is_ignored() -> None:
    prompt = "%xprompts_enabled:false\n%clan:example\n%xprompts_enabled:true\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example\nDo work"
    assert directives.clan is None


def test_clan_tribe_conflict_inside_disabled_region_is_ignored() -> None:
    prompt = (
        "%xprompts_enabled:false\n"
        "%clan:example\n%tribe:research\n"
        "%xprompts_enabled:true\nDo work"
    )

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example\n%tribe:research\nDo work"
    assert directives.clan is None
    assert directives.tribe is None
