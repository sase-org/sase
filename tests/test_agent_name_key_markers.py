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
from sase.agent.multi_prompt_reference_directives import (
    extract_static_clan_directive,
    extract_static_name_directive,
)
from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
from sase.xprompt.loader_sources import load_xprompt_from_file
from tests._xprompt_swarm_helpers import patch_catalog


def _configure_allocation(
    monkeypatch: pytest.MonkeyPatch,
    tokens: Iterable[str],
    *,
    reserved: set[str] | None = None,
    clans: set[str] | None = None,
    blocked_roots: dict[str, dict[str, object]] | None = None,
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
    monkeypatch.setattr(
        "sase.agent.agent_name_keys.get_blocked_local_namespace_roots",
        lambda: dict(blocked_roots or {}),
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


def test_blocked_root_raises_directive_error_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permanently blocked base must fail fast, not retry every token forever.

    Before the oracle knew about blocked namespace roots, every token for a
    blocked base looked identically available, so the per-token loop never
    terminated. This must surface as one clear ``DirectiveError`` instead.
    """
    from sase.xprompt._exceptions import DirectiveError

    _configure_allocation(
        monkeypatch,
        ["0", "1", "2"],
        blocked_roots={
            "research": {
                "source_owner": {"username": "alice", "machine_name": "athena"}
            }
        },
    )

    with pytest.raises(DirectiveError, match="reserved owner namespace 'research'"):
        resolve_agent_name_key_markers(["%id:research.{@1!}.cdx\n%clan:research.{@1!}"])


def test_blocked_root_does_not_prevent_allocation_under_a_different_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_allocation(
        monkeypatch,
        ["0", "1"],
        blocked_roots={"research": {}},
    )

    assert resolve_agent_name_key_markers(
        ["%id:other.{@1!}.cdx\n%clan:other.{@1!}"]
    ) == ["%id:other.0.cdx\n%clan:other.0"]


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


def test_checked_in_reads_swarm_declares_one_clan_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every #sase/reads invocation puts its four agents in one reads-<token> clan."""
    reads_path = Path(__file__).resolve().parents[1] / "sase" / "xprompts" / "reads.md"
    source = reads_path.read_text(encoding="utf-8")
    assert "%g:" not in source
    assert "reads.{@1}" not in source

    reads = load_xprompt_from_file(reads_path)
    assert reads is not None
    with patch_catalog({"reads": reads}):
        records = expand_xprompt_swarms_with_metadata(
            ["#reads(episodic agent memory)", "#reads(context rot)"]
        )

    _configure_allocation(monkeypatch, ["0", "1"])
    resolved = resolve_agent_name_key_markers([record.prompt for record in records])
    assert len(resolved) == 8

    for invocation, clan_name in ((resolved[:4], "reads-0"), (resolved[4:], "reads-1")):
        clans = []
        for segment in invocation:
            clan = extract_static_clan_directive(segment)
            assert clan is not None
            clans.append(clan)
        assert {clan.name for clan in clans} == {clan_name}
        assert [clan.declared for clan in clans] == [True, False, False, False]
        assert all(clan.tribe is None for clan in clans)
        assert [extract_static_name_directive(segment) for segment in invocation] == [
            f"{clan_name}.agy",
            f"{clan_name}.cld",
            f"{clan_name}.cdx",
            f"{clan_name}.final",
        ]
        for suffix in ("agy", "cld", "cdx"):
            assert f"%wait:{clan_name}.{suffix}" in invocation[3]
