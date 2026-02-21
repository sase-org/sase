"""Tests for the SharedRunnerPool cross-process runner pool."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.runner_pool import SharedRunnerPool


@pytest.fixture
def temp_shared_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary shared state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield shared_dir


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_init_creates_counter_file(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test that SharedRunnerPool creates the counter file on init."""
    pool = SharedRunnerPool(max_runners=5)
    assert pool.get_counter_path().exists()
    assert pool.get_counter_path().read_text() == "0"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_init_preserves_existing_counter(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test that init doesn't overwrite an existing counter file."""
    shared_dir = temp_shared_dir
    shared_dir.mkdir(parents=True, exist_ok=True)
    counter_file = shared_dir / "runner_count"
    counter_file.write_text("3")

    pool = SharedRunnerPool(max_runners=5)
    assert pool.get_counter_path().read_text() == "3"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_reserve_slot_success(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test reserving a slot when capacity available."""
    pool = SharedRunnerPool(max_runners=5)
    assert pool.reserve_slot() is True
    assert pool.get_counter_path().read_text().strip() == "1"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_reserve_slot_multiple(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test reserving multiple slots sequentially."""
    pool = SharedRunnerPool(max_runners=3)
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is False
    assert pool.get_counter_path().read_text().strip() == "3"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=3)
def test_reserve_slot_respects_global_runners(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test that reserve_slot accounts for global runners."""
    pool = SharedRunnerPool(max_runners=5)
    # Global has 3, counter has 0, max 5 → 2 slots available
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is False


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=5)
def test_reserve_slot_fails_when_global_at_limit(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test that reserve_slot fails when global runners already at limit."""
    pool = SharedRunnerPool(max_runners=5)
    assert pool.reserve_slot() is False


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_release_slot(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test releasing a previously reserved slot."""
    pool = SharedRunnerPool(max_runners=5)
    pool.reserve_slot()
    pool.reserve_slot()
    assert pool.get_counter_path().read_text().strip() == "2"

    pool.release_slot()
    assert pool.get_counter_path().read_text().strip() == "1"

    pool.release_slot()
    assert pool.get_counter_path().read_text().strip() == "0"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_release_slot_never_goes_negative(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test that releasing with no reservations doesn't go negative."""
    pool = SharedRunnerPool(max_runners=5)
    pool.release_slot()
    assert pool.get_counter_path().read_text().strip() == "0"


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=2)
def test_get_current_runners(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test get_current_runners combines counter with global count."""
    pool = SharedRunnerPool(max_runners=10)
    pool.reserve_slot()
    # Global (2) + counter (1) = 3
    assert pool.get_current_runners() == 3


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_is_at_limit_true(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test is_at_limit returns True when at max."""
    pool = SharedRunnerPool(max_runners=2)
    pool.reserve_slot()
    pool.reserve_slot()
    assert pool.is_at_limit() is True


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_is_at_limit_false(_mock_count: object, temp_shared_dir: Path) -> None:
    """Test is_at_limit returns False when slots available."""
    pool = SharedRunnerPool(max_runners=5)
    pool.reserve_slot()
    assert pool.is_at_limit() is False


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=4)
def test_is_at_limit_with_global_runners(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test is_at_limit accounts for global runners."""
    pool = SharedRunnerPool(max_runners=5)
    pool.reserve_slot()
    # Global (4) + counter (1) = 5 >= max (5)
    assert pool.is_at_limit() is True


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=0)
def test_reserve_release_reserve_cycle(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test a full reserve-release-reserve cycle."""
    pool = SharedRunnerPool(max_runners=2)

    # Fill up
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is False

    # Release one
    pool.release_slot()

    # Can reserve again
    assert pool.reserve_slot() is True
    assert pool.reserve_slot() is False
