"""ACE TUI PNG visual snapshot for the startup update toast."""

from __future__ import annotations

import pytest
from textual.widgets._toast import Toast

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.updates import (
    CommitSourceSpec,
    CommitSummary,
    IncomingCommits,
    OutdatedComponent,
    UpdateStatus,
)
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


def _grouped_toast_status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=1_700_000_000.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.10.2+132.gcb7945a",
                latest_version="0.10.2+133.g687eb0",
                distribution_name="sase",
                install_type="editable",
                source_root="/repo/sase",
                upstream_ref="origin/main",
            ),
            OutdatedComponent(
                display_name="sase-core",
                role="core",
                installed_version="0.4.1",
                latest_version="0.4.2",
                distribution_name="sase-core-rs",
                install_type="editable",
                source_root="/repo/sase-core",
                upstream_ref="origin/main",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="1.2.0",
                latest_version="1.3.0",
                distribution_name="sase-github",
                install_type="editable",
                source_root="/repo/sase-github",
                upstream_ref="origin/main",
            ),
        ),
    )


def _visual_incoming_commits(spec: CommitSourceSpec) -> IncomingCommits:
    if spec.git_root == "/repo/sase":
        return IncomingCommits(
            total=12,
            commits=tuple(
                CommitSummary(f"a1b6b{idx:02d}", f"chore: grouped toast commit {idx}")
                for idx in range(12)
            ),
            source="git",
        )
    if spec.git_root == "/repo/sase-core":
        return IncomingCommits(
            total=2,
            commits=(
                CommitSummary("9f2c1a0", "fix: compare-ref pagination"),
                CommitSummary("7a44cc1", "test: cover stale upstream refs"),
            ),
            source="git",
        )
    return IncomingCommits(
        total=12,
        commits=tuple(
            CommitSummary(f"89abc{idx:02d}", f"feat: plugin update preview {idx}")
            for idx in range(12)
        ),
        source="git",
    )


def _toast_is_mounted(page: AcePage) -> bool:
    return bool(list(page.app.screen.query(Toast)))


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
        lambda: update_toast._UpdateToastConfig(startup_toast=True),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        notifications=True,
        startup_policy="real",
    ) as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "startup_update_toast_120x40",
            title="ACE startup update toast",
        )


async def test_startup_update_toast_grouped_commits_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup update toast shows grouped, truncated incoming commits."""
    patch_startup_loaders(monkeypatch)
    status = _grouped_toast_status()
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=True),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: status,
    )
    monkeypatch.setattr(
        update_toast,
        "_fetch_incoming_commits",
        lambda spec, **_kwargs: _visual_incoming_commits(spec),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        notifications=True,
        startup_policy="real",
    ) as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        await wait_for_visual_idle(page)
        # The wider core-rebuild badge changes the top-bar layout after the
        # toast worker lands. Force a full repaint before exporting so Textual
        # does not hand the PNG helper a partial dirty-region compositor frame.
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "startup_update_toast_grouped_commits_120x40",
            title="ACE startup grouped update toast",
        )
