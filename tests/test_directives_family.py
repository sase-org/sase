"""Tests for rootless agent-clan prompt directives."""

from __future__ import annotations

import pytest

from sase.agent.multi_prompt_reference_directives import extract_static_clan_directive
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            '%clan(research, summary="[bold]Research[/bold]")',
            "[bold]Research[/bold]",
        ),
        (
            "%clan(research, summary=[[ [bold]Research[/bold]\n  Second line ]])",
            "[bold]Research[/bold]\nSecond line",
        ),
    ],
)
def test_clan_directive_parses_literal_summary(
    source: str,
    expected: str,
) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nDo work")

    assert cleaned == "Do work"
    assert directives.clan == "research"
    assert directives.clan_summary == expected
    assert directives.clan_summary_script is None


def test_clan_directive_text_block_summary_ignores_inner_marker() -> None:
    summary = (
        "Use `[<web>:<keyword> [...]]` for example, then continue.\n"
        "Keep this comma, and the rest of the prose in the summary."
    )
    prompt = f"%clan(research, tribe=study, summary=[[{summary}]])\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)
    static = extract_static_clan_directive(prompt)

    assert cleaned == "Do work"
    assert directives.clan == "research"
    assert directives.clan_tribe == "study"
    assert directives.clan_summary == summary
    assert static is not None
    assert static.name == "research"
    assert static.tribe == "study"


def test_clan_directive_parses_summary_script_with_tribe() -> None:
    cleaned, directives = extract_prompt_directives(
        "%clan(research, tribe=study, summary_script=make_summary)\nDo work"
    )

    assert cleaned == "Do work"
    assert directives.clan_tribe == "study"
    assert directives.clan_summary is None
    assert directives.clan_summary_script == "make_summary"


def test_clan_colon_form_has_no_summary() -> None:
    _, directives = extract_prompt_directives("%clan:research\nDo work")

    assert directives.clan_summary is None
    assert directives.clan_summary_script is None


def test_clan_joiner_cannot_declare_summary() -> None:
    with pytest.raises(DirectiveError, match="Unsupported keyword.*summary"):
        extract_prompt_directives("%id(worker, clan=research, summary=nope)\nDo work")


@pytest.mark.parametrize("directive", ["clan", "c"])
def test_clan_double_colon_shorthand_parses_colon_form(directive: str) -> None:
    cleaned, directives = extract_prompt_directives(
        f"%{directive}:research:: [bold]Research[/bold]\nSecond line"
    )

    assert cleaned == ""
    assert directives.clan == "research"
    assert directives.clan_summary == "[bold]Research[/bold]\nSecond line"


def test_clan_double_colon_shorthand_parses_parenthesized_form() -> None:
    prompt = (
        "%clan(research, tribe=study):: First line\nSecond line\n%model:opus\nDo work"
    )

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Do work"
    assert directives.clan == "research"
    assert directives.clan_tribe == "study"
    assert directives.clan_summary == "First line\nSecond line"
    assert directives.model == "opus"


def test_clan_double_colon_shorthand_stops_at_xprompt_boundary() -> None:
    prompt = "%clan:research:: First paragraph\n\nSecond paragraph\n#next\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "#next\nDo work"
    assert directives.clan_summary == "First paragraph\n\nSecond paragraph"


def test_clan_double_colon_shorthand_ignores_boundaries_in_fenced_code() -> None:
    prompt = (
        "%clan:research:: Example:\n"
        "```text\n%model:inside\n#inside\n```\n"
        "After the example\n%model:opus\nDo work"
    )

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Do work"
    assert directives.model == "opus"
    assert directives.clan_summary == (
        "Example:\n```text\n%model:inside\n#inside\n```\nAfter the example"
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "%clan(research, summary=literal):: shorthand",
            "Cannot combine.*shorthand.*summary=",
        ),
        (
            "%clan(research, summary_script=build):: shorthand",
            "Cannot combine.*shorthand.*summary_script=",
        ),
    ],
)
def test_clan_double_colon_shorthand_rejects_explicit_summary_arguments(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=message):
        extract_prompt_directives(source)


def test_non_allowlisted_directive_double_colon_is_not_rewritten() -> None:
    cleaned, directives = extract_prompt_directives("%id:worker:: notes")

    assert cleaned == ":: notes"
    assert directives.name == "worker"
    assert directives.clan_summary is None


@pytest.mark.parametrize(
    "prompt",
    [
        "%{%clan:one:: summary | plain}",
        "%(%clan:one:: summary, plain)",
    ],
)
def test_clan_double_colon_shorthand_inside_raw_alt_is_untouched(
    prompt: str,
) -> None:
    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None
    assert directives.clan_summary is None


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
        ("%id(!, tribe=research)", "requires a non-empty id"),
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


def test_id_tribe_keyword_conflicts_with_clan_declaration() -> None:
    with pytest.raises(
        DirectiveError,
        match=r"Cannot combine %clan with %id\(\.\.\., tribe=\.\.\.\)",
    ):
        extract_prompt_directives("%clan:research\n%id(worker, tribe=review)\nDo work")


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
        ("%clan(foo, summary=)", "summary=.*requires a non-empty value"),
        (
            "%clan(foo, summary_script=)",
            "summary_script=.*requires a non-empty value",
        ),
        (
            "%clan(foo, summary=literal, summary_script=build)",
            "summary= and summary_script= are mutually exclusive",
        ),
        (
            "%clan(foo, summary=one, summary=two)",
            "Duplicate keyword argument 'summary'",
        ),
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


def test_clan_double_colon_shorthand_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%clan:example:: hidden\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None
    assert directives.clan_summary is None


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


def test_clan_double_colon_shorthand_inside_disabled_region_is_ignored() -> None:
    prompt = (
        "%xprompts_enabled:false\n"
        "%clan:example:: hidden\n"
        "%xprompts_enabled:true\nDo work"
    )

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example:: hidden\nDo work"
    assert directives.clan is None
    assert directives.clan_summary is None


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
