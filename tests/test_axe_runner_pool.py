"""Tests for the axe runner pool module."""

from unittest.mock import patch

from sase.axe.runner_pool import RunnerPool


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_get_current_runners_includes_global(mock_count: object) -> None:
    """Test that get_current_runners includes global count."""
    mock_count.return_value = 3  # type: ignore
    pool = RunnerPool(max_runners=10)
    pool._started_this_tick = 2

    # Should be global (3) + this_tick (2) = 5
    assert pool.get_current_runners() == 5


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_reserve_slot_fails_at_limit(mock_count: object) -> None:
    """Test that reserve_slot fails when at limit."""
    mock_count.return_value = 5  # type: ignore
    pool = RunnerPool(max_runners=5)

    # Should fail - already at max
    assert pool.reserve_slot() is False
    assert pool.get_started_this_tick() == 0


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_reserve_slots_returns_zero_when_none_available(mock_count: object) -> None:
    """Test that reserve_slots returns 0 when none available."""
    mock_count.return_value = 5  # type: ignore
    pool = RunnerPool(max_runners=5)

    reserved = pool.reserve_slots(3)
    assert reserved == 0
    assert pool.get_started_this_tick() == 0


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_add_started_increments_count(mock_count: object) -> None:
    """Test that add_started increments the started count."""
    mock_count.return_value = 0  # type: ignore
    pool = RunnerPool(max_runners=10)

    pool.add_started(3)
    assert pool.get_started_this_tick() == 3

    pool.add_started(2)
    assert pool.get_started_this_tick() == 5


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_is_at_limit_true_when_at_max(mock_count: object) -> None:
    """Test that is_at_limit returns True when at max."""
    mock_count.return_value = 5  # type: ignore
    pool = RunnerPool(max_runners=5)

    assert pool.is_at_limit() is True


@patch("sase.axe.runner_pool.count_all_runners_global")
def test_reset_tick_and_reserve_workflow(mock_count: object) -> None:
    """Test the typical workflow of reset_tick followed by reserves."""
    mock_count.return_value = 0  # type: ignore
    pool = RunnerPool(max_runners=3)

    # Simulate first tick
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is True
    assert pool.get_started_this_tick() == 2

    # Reset for next tick
    pool.reset_tick()
    assert pool.get_started_this_tick() == 0

    # Can reserve again
    assert pool.reserve_slot() is True
    assert pool.get_started_this_tick() == 1
