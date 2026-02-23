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


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=5)
def test_reserve_slot_fails_when_global_at_limit(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test that reserve_slot fails when global runners already at limit."""
    pool = SharedRunnerPool(max_runners=5)
    assert pool.reserve_slot() is False


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


@patch("sase.axe.runner_pool.count_all_runners_global", return_value=4)
def test_is_at_limit_with_global_runners(
    _mock_count: object, temp_shared_dir: Path
) -> None:
    """Test is_at_limit accounts for global runners."""
    pool = SharedRunnerPool(max_runners=5)
    pool.reserve_slot()
    # Global (4) + counter (1) = 5 >= max (5)
    assert pool.is_at_limit() is True
