"""Tests for prompt K bead preview routing."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.bead_preview_modal import BeadPreviewModal
from sase.ace.tui.models.bead_preview import (
    BeadRouteAmbiguous,
    BeadRouteFound,
    BeadRouteMissing,
    BeadRouteNotBead,
    BeadRouteUnavailable,
    BeadStoreDirectory,
    BeadStoreRef,
)
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.link_scan import PagerOrigin
from sase.pager.screen import PagerScreen
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot, bead_id_prefix
from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], BeadPreviewModal)


def _snapshot(
    tmp_path: Path,
    *,
    issue_prefix: str = "sase",
    issue_ids: frozenset[str] = frozenset(),
    project_label: str = "sase",
    project_key: str = "sase",
) -> BeadStoreSnapshot:
    return BeadStoreSnapshot(
        origin=BeadStoreOrigin(
            project_key=project_key,
            project_label=project_label,
            primary_workspace=tmp_path,
            beads_dir=tmp_path / "beads",
        ),
        store_key=project_key,
        issue_ids=issue_ids,
        issue_prefix=issue_prefix,
        project_refs=frozenset({project_key}),
    )


def _directory(tmp_path: Path, **kwargs: Any) -> BeadStoreDirectory:
    return BeadStoreDirectory(snapshots=(_snapshot(tmp_path, **kwargs),))


def _install_directory(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    directory: BeadStoreDirectory | None,
) -> list[BeadStoreDirectory]:
    published: list[BeadStoreDirectory] = []
    monkeypatch.setattr(
        app,
        "get_bead_store_directory",
        lambda *, schedule=True: directory,
        raising=False,
    )
    monkeypatch.setattr(
        app,
        "publish_bead_store_directory",
        lambda loaded, *, generation=None: published.append(loaded),
        raising=False,
    )
    return published


async def test_k_on_bare_id_and_ref_pushes_bead_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        issue = project.create("Epic", IssueType.PLAN, description="Body")
        prefix = bead_id_prefix(issue.id)
        assert prefix is not None
        directory = BeadStoreDirectory(
            snapshots=(
                _snapshot(
                    tmp_path, issue_prefix=prefix, issue_ids=frozenset({issue.id})
                ),
            )
        )
        store = BeadStoreRef(
            project_key="sase",
            project_label="sase",
            beads_dir=tmp_path / "beads",
            primary_workspace=tmp_path,
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteFound(issue.id, store),
    )

    async with PromptPage(issue.id, cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))
        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, BeadPreviewModal)
        assert modal._bead_id == issue.id

    ref_text = f"@bead:{issue.id}"
    async with PromptPage(ref_text, cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))
        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, BeadPreviewModal)
        assert modal._bead_id == issue.id


async def test_unknown_prefix_is_synchronous_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path)
    looked_up: list[object] = []

    async with PromptPage("bob-cli", cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda *a, **k: looked_up.append((a, k)) or True,
        )
        await page.press("K")
        await page.pause()
        assert looked_up
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_missing_owned_id_threads_bead_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="bob-cli")
    captured: dict[str, str | None] = {}
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteMissing("bob-cli-kz", ("bob-cli",)),
    )

    async with PromptPage("bob-cli-kz", cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda *a, **k: captured.update(k) or True,
        )
        await page.press("K")
        await page.wait_for(lambda: "bead_miss" in captured)
        assert captured["bead_miss"] == "No bead 'bob-cli-kz' in bob-cli"


async def test_missing_ref_toasts_without_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    notifications: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteMissing("sase-zzzz", ("sase",)),
    )

    async with PromptPage("@bead:sase-zzzz", cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("ref misses must not fall through")
            ),
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("K")
        await page.wait_for(lambda: bool(notifications))
        assert notifications == [("No bead 'sase-zzzz' in sase", "information")]


async def test_ambiguous_and_unavailable_warn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    notifications: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteAmbiguous("sase-1aa", ("sase", "bob-cli")),
    )

    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("K")
        await page.wait_for(lambda: bool(notifications))
        message, severity = notifications[0]
        assert "multiple projects" in message
        assert "+project" in message
        assert severity == "warning"

    notifications.clear()
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteUnavailable("sase-1aa", "bob-cli", "locked"),
    )
    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("K")
        await page.wait_for(lambda: bool(notifications))
        assert notifications == [("bob-cli beads are unavailable: locked", "warning")]


async def test_cold_directory_loads_publishes_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    looked_up: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.load_bead_store_directory",
        lambda: directory,
    )

    async with PromptPage("bob-cli", cursor=(0, 0), size=(80, 24)) as page:
        published = _install_directory(monkeypatch, page.ta.app, None)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda *a, **k: looked_up.append(True) or True,
        )
        await page.press("K")
        await page.wait_for(lambda: bool(looked_up) and bool(published))
        assert published[0] is directory
        assert not _top_is_preview(page)


async def test_stale_result_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    store = BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=tmp_path / "beads",
        primary_workspace=tmp_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteFound("sase-1aa", store),
    )

    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        original = page.ta._resolve_bead_preview_async

        async def stale(*args: object, **kwargs: object) -> None:
            page.ta._prompt_preview_request_id += 1
            await original(*args, **kwargs)

        monkeypatch.setattr(page.ta, "_resolve_bead_preview_async", stale)
        await page.press("K")
        await page.pause()
        await page.pause()
        assert not _top_is_preview(page)


@pytest.mark.parametrize("invalidate_directory", [False, True])
async def test_same_cursor_text_change_or_directory_invalidation_discards_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalidate_directory: bool,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    store = BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=tmp_path / "beads",
        primary_workspace=tmp_path,
    )
    started = threading.Event()
    release = threading.Event()

    def delayed_route(*_args: object, **_kwargs: object) -> BeadRouteFound:
        started.set()
        release.wait(timeout=3)
        return BeadRouteFound("sase-1aa", store)

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        delayed_route,
    )
    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        await page.press("K")
        assert await asyncio.to_thread(started.wait, 2)
        if invalidate_directory:
            monkeypatch.setattr(
                page.ta.app,
                "warm_bead_store_directory",
                lambda: None,
                raising=False,
            )
            from sase.ace.tui.actions._startup_prompt_bead_directory import (
                StartupPromptBeadDirectoryMixin,
            )

            page.ta.app._bead_store_directory_generation = 0
            StartupPromptBeadDirectoryMixin._invalidate_bead_store_directory(
                page.ta.app,
                reason="test invalidation",
            )
        else:
            page.ta.load_text("sase-1bb")
            page.ta.cursor_location = (0, 2)
        release.set()
        await page.pause()
        await page.pause()
        assert not _top_is_preview(page)


async def test_routing_exception_becomes_current_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="sase")
    notifications: list[tuple[str, str | None]] = []

    def explode(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention", explode
    )
    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await page.wait_for(lambda: bool(notifications))

        assert notifications == [
            ("Could not resolve bead 'sase-1aa': router unavailable", "warning")
        ]


def _detail_resolution() -> LinkResolution:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1aa",
                title="sase-1aa",
                kind="bead",
                body="Epic body",
            ),
        ),
        title="sase-1aa",
        origin=PagerOrigin.BEAD,
    )
    return LinkResolution(
        target=LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document)
    )


def _top_is_pager(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], PagerScreen)


async def test_ctrl_bracket_on_bead_opens_pager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(
        tmp_path, issue_prefix="sase", issue_ids=frozenset({"sase-1aa"})
    )
    store = BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=tmp_path / "beads",
        primary_workspace=tmp_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteFound("sase-1aa", store),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.bead_detail_link_resolution",
        lambda *_a, **_k: _detail_resolution(),
    )

    async with PromptPage("sase-1aa", cursor=(0, 2), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        await page.press("ctrl+right_square_bracket")
        await page.wait_for(lambda: _top_is_pager(page))
        assert not _top_is_preview(page)


async def test_ctrl_bracket_missing_owned_id_toasts_without_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path, issue_prefix="bob-cli")
    notifications: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteMissing("bob-cli-kz", ("bob-cli",)),
    )

    async with PromptPage("bob-cli-kz", cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("Ctrl+] must not fall through to word lookup")
            ),
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("ctrl+right_square_bracket")
        await page.wait_for(lambda: bool(notifications))
        assert notifications == [("No bead 'bob-cli-kz' in bob-cli", "information")]
        assert not _top_is_pager(page)


async def test_ctrl_bracket_unowned_prefix_keeps_jump_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = _directory(tmp_path)
    notifications: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteNotBead("plain"),
    )

    async with PromptPage("plain text", cursor=(0, 0), size=(80, 24)) as page:
        _install_directory(monkeypatch, page.ta.app, directory)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("ctrl+right_square_bracket")
        await page.pause()
        assert page.ta._prompt_jump_request_id == 0
        assert notifications == [
            (
                "Move the cursor onto a macro, skill, file path, glossary "
                "term, repo name, or bead ID to jump to its definition",
                "warning",
            )
        ]
