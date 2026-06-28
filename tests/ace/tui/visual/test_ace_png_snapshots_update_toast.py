"""ACE TUI PNG visual snapshot for the startup update toast."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.updates import OutdatedComponent, UpdateStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _toast_status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=1_700_000_000.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="1.2.0",
                latest_version="1.3.0",
                distribution_name="sase-github",
            ),
            OutdatedComponent(
                display_name="telegram",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-telegram",
            ),
        ),
    )


async def test_startup_update_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup update toast is readable and tied to the Updates tab accent."""
    patch_startup_loaders(monkeypatch)
    status = _toast_status()
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=True, check_ttl_hours=24),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "startup_update_toast_120x40",
            title="ACE startup update toast",
        )
