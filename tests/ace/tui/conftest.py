"""Shared isolation for ACE TUI tests."""

import functools
from collections.abc import Iterator

import pytest
from textual.pilot import Pilot

from sase.ace.testing import settle as settle_helpers
from sase.ace.tui.util import shutdown
from sase.project_display_names import ProjectRefDisplaySnapshot


@pytest.fixture(autouse=True)
def _reset_ace_shutdown_signal() -> Iterator[None]:
    shutdown._shutdown_signal.reset_for_tests()
    yield
    shutdown._shutdown_signal.reset_for_tests()


@pytest.fixture(autouse=True)
def _event_driven_bare_pilot_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make raw ACE TUI ``pilot.pause()`` calls use the shared settle barrier."""

    original_pause = Pilot.pause

    @functools.wraps(original_pause)
    async def pause(self: Pilot, delay: float | None = None) -> None:
        if delay is None:
            await settle_helpers.settle_pilot(self, _pilot_pause=original_pause)
        else:
            await original_pause(self, delay)

    monkeypatch.setattr(Pilot, "pause", pause)


@pytest.fixture(autouse=True)
def _isolate_commits_current_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ACE tests independent of the checkout running the test suite."""
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda **_kwargs: (None, None, None),
    )


@pytest.fixture(autouse=True)
def _isolate_commits_project_display_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Stitches startup labels independent of the host project inventory."""
    monkeypatch.setattr(
        "sase.project_display_names.load_project_ref_display_snapshot",
        ProjectRefDisplaySnapshot,
    )
