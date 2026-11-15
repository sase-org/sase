"""Tests for status-tinted prompt bead mentions and their triggers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.style import Style

from sase.ace.testing import PromptPage
from sase.ace.tui.actions import _startup_prompt_bead_directory as bead_dir_mod
from sase.ace.tui.models.bead_preview import (
    BeadMentionEntry,
    BeadMentionIndex,
    BeadStoreDirectory,
)
from sase.ace.tui.util.semantic_styles import (
    bead_mention_style_name,
    semantic_highlight_styles_from_theme,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot


def _snapshot(
    tmp_path: Path,
    *,
    issue_prefix: str = "sase",
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
        issue_ids=frozenset(),
        issue_prefix=issue_prefix,
        project_refs=frozenset({project_key}),
    )


def _directory(tmp_path: Path, **kwargs: Any) -> BeadStoreDirectory:
    return BeadStoreDirectory(snapshots=(_snapshot(tmp_path, **kwargs),))


def _install_bead_directory(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    directory: BeadStoreDirectory | None,
) -> list[bool]:
    schedules: list[bool] = []
    monkeypatch.setattr(
        app,
        "get_bead_store_directory",
        lambda *, schedule=True: (schedules.append(schedule), directory)[1],
        raising=False,
    )
    return schedules


def _install_bead_index(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    index: BeadMentionIndex | None = None,
) -> BeadMentionIndex:
    owned = index if index is not None else BeadMentionIndex()
    monkeypatch.setattr(
        app, "bead_mention_index_for_render", lambda: owned, raising=False
    )
    return owned


def _record_requests(monkeypatch: pytest.MonkeyPatch, app: Any) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        app,
        "request_bead_mention_resolution",
        lambda ids: calls.append(sorted(str(item) for item in ids)),
        raising=False,
    )
    return calls


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _bead_spans(ta: PromptTextArea) -> list[tuple[int, int, int, str]]:
    return [
        (row, start, end, name)
        for row, spans in ta._highlights.items()
        for start, end, name in spans
        if name.startswith("bead.mention.")
    ]


async def test_insert_typing_schedules_no_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with PromptPage("see sase-1ss", mode="insert") as page:
        _install_bead_directory(monkeypatch, page.ta.app, _directory(tmp_path))
        _install_bead_index(monkeypatch, page.ta.app)
        calls = _record_requests(monkeypatch, page.ta.app)
        await page.press("x")
        await page.press("y")
        await page.pause()
        assert calls == []


async def test_escape_schedules_one_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with PromptPage("see sase-1ss here", mode="insert") as page:
        _install_bead_directory(monkeypatch, page.ta.app, _directory(tmp_path))
        _install_bead_index(monkeypatch, page.ta.app)
        calls = _record_requests(monkeypatch, page.ta.app)
        await page.press("escape")
        assert page.mode == "normal"
        assert calls == [["sase-1ss"]]


async def test_escape_without_directory_schedules_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with PromptPage("see sase-1ss here", mode="insert") as page:
        calls = _record_requests(monkeypatch, page.ta.app)
        await page.press("escape")
        assert page.mode == "normal"
        assert calls == []


async def test_published_index_styles_resolved_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text = "see sase-1ss then sase-9zz"
    async with PromptPage(text, mode="insert") as page:
        _install_bead_directory(monkeypatch, page.ta.app, _directory(tmp_path))
        index = _install_bead_index(monkeypatch, page.ta.app)
        index.store(
            "sase-1ss",
            BeadMentionEntry("in_progress", "key", "token"),
        )
        index.store("sase-9zz", BeadMentionEntry(None, "key", "token"))

        page.ta._build_highlight_map()

        assert (0, 4, 12, "bead.mention.in_progress") in _bead_spans(page.ta)
        assert all(span[3] != "bead.mention.missing" for span in _bead_spans(page.ta))
        assert len(_bead_spans(page.ta)) == 1
        style = page.ta._theme.syntax_styles["bead.mention.in_progress"]
        assert style.bold is True
        assert style.underline is True


async def test_ref_form_keeps_artifact_styling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async with PromptPage("see @bead:sase-1ss here", mode="insert") as page:
        _install_bead_directory(monkeypatch, page.ta.app, _directory(tmp_path))
        index = _install_bead_index(monkeypatch, page.ta.app)
        index.store(
            "sase-1ss",
            BeadMentionEntry("closed", "key", "token"),
        )

        page.ta._build_highlight_map()

        assert _bead_spans(page.ta) == []


async def test_highlight_map_render_never_warms_or_queries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("highlight path must not do I/O")

    monkeypatch.setattr("sase.core.bead_read_facade.statuses_for_ids", _raise)
    monkeypatch.setattr("sase.core.bead_read_facade.store_fingerprint", _raise)
    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.load_bead_store_directory", _raise
    )
    async with PromptPage("see sase-1ss here", mode="insert") as page:
        schedules = _install_bead_directory(
            monkeypatch, page.ta.app, _directory(tmp_path)
        )
        index = _install_bead_index(monkeypatch, page.ta.app)
        index.store("sase-1ss", BeadMentionEntry("closed", "key", "token"))

        page.ta._build_highlight_map()

        assert schedules == [False]
        assert (0, 4, 12, "bead.mention.closed") in _bead_spans(page.ta)


async def test_k_requests_mention_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.ace.tui.models.bead_preview import BeadRouteFound, BeadStoreRef

    store = BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=tmp_path / "beads",
        primary_workspace=tmp_path,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_bead_preview.route_bead_mention",
        lambda *_a, **_k: BeadRouteFound("sase-1ss", store),
    )
    directory = _directory(tmp_path)
    async with PromptPage("see sase-1ss here", cursor=(0, 6)) as page:
        _install_bead_directory(monkeypatch, page.ta.app, directory)
        _install_bead_index(monkeypatch, page.ta.app)
        calls = _record_requests(monkeypatch, page.ta.app)
        await page.press("K")
        await page.wait_for(lambda: len(calls) > 0)
        assert calls == [["sase-1ss"]]


def test_semantic_styles_cover_every_status() -> None:
    theme = SimpleNamespace(
        primary="#ff0000",
        accent="#00ff00",
        background="#000000",
        foreground="#ffffff",
    )
    styles = semantic_highlight_styles_from_theme(theme)
    assert styles is not None
    assert set(styles.bead) == {
        "open",
        "claimed",
        "ready",
        "snoozed",
        "in_progress",
        "closed",
    }
    for status, style in styles.bead.items():
        assert style.bold is True
        assert style.underline is True
        assert bead_mention_style_name(status) == f"bead.mention.{status}"
    assert "in_progress=" in styles.signature
    assert "closed=" in styles.signature


def test_semantic_styles_adapt_to_light_theme() -> None:
    dark = SimpleNamespace(
        primary="#ff0000",
        accent="#00ff00",
        background="#000000",
        foreground="#ffffff",
    )
    light = SimpleNamespace(
        primary="#ff0000",
        accent="#00ff00",
        background="#ffffff",
        foreground="#000000",
    )
    dark_styles = semantic_highlight_styles_from_theme(dark)
    light_styles = semantic_highlight_styles_from_theme(light)
    assert dark_styles is not None and light_styles is not None
    assert dark_styles.signature != light_styles.signature
    assert (
        dark_styles.bead["in_progress"].color != light_styles.bead["in_progress"].color
    )


def test_semantic_styles_default_bead_map_is_empty() -> None:
    from sase.ace.tui.util.semantic_styles import SemanticHighlightStyles

    assert SemanticHighlightStyles(glossary=Style(), repo=Style()).bead == {}


def _stub_app(
    directory: BeadStoreDirectory | None,
    index: BeadMentionIndex,
) -> SimpleNamespace:
    return SimpleNamespace(
        _bead_store_directory=directory,
        _bead_store_directory_generation=0,
        _bead_store_directory_warming=False,
        _bead_mention_index=index,
        _bead_mention_pending=set(),
        _bead_mention_resolution_in_flight=False,
        run_workers=[],
        warmed=[],
        refreshed=[],
    )


def _bind_stub(app: SimpleNamespace) -> SimpleNamespace:
    mixin = bead_dir_mod.StartupPromptBeadDirectoryMixin
    app.warm_bead_store_directory = lambda: app.warmed.append(True)  # type: ignore[method-assign]
    app.run_worker = lambda worker, **_k: app.run_workers.append(worker())  # type: ignore[method-assign]
    app._refresh_visible_prompt_semantic_surfaces = (  # type: ignore[method-assign]
        lambda **_k: app.refreshed.append(True)
    )
    app.request_bead_mention_resolution = mixin.request_bead_mention_resolution.__get__(
        app
    )  # type: ignore[method-assign]
    app._run_bead_mention_resolution = mixin._run_bead_mention_resolution.__get__(app)  # type: ignore[method-assign]
    app._plan_bead_mention_resolution = mixin._plan_bead_mention_resolution.__get__(app)  # type: ignore[method-assign]
    return app


async def test_two_requests_coalesce_into_one_worker(tmp_path: Path) -> None:
    app = _bind_stub(_stub_app(_directory(tmp_path), BeadMentionIndex()))
    app.request_bead_mention_resolution(["sase-1ss"])
    app.request_bead_mention_resolution(["sase-1ss.1"])
    assert len(app.run_workers) == 1
    assert app._bead_mention_pending == {"sase-1ss", "sase-1ss.1"}


async def test_worker_publishes_and_releases_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.ace.tui.models.bead_preview import BeadMentionEntry as Entry

    published = [
        ("sase-1ss", Entry("open", "key", "tok")),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.resolve_bead_mention_updates",
        lambda _plan: published,
    )
    app = _bind_stub(_stub_app(_directory(tmp_path), BeadMentionIndex()))
    app.request_bead_mention_resolution(["sase-1ss"])
    assert len(app.run_workers) == 1
    await app.run_workers[0]
    assert app._bead_mention_index.peek("sase-1ss") == published[0][1]
    assert app._bead_mention_resolution_in_flight is False
    assert app.refreshed == [True]


async def test_worker_releases_flag_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _explode(_plan: Any) -> Any:
        raise RuntimeError("resolution exploded")

    monkeypatch.setattr(
        "sase.ace.tui.models.bead_preview.resolve_bead_mention_updates", _explode
    )
    app = _bind_stub(_stub_app(_directory(tmp_path), BeadMentionIndex()))
    app.request_bead_mention_resolution(["sase-1ss"])
    await app.run_workers[0]
    assert app._bead_mention_resolution_in_flight is False
    assert app._bead_mention_index.peek("sase-1ss") is None
    assert app.refreshed == []


async def test_request_with_cold_directory_warms_instead(tmp_path: Path) -> None:
    app = _bind_stub(_stub_app(None, BeadMentionIndex()))
    app.request_bead_mention_resolution(["sase-1ss"])
    assert app.warmed == [True]
    assert app.run_workers == []
    assert app._bead_mention_pending == {"sase-1ss"}
