"""Shared isolation for ACE TUI tests."""

from collections.abc import Iterator

import pytest

from sase.ace.tui.util import shutdown


@pytest.fixture(autouse=True)
def _reset_ace_shutdown_signal() -> Iterator[None]:
    shutdown._shutdown_signal.reset_for_tests()
    yield
    shutdown._shutdown_signal.reset_for_tests()
