"""ACE TUI PNG visual snapshot for the post-update toast."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    write_pending_update_toast,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _receipt() -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(
            UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),
            UpdateVersionTransition("sase-telegram", "0.5.0", "0.6.0"),
        ),
        dependency_count=2,
    )


async def test_post_update_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The post-update toast confirms the new version without crowding ACE."""
    patch_startup_loaders(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=True),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "post_update_toast_120x40",
            title="ACE post-update toast",
        )
