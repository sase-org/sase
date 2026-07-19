"""Tests for pure prompt directive rewrite helpers."""

from __future__ import annotations

from unittest.mock import patch

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
