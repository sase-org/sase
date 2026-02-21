"""Tests for the axe chop registry module."""

from sase.axe.chop_registry import (
    ChopContext,
    _CHOPS,
    _ensure_chops_loaded,
    get_all_chops,
    get_chop,
    list_chops,
    register_chop,
)

# All 11 expected chop names
EXPECTED_CHOPS = sorted(
    [
        "hook_checks",
        "mentor_checks",
        "workflow_checks",
        "pending_checks_poll",
        "comment_zombie_checks",
        "suffix_transforms",
        "orphan_cleanup",
        "stale_running_cleanup",
        "cl_submitted_checks",
        "comment_checks",
        "error_digest",
    ]
)


def test_list_chops_returns_all_11_names() -> None:
    """list_chops() should return all 11 registered chop names."""
    names = list_chops()
    assert names == EXPECTED_CHOPS


def test_get_chop_returns_callable_for_each() -> None:
    """get_chop(name) should return a callable for every registered chop."""
    for name in EXPECTED_CHOPS:
        chop = get_chop(name)
        assert callable(chop)


def test_get_chop_raises_key_error_for_unknown() -> None:
    """get_chop() should raise KeyError for an unregistered name."""
    import pytest

    with pytest.raises(KeyError, match="nonexistent"):
        get_chop("nonexistent")


def test_get_all_chops_returns_dict_with_11_entries() -> None:
    """get_all_chops() should return a dict with 11 entries."""
    all_chops = get_all_chops()
    assert isinstance(all_chops, dict)
    assert len(all_chops) == 11
    assert sorted(all_chops.keys()) == EXPECTED_CHOPS


def test_register_chop_decorator_registers_function() -> None:
    """@register_chop should register the decorated function."""

    @register_chop("_test_chop")
    def my_test_chop(ctx: ChopContext) -> None:
        pass

    try:
        assert "_test_chop" in _CHOPS
        assert _CHOPS["_test_chop"] is my_test_chop
    finally:
        # Clean up to avoid polluting other tests
        _CHOPS.pop("_test_chop", None)


def test_ensure_chops_loaded_is_idempotent() -> None:
    """_ensure_chops_loaded() should be safe to call multiple times."""
    _ensure_chops_loaded()
    first = dict(_CHOPS)
    _ensure_chops_loaded()
    second = dict(_CHOPS)
    assert first == second


def test_get_all_chops_returns_copy() -> None:
    """get_all_chops() should return a copy, not the internal dict."""
    all_chops = get_all_chops()
    assert all_chops is not _CHOPS
