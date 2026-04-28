"""Tests for the neutral per-group fold registry.

Mirrors ``test_agent_group_fold`` but exercises ``GroupFoldRegistry``
directly so we cover the type CL code will use without going through
the Agent-flavoured alias.
"""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.group_fold import GroupFoldRegistry


def test_agent_alias_is_the_neutral_class() -> None:
    """``AgentGroupFoldRegistry`` is preserved as a back-compat alias."""
    assert AgentGroupFoldRegistry is GroupFoldRegistry


def test_default_registry_has_no_collapsed_groups() -> None:
    registry = GroupFoldRegistry()
    assert registry.collapsed == set()
    assert registry.is_collapsed(("proj",)) is False


def test_collapse_returns_true_only_on_first_change() -> None:
    registry = GroupFoldRegistry()
    key: tuple[str, ...] = ("proj", "cl")
    assert registry.collapse(key) is True
    assert registry.collapse(key) is False
    assert registry.is_collapsed(key) is True


def test_expand_undoes_collapse_and_is_idempotent() -> None:
    registry = GroupFoldRegistry()
    key: tuple[str, ...] = ("proj", "cl")
    assert registry.expand(key) is False
    registry.collapse(key)
    assert registry.expand(key) is True
    assert registry.expand(key) is False


def test_clear_unknown_drops_stale_keys() -> None:
    registry = GroupFoldRegistry()
    stale: tuple[str, ...] = ("proj", "cl-old")
    live: tuple[str, ...] = ("proj", "cl-new")
    registry.collapse(stale)
    registry.collapse(live)
    registry.clear_unknown([live])
    assert registry.is_collapsed(stale) is False
    assert registry.is_collapsed(live) is True


def test_version_increments_only_on_real_mutation() -> None:
    registry = GroupFoldRegistry()
    assert registry.version == 0
    registry.collapse(("a",))
    assert registry.version == 1
    registry.collapse(("a",))  # idempotent
    assert registry.version == 1
    registry.expand(("a",))
    assert registry.version == 2
