"""Tests for configured chop lookup."""

import pytest

from sase.axe.chop_runner import AmbiguousChopError, ChopNotFoundError
from sase.axe.chop_runner import find_configured_chop
from sase.axe.config import ChopConfig

from tests.axe_chop_runner_helpers import config_with


def test_find_configured_chop_unique() -> None:
    chop = ChopConfig(name="hook_checks", description="")
    config = config_with(hooks=[chop])
    match = find_configured_chop(config, "hook_checks")
    assert match.lumberjack_name == "hooks"
    assert match.chop is chop


def test_find_configured_chop_missing_raises() -> None:
    config = config_with(hooks=[ChopConfig(name="other", description="")])
    with pytest.raises(ChopNotFoundError):
        find_configured_chop(config, "missing")


def test_find_configured_chop_ignores_disabled_entries() -> None:
    config = config_with(
        hooks=[ChopConfig(name="retired", description="", enabled=False)]
    )
    with pytest.raises(ChopNotFoundError):
        find_configured_chop(config, "retired")


def test_find_configured_chop_ambiguous_without_lumberjack_raises() -> None:
    config = config_with(
        hooks=[ChopConfig(name="dup", description="")],
        comments=[ChopConfig(name="dup", description="")],
    )
    with pytest.raises(AmbiguousChopError) as exc_info:
        find_configured_chop(config, "dup")
    assert exc_info.value.candidates == ["comments", "hooks"]


def test_find_configured_chop_ambiguous_with_lumberjack_succeeds() -> None:
    chop_h = ChopConfig(name="dup", description="from hooks")
    chop_c = ChopConfig(name="dup", description="from comments")
    config = config_with(hooks=[chop_h], comments=[chop_c])
    match = find_configured_chop(config, "dup", lumberjack_name="comments")
    assert match.lumberjack_name == "comments"
    assert match.chop is chop_c


def test_find_configured_chop_lumberjack_filter_misses_raises() -> None:
    chop = ChopConfig(name="hook_checks", description="")
    config = config_with(hooks=[chop])
    with pytest.raises(ChopNotFoundError):
        find_configured_chop(config, "hook_checks", lumberjack_name="comments")
