"""Pure, snapshot-driven tribe wait binding."""

from __future__ import annotations

from sase.core.wait_dependency_resolution import (
    TribeMemberRow,
    resolve_tribe_wait_binding,
)


def _row(
    name: str,
    timestamp: str,
    *,
    tribe: str | None = "epic",
    identity: str | None = None,
    clan: str | None = None,
    generation: str | None = None,
    effective_clan_tribe: str | None = None,
    complete: bool = True,
    terminal: bool | None = None,
) -> TribeMemberRow:
    return TribeMemberRow(
        tribe=tribe,
        launch_timestamp=timestamp,
        identity=identity or name,
        name=name,
        clan_name=clan,
        clan_generation=generation,
        effective_clan_tribe=effective_clan_tribe,
        is_complete=complete,
        is_terminal=complete if terminal is None else terminal,
    )


def test_binding_requires_strictly_new_entity_and_excludes_self() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row("older", "20260718010000"),
            _row("cutoff", "20260718020000"),
            _row("self", "20260718021000", identity="self-dir"),
            _row("next", "20260718022000"),
        ],
        newer_than="20260718020000",
        exclude_identity="self-dir",
    )

    assert binding.state == "bound"
    assert binding.kind == "agent"
    assert binding.identity == "next"
    assert binding.name == "next"


def test_binding_selects_earliest_complete_entity() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row(
                "failed",
                "20260718021000",
                complete=False,
                terminal=True,
            ),
            _row("later", "20260718024000"),
            _row("earliest", "20260718022000"),
        ],
        newer_than="20260718020000",
    )

    assert binding.state == "bound"
    assert binding.name == "earliest"
    assert binding.timestamp == "20260718022000"


def test_direct_clan_member_enrolls_whole_generation() -> None:
    rows = [
        _row(
            "review.one",
            "20260718021000",
            clan="review",
            generation="generation-1",
        ),
        _row(
            "review.two",
            "20260718022000",
            tribe=None,
            clan="review",
            generation="generation-1",
            complete=False,
        ),
    ]

    pending = resolve_tribe_wait_binding(
        "epic",
        rows,
        newer_than="20260718020000",
    )

    assert pending.state == "pending"
    assert pending.kind == "clan"
    assert pending.name == "review"
    assert pending.generation == "generation-1"
    assert pending.timestamp == "20260718021000"

    bound = resolve_tribe_wait_binding(
        "epic",
        [
            rows[0],
            _row(
                "review.two",
                "20260718022000",
                tribe=None,
                clan="review",
                generation="generation-1",
            ),
        ],
        newer_than="20260718020000",
    )

    assert bound.state == "bound"
    assert bound.kind == "clan"
    assert bound.name == "review"


def test_effective_clan_tribe_enrolls_generation() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row(
                "review.one",
                "20260718021000",
                tribe=None,
                clan="review",
                generation="generation-1",
                effective_clan_tribe="epic",
            ),
            _row(
                "review.two",
                "20260718022000",
                tribe=None,
                clan="review",
                generation="generation-1",
            ),
        ],
        newer_than="20260718020000",
    )

    assert binding.state == "bound"
    assert binding.kind == "clan"
    assert binding.timestamp == "20260718021000"


def test_excluding_one_clan_member_excludes_the_generation() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row(
                "review.one",
                "20260718021000",
                identity="review-one-dir",
                clan="review",
                generation="generation-1",
            ),
            _row(
                "review.two",
                "20260718022000",
                tribe=None,
                identity="review-two-dir",
                clan="review",
                generation="generation-1",
            ),
        ],
        newer_than="20260718020000",
        exclude_identity="review-one-dir",
    )

    assert binding.state == "pending"
    assert binding.kind is None


def test_binding_uses_timestamp_kind_and_name_tie_break() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row("zeta", "20260718021000"),
            _row("alpha", "20260718021000"),
            _row(
                "review.one",
                "20260718021000",
                clan="review",
                generation="generation-1",
            ),
        ],
        newer_than="20260718020000",
    )

    assert binding.state == "bound"
    assert binding.kind == "agent"
    assert binding.name == "alpha"


def test_pending_binding_has_no_entity_when_nothing_qualifies() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [_row("at-cutoff", "20260718020000")],
        newer_than="20260718020000",
    )

    assert binding.state == "pending"
    assert binding.kind is None
    assert binding.name is None


def test_pending_binding_exposes_earliest_in_flight_entity() -> None:
    binding = resolve_tribe_wait_binding(
        "epic",
        [
            _row("later", "20260718022000", complete=False),
            _row(
                "earliest",
                "20260718021000",
                complete=False,
                terminal=True,
            ),
        ],
        newer_than="20260718020000",
    )

    assert binding.state == "pending"
    assert binding.kind == "agent"
    assert binding.name == "earliest"
    assert binding.is_terminal


def test_reserved_tribe_is_classified_without_reading_rows() -> None:
    binding = resolve_tribe_wait_binding(
        "default",
        (_row("should-not-bind", "20260718021000", tribe="default"),),
        newer_than="20260718020000",
    )

    assert binding.state == "reserved"
    assert binding.kind is None
