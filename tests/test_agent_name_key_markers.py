"""Launch-time resolution tests for keyed agent-name markers."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.agent_name_keys import (
    has_unresolved_agent_name_key_marker,
    resolve_agent_name_key_markers,
)


def _configure_allocation(
    monkeypatch: pytest.MonkeyPatch,
    tokens: Iterable[str],
    *,
    reserved: set[str] | None = None,
    clans: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.agent_name_allocation_lock",
        nullcontext,
    )
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_reserved_agent_names",
        lambda: set(reserved or ()),
    )
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_reserved_clan_names",
        lambda: set(clans or ()),
    )
    token_values = tuple(tokens)
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.iter_agent_name_template_tokens",
        lambda: iter(token_values),
    )


def test_shared_key_uses_one_token_and_distinct_keys_use_different_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(monkeypatch, ["0", "1", "2"])

    resolved = resolve_agent_name_key_markers(
        [
            "%id:research.{@lead!}.cdx\n%clan:research.{@lead!}",
            "%id:research.{@lead!}.cld\n%wait:research.{@lead!}.cdx",
            "%id:research.{@other!}.image",
        ]
    )

    assert resolved == [
        "%id:research.0.cdx\n%clan:research.0",
        "%id:research.0.cld\n%wait:research.0.cdx",
        "%id:research.1.image",
    ]


def test_namespace_occupancy_skips_an_apparently_free_hood(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(
        monkeypatch,
        ["0", "1"],
        reserved={"research.0.cdx"},
    )

    assert resolve_agent_name_key_markers(
        ["%id:research.{@1!}.image\n%clan:research.{@1!}"]
    ) == ["%id:research.1.image\n%clan:research.1"]


def test_separator_rule_for_letter_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_allocation(monkeypatch, ["o"])

    assert resolve_agent_name_key_markers(["research.{@1!}\nfoo{@1!}\n{@1!}"]) == [
        "research.o\nfoo-o\no"
    ]


def test_separator_rule_for_digit_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_allocation(monkeypatch, ["0"])

    assert resolve_agent_name_key_markers(["foo{@1!}"]) == ["foo0"]


def test_every_prompt_context_is_rewritten_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(monkeypatch, ["o"])
    prompt = (
        "%id:research.{@1!}.cdx\n"
        "%clan(research.{@1!}, tribe=research)\n"
        "%id(image, clan=research.{@1!})\n"
        "%wait:research.{@1!}.final\n"
        "#fork:research.{@1!}.final\n"
        "Read `research.{@1!}.cdx` before continuing."
    )

    assert resolve_agent_name_key_markers([prompt]) == [
        "%id:research.o.cdx\n"
        "%clan(research.o, tribe=research)\n"
        "%id(image, clan=research.o)\n"
        "%wait:research.o.final\n"
        "#fork:research.o.final\n"
        "Read `research.o.cdx` before continuing."
    ]


def test_fenced_and_disabled_regions_remain_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(monkeypatch, ["o"])
    prompt = (
        "outside research.{@1!}\n"
        "```\ninside research.{@1!}\n```\n"
        "%xprompts_enabled:false\n"
        "disabled research.{@1!}\n"
        "%xprompts_enabled:true\n"
    )

    assert resolve_agent_name_key_markers([prompt]) == [
        "outside research.o\n"
        "```\ninside research.{@1!}\n```\n"
        "%xprompts_enabled:false\n"
        "disabled research.{@1!}\n"
        "%xprompts_enabled:true\n"
    ]


def test_unicode_before_marker_uses_rust_byte_offsets_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(monkeypatch, ["o"])

    assert resolve_agent_name_key_markers(["Résumé: research.{@1!}"]) == [
        "Résumé: research.o"
    ]


def test_resolution_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_allocation(monkeypatch, ["o"])
    first = resolve_agent_name_key_markers(["%id:research.{@1!}.cdx"])

    assert resolve_agent_name_key_markers(first) == first


def test_unresolved_guard_ignores_literal_regions() -> None:
    assert has_unresolved_agent_name_key_marker("run {@1!}") is True
    assert has_unresolved_agent_name_key_marker("```\n{@1!}\n```") is False
    assert (
        has_unresolved_agent_name_key_marker(
            "%xprompts_enabled:false\n{@1!}\n%xprompts_enabled:true\n"
        )
        is False
    )


def test_runner_rejects_a_marker_skipped_by_parent(
    tmp_path: Path,
) -> None:
    from tests._agent_names_extract_fixtures import run_extract

    with pytest.raises(
        RuntimeError,
        match="parent launch pipeline failed to resolve keyed markers",
    ):
        run_extract(tmp_path, prompt="%id:research.o.image\nDo {@1!}")


def test_concrete_clan_target_cannot_be_stolen_by_a_later_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.clan_membership import _resolve_clan_target

    _configure_allocation(monkeypatch, ["o"])
    deferred = resolve_agent_name_key_markers(["%id(image, clan=research.{@1!})"])[0]
    concrete_target = deferred.split("clan=", 1)[1].rstrip(")")

    with patch(
        "sase.agent.names.get_reserved_clan_names",
        return_value={"research.o", "research.p"},
    ):
        assert (
            _resolve_clan_target(
                "research.@",
                create_only=False,
                member_name="research.o.image",
                member_name_template=None,
            )
            == "research.p"
        )
        assert (
            _resolve_clan_target(
                concrete_target,
                create_only=False,
                member_name="research.o.image",
                member_name_template=None,
            )
            == "research.o"
        )
