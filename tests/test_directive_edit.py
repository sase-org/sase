"""Tests for pure prompt directive rewrite helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.xprompt.directive_edit import (
    PromptWaitDirective,
    demote_prompt_clan_declaration,
    prompt_declares_clan,
    rewrite_prompt_clan_member_name,
    set_prompt_auto_mode,
    set_prompt_clan_tribe,
    set_prompt_name,
    set_prompt_tribe,
    set_prompt_wait,
)
from sase.xprompt.directives import extract_prompt_directives


def test_set_prompt_name_inserts_when_absent() -> None:
    assert set_prompt_name("Do work", "reviewer") == "%id:reviewer\nDo work"


def test_set_prompt_name_replaces_long_form() -> None:
    assert set_prompt_name("%id:old\nDo work", "new") == "%id:new\nDo work"


def test_set_prompt_name_replaces_alias_without_touching_tribe() -> None:
    prompt = "%i(old, tribe=batch)\nDo work"
    assert set_prompt_name(prompt, "new") == "%id(new, tribe=batch)\nDo work"


def test_demote_prompt_clan_declaration_rewrites_id_and_drops_tribe() -> None:
    prompt = "%id:!research.worker.r0\n%clan(research, tribe=review)\nDo work"

    assert demote_prompt_clan_declaration(prompt) == (
        "%id(!worker.r0, clan=research)\nDo work"
    )


def test_demote_prompt_clan_declaration_leaves_joiner_unchanged() -> None:
    prompt = "%id(worker, clan=research)\nDo work"
    assert demote_prompt_clan_declaration(prompt) == prompt


def test_demote_prompt_clan_template_declaration_preserves_template() -> None:
    prompt = "%id:research.@.lead\n%clan(research.@, tribe=review)\nDo work"

    assert demote_prompt_clan_declaration(prompt) == (
        "%id(lead, clan=research.@)\nDo work"
    )


def test_demote_prompt_clan_declaration_removes_shorthand_summary() -> None:
    prompt = (
        "%id:research.worker\n"
        "%clan:research:: [bold]Research[/bold]\n"
        "Second paragraph\n\n"
        "%model:opus\n"
        "Do work"
    )

    assert demote_prompt_clan_declaration(prompt) == (
        "%id(worker, clan=research)\n%model:opus\nDo work"
    )


def test_demote_prompt_clan_declaration_removes_multiline_summary_arg() -> None:
    prompt = (
        "%id:research.worker\n"
        "%clan(research, summary=[[\n"
        "  [bold]Research[/bold]\n"
        "  Second line\n"
        "]])\n"
        "Do work"
    )

    assert demote_prompt_clan_declaration(prompt) == (
        "%id(worker, clan=research)\nDo work"
    )


def test_rewrite_prompt_clan_member_name_resolves_template() -> None:
    prompt = "%id(worker, clan=research.@)\nDo work"

    assert (
        rewrite_prompt_clan_member_name(
            prompt,
            "research.2.worker.r0",
            current_agent_name="research.2.worker",
        )
        == "%id(worker.r0, clan=research.2)\nDo work"
    )


def test_rewrite_prompt_clan_member_name_removes_shorthand_summary() -> None:
    prompt = (
        "%id:research.worker\n"
        "%clan(research, tribe=study):: First line\n"
        "Second line\n"
        "#next\n"
        "Do work"
    )

    assert rewrite_prompt_clan_member_name(prompt, "research.worker.r0") == (
        "%id(worker.r0, clan=research)\n#next\nDo work"
    )


def test_prompt_declares_clan_ignores_joiner_and_protected_examples() -> None:
    assert prompt_declares_clan("%clan:research\nDo work") is True
    assert prompt_declares_clan("%id(worker, clan=research)\nDo work") is False
    assert prompt_declares_clan("```text\n%clan:example\n```\nDo work") is False


def test_set_prompt_tribe_set_and_unset_alias() -> None:
    assert set_prompt_tribe("%t:old\nDo work", "triage") == (
        "%id(tribe=triage)\nDo work"
    )
    assert set_prompt_tribe("%id(tribe=triage)\nDo work", None) == "Do work"


def test_set_prompt_tribe_updates_existing_id_keyword() -> None:
    assert set_prompt_tribe("%id:worker\nDo work", "triage") == (
        "%id(worker, tribe=triage)\nDo work"
    )
    assert set_prompt_tribe("%i(worker, tribe=old)\nDo work", "triage") == (
        "%id(worker, tribe=triage)\nDo work"
    )
    assert set_prompt_tribe("%id(worker, tribe=triage)\nDo work", None) == (
        "%id:worker\nDo work"
    )


def test_set_prompt_tribe_migrates_removed_group_spellings() -> None:
    prompt = "%group:old\n%g:older\nDo work"
    assert set_prompt_tribe(prompt, "triage") == "%id(tribe=triage)\nDo work"


def test_set_prompt_clan_tribe_adds_replaces_and_removes_keyword() -> None:
    assert set_prompt_clan_tribe("%clan:review\nDo work", "quality") == (
        "%clan(review, tribe=quality)\nDo work"
    )
    assert (
        set_prompt_clan_tribe("%c(review, tribe=old)\nDo work", "quality")
        == "%clan(review, tribe=quality)\nDo work"
    )
    assert (
        set_prompt_clan_tribe("%clan(review, tribe=quality)\nDo work", None)
        == "%clan(review)\nDo work"
    )


@pytest.mark.parametrize(
    "summary_arg",
    [
        'summary="[bold]Review, findings[/bold]"',
        "summary=[[ [bold]Review[/bold] ]]",
        "summary=[[\n    [bold]Review[/bold]\n      Nested detail\n]]",
        "summary_script=sase_clan_summary_epic",
    ],
)
def test_set_prompt_clan_tribe_preserves_summary_arguments_verbatim(
    summary_arg: str,
) -> None:
    without_tribe = f"%clan(review, {summary_arg})\nDo work"
    with_old_tribe = f"%clan(review, tribe=old, {summary_arg})\nDo work"

    added = set_prompt_clan_tribe(without_tribe, "quality")
    replaced = set_prompt_clan_tribe(with_old_tribe, "quality")
    removed = set_prompt_clan_tribe(replaced, None)

    assert added == f"%clan(review, tribe=quality, {summary_arg})\nDo work"
    assert replaced == added
    assert removed == without_tribe

    _, original_directives = extract_prompt_directives(without_tribe)
    for rewritten in (added, replaced, removed):
        _, directives = extract_prompt_directives(rewritten)
        assert directives.clan_summary == original_directives.clan_summary
        assert directives.clan_summary_script == original_directives.clan_summary_script


def test_set_prompt_clan_tribe_round_trips_epic_declaration() -> None:
    prompt = (
        "%clan(sase-7r, tribe=epic, summary_script=sase_clan_summary_epic)\nDo work"
    )

    assert set_prompt_clan_tribe(prompt, "landed") == (
        "%clan(sase-7r, tribe=landed, summary_script=sase_clan_summary_epic)\nDo work"
    )


def test_set_prompt_clan_tribe_validates_summary_keyword_contract() -> None:
    with pytest.raises(ValueError, match="unsupported keyword.*mystery="):
        set_prompt_clan_tribe("%clan(review, mystery=value)", "quality")
    with pytest.raises(ValueError, match="Duplicate keyword argument 'summary'"):
        set_prompt_clan_tribe(
            "%clan(review, summary=one, summary=two)",
            "quality",
        )
    with pytest.raises(ValueError, match="summary= and summary_script=.*exclusive"):
        set_prompt_clan_tribe(
            "%clan(review, summary=one, summary_script=build)",
            "quality",
        )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (
            "%c:review:: [bold]Review[/bold]\nSecond line",
            "%clan(review, tribe=quality):: [bold]Review[/bold]\nSecond line",
        ),
        (
            "%c(review, tribe=old):: [bold]Review[/bold]\nSecond line",
            "%clan(review, tribe=quality):: [bold]Review[/bold]\nSecond line",
        ),
    ],
)
def test_set_prompt_clan_tribe_preserves_shorthand_summary(
    prompt: str,
    expected: str,
) -> None:
    _, original_directives = extract_prompt_directives(prompt)

    rewritten = set_prompt_clan_tribe(prompt, "quality")

    assert rewritten == expected
    _, directives = extract_prompt_directives(rewritten)
    assert directives.clan_summary == original_directives.clan_summary


def test_set_prompt_clan_tribe_preserves_ignored_regions() -> None:
    prompt = (
        "%clan:review\n"
        "```text\n%clan(example, tribe=literal)\n```\n"
        "%xprompts_enabled:false\n%clan:disabled\n%xprompts_enabled:true\n"
        "Do work"
    )

    assert set_prompt_clan_tribe(prompt, "quality") == prompt.replace(
        "%clan:review", "%clan(review, tribe=quality)", 1
    )


def test_set_prompt_tribe_routes_clan_launches_to_clan_keyword() -> None:
    assert set_prompt_tribe("%clan:review\nDo work", "quality") == (
        "%clan(review, tribe=quality)\nDo work"
    )
    assert (
        set_prompt_tribe(
            "%tribe:legacy\n%clan:review\nDo work",
            "quality",
        )
        == "%clan(review, tribe=quality)\nDo work"
    )


def test_set_prompt_auto_mode_canonical_forms() -> None:
    assert set_prompt_auto_mode("%a:tale\nDo work", "plan") == "%auto\nDo work"
    assert set_prompt_auto_mode("%auto\nDo work", "epic") == "%auto:epic\nDo work"
    assert set_prompt_auto_mode("%auto:epic\nDo work", None) == "Do work"


def test_set_prompt_wait_replaces_alias_and_time_forms() -> None:
    prompt = "%w:old\n#t:5m\n%time:1h\nDo work"
    rewritten = set_prompt_wait(
        prompt,
        PromptWaitDirective(agents=("dep",), time_token="10m"),
    )
    assert rewritten == "%wait(dep, time=10m)\nDo work"
    with patch("sase.agent.names.is_agent_name_template", return_value=False):
        _, directives = extract_prompt_directives(rewritten)
    assert directives.wait == ["dep"]
    assert directives.wait_duration == 600.0


def test_set_prompt_wait_replaces_inline_wait_and_time_forms() -> None:
    prompt = "%w:old #t:5m %time:1430 Do work"
    rewritten = set_prompt_wait(
        prompt,
        PromptWaitDirective(agents=("dep",), time_token="10m"),
    )

    assert rewritten == "%wait(dep, time=10m)\nDo work"


def test_set_prompt_wait_clears_wait_directives() -> None:
    assert set_prompt_wait("%wait(dep, time=5m)\nDo work", None) == "Do work"


def test_set_prompt_wait_formats_runner_threshold() -> None:
    rewritten = set_prompt_wait(
        "Do work",
        PromptWaitDirective(agents=("dep",), time_token="5m", runners=0),
    )

    assert rewritten == "%wait(dep, time=5m, runners=0)\nDo work"


def test_set_prompt_wait_formats_and_round_trips_bead_only_conditions() -> None:
    rewritten = set_prompt_wait(
        "Do work",
        PromptWaitDirective(beads=("sase-87.1", "sase-87.2")),
    )

    assert rewritten == ("%wait(bead=sase-87.1)\n%wait(bead=sase-87.2)\nDo work")
    _, directives = extract_prompt_directives(rewritten)
    assert directives.wait == []
    assert directives.wait_beads == ["sase-87.1", "sase-87.2"]


def test_set_prompt_wait_formats_and_round_trips_mixed_conditions() -> None:
    rewritten = set_prompt_wait(
        "%w(bead=old)\nDo work",
        PromptWaitDirective(
            agents=("dep",),
            time_token="5m",
            runners=0,
            beads=("sase-87.1", "sase-87.2"),
        ),
    )

    assert rewritten == (
        "%wait(dep, time=5m, runners=0)\n"
        "%wait(bead=sase-87.1)\n"
        "%wait(bead=sase-87.2)\n"
        "Do work"
    )
    _, directives = extract_prompt_directives(rewritten)
    assert directives.wait == ["dep"]
    assert directives.wait_beads == ["sase-87.1", "sase-87.2"]
    assert directives.wait_duration == 300.0
    assert directives.wait_runners == 0


def test_set_prompt_wait_round_trips_tribe_reference() -> None:
    rewritten = set_prompt_wait(
        "%w:old\nDo work",
        PromptWaitDirective(agents=("@epic", "builder")),
    )

    assert rewritten == "%wait(@epic, builder)\nDo work"
    _, directives = extract_prompt_directives(rewritten)
    assert directives.wait == ["@epic", "builder"]


def test_insert_after_frontmatter() -> None:
    prompt = "---\ntitle: demo\n---\nDo work"
    assert set_prompt_name(prompt, "agent") == (
        "---\ntitle: demo\n---\n%id:agent\nDo work"
    )


def test_fenced_directives_are_not_rewritten() -> None:
    prompt = "Before\n```text\n%id:example\n```\nDo work"
    assert set_prompt_name(prompt, "real") == (
        "%id:real\nBefore\n```text\n%id:example\n```\nDo work"
    )


def test_disabled_region_directives_are_not_rewritten() -> None:
    prompt = "%xprompts_enabled:false\n%tribe:old\n%xprompts_enabled:true\nDo work"
    assert set_prompt_tribe(prompt, "new") == (
        "%id(tribe=new)\n"
        "%xprompts_enabled:false\n"
        "%tribe:old\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )


def test_alt_branch_directives_are_not_rewritten() -> None:
    prompt = "%alt(%id:a | %id:b)\nDo work"
    assert set_prompt_name(prompt, "real") == ("%id:real\n%alt(%id:a | %id:b)\nDo work")
