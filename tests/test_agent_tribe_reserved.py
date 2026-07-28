"""Reserved pseudo-tribe names and where they are (and are not) rejected."""

from __future__ import annotations

import pytest

from sase.core.agent_tribe import (
    RESERVED_DEFAULT_TRIBE,
    RESERVED_TRIBE_NAMES,
    is_reserved_tribe_name,
    parse_tribe_reference,
    reserved_tribe_target_reason,
    validate_tribe_name,
)


def test_default_is_the_reserved_pseudo_tribe() -> None:
    assert RESERVED_DEFAULT_TRIBE == "default"
    assert RESERVED_TRIBE_NAMES == frozenset({"default"})
    assert is_reserved_tribe_name("default")


@pytest.mark.parametrize("tribe", ["epic", "Default", "default-2", "defaults", ""])
def test_named_tribes_are_not_reserved(tribe: str) -> None:
    assert not is_reserved_tribe_name(tribe)


def test_reserved_name_stays_valid_for_storage_and_classification() -> None:
    """The guard is scoped to *targets*; validation and parsing are unchanged.

    ``validate_tribe_name`` is applied to stored artifact values and to
    ``tribes.default`` display config, and ``parse_tribe_reference`` is used
    as a plain "is this a tribe reference?" classifier at call sites with no
    error handling.  Neither may start rejecting the reserved name.
    """
    assert validate_tribe_name("default") == "default"
    assert parse_tribe_reference("@default") == "default"


def test_reserved_target_reason_names_the_panel() -> None:
    reason = reserved_tribe_target_reason("default")

    assert "reserved @default panel" in reason
    assert "never resolve" in reason
