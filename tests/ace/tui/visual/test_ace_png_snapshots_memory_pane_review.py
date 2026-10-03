"""PNG goldens for the review watermark (phase `watermark-tui`).

The Changes lens with unreviewed rows (``●`` dots plus the ``● N new``
header chip) and the Config hub ``MEMORY`` sub-tab badge, at 120x40 in
dark and light themes. Feed epochs are fixed past dates (the visual
lane pins ``TZ=UTC``) and history data is injected deterministically:
no git, no core, no wall-clock reads.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from typing import Any

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.memory_panel import MemoryPanel, MemoryPane
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_config_modal,
    _patch_config_view,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_T0 = 1789905600  # 2026-09-20 12:00 UTC, pinned for goldens
_T1 = 1789992000  # 2026-09-21 12:00 UTC
_T2 = 1790085780  # 2026-09-22 14:03 UTC


def _golden_authored(name: str) -> dict[str, Any]:
    return {
        "subject_id": f"note:project:sase/{name}",
        "ordinal": 3,
        "class": "authored",
        "summary": {
            "section_paths": ["Definition"],
            "words_added": 20,
            "words_removed": 3,
        },
        "path": f"sase/memory/{name}.md",
        "commit": "d" * 40,
    }


def _golden_changeset(
    commit: str, epoch: int, subject: str, name: str
) -> dict[str, Any]:
    return {
        "scope_key": "project:sase",
        "commit": commit,
        "committer_time": epoch,
        "provenance": {
            "subject": subject,
            "bead": "sase-1ev.12",
            "agent": "athena.sase-1ev.12",
        },
        "regen_only": False,
        "authored": [_golden_authored(name)],
        "consequences": [],
    }


def _golden_feed() -> dict[str, Any]:
    return {
        "changesets": [
            _golden_changeset("a" * 40, _T2, "feat: newest", "alpha"),
            _golden_changeset("b" * 40, _T1, "feat: newer", "beta"),
            _golden_changeset("c" * 40, _T0 - 100, "feat: older", "gamma"),
        ]
    }


def _golden_review() -> dict[str, Any]:
    return {
        "scopes": [
            {
                "scope_key": "project:sase",
                "watermark": {
                    "commit": "w" * 40,
                    "committer_time": _T0,
                    "marked_at": _T0,
                },
                "new_count": 2,
                "newest_commit": "a" * 40,
            }
        ]
    }


def _golden_history() -> SimpleNamespace:
    feed = _golden_feed()
    review = _golden_review()
    scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")
    service = SimpleNamespace(
        project_scope=lambda _root: scope,
        review_state=lambda _scopes: review,
        mark_reviewed=lambda _scope, _through: {"scope_key": "project:sase"},
    )
    return SimpleNamespace(
        service=service,
        scope_for_ref=lambda _ref: scope,
        feed=lambda _scopes: dict(feed),
        subjects=lambda _scope: {"subjects": []},
        version_body=lambda _scope, _selector, version: {
            "body": f"# Garden note\n\nBody at {version}.\n",
            "body_missing": False,
            "blob_oid": "b" * 40,
        },
        comparison=lambda _scope, _selector, _base, _target: {"ops": []},
    )


def _setup_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note(
            "gotchas",
            description="Code conventions and gotchas.",
            body="Code conventions and gotchas body text.",
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})


def _lens_pane(page: AcePage) -> MemoryPane | None:
    screen = page.app.screen
    if isinstance(screen, MemoryPanel):
        return screen.pane
    if isinstance(screen, MemoryPane):
        return screen
    return None


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_changes_lens_review_dark_120x40",
            "ACE memory pane - Changes lens review watermark dark",
        ),
        (
            "textual-light",
            "memory_pane_changes_lens_review_light_120x40",
            "ACE memory pane - Changes lens review watermark light",
        ),
    ],
)
async def test_memory_pane_changes_lens_review_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _setup_notes(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(MemoryPanel(initial_note="sase/memory/gotchas.md"))
        await page.expect_modal("MemoryPanel")
        await wait_for_state(
            page,
            lambda: _lens_pane(page) is not None and not _lens_pane(page)._loading,
            description="panel load",
        )
        pane = _lens_pane(page)
        assert pane is not None
        history = _golden_history()
        monkeypatch.setattr(pane, "_ace_history", lambda: history)
        await page.press("C")
        await wait_for_state(
            page,
            lambda: (
                pane._changes_feed is not None and tuple(pane._changes_review) != ()
            ),
            description="changes feed and review",
        )
        await page.press("j")
        await wait_for_svg_contains(page, "2 new")
        await wait_for_state(
            page,
            lambda: bool(pane._changes_sections),
            description="changeset sections",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "config_hub_memory_badge_dark_120x40",
            "ACE Config hub - MEMORY review badge dark",
        ),
        (
            "textual-light",
            "config_hub_memory_badge_light_120x40",
            "ACE Config hub - MEMORY review badge light",
        ),
    ],
)
async def test_config_hub_memory_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    # The real config view loader never settles in a snapshot run; the
    # shared fixture feeds a deterministic inventory instead.
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        _modal, _pane = await _open_config_modal(page)
        hub = _modal.query_one("#config", ConfigHubPane)
        hub._apply_memory_badge(3)
        await wait_for_svg_contains(page, "●3 Memory")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
