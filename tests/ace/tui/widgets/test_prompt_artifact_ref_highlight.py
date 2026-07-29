"""Tests for artifact-reference highlighting in ``PromptTextArea``."""

from __future__ import annotations

from pathlib import Path
import threading

from rich.color import Color

from sase.ace.tui.widgets import _artifact_ref_highlight
from sase.ace.tui.widgets.artifact_ref_completion import (
    ArtifactRefCompletionCatalog,
)
from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_BYTES
from sase.ace.tui.widgets.prompt_completion import DEFAULT_PROMPT_COMPLETION_SETTINGS
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.artifact_refs import ArtifactRefContext, ArtifactRefDocumentRoot

from ._completion_helpers import CompletionTestApp


_KNOWN_KINDS = frozenset({"commit", "chat", "bug", "file", "plans", "designs"})


class _WarmCompletionTestApp(CompletionTestApp):
    def get_prompt_completion_settings(self):
        return DEFAULT_PROMPT_COMPLETION_SETTINGS


def _seed_known_kinds(text_area: PromptTextArea) -> None:
    text_area._artifact_ref_known_kinds_by_project[None] = _KNOWN_KINDS


def _artifact_highlights(
    text_area: PromptTextArea,
) -> list[tuple[int, int, int, str]]:
    return [
        (row, start, end, name)
        for row, spans in text_area._highlights.items()
        for start, end, name in spans
        if name.startswith("artifact_ref.")
    ]


def _stub_known_kind_loaders(monkeypatch, tmp_path: Path):
    calls: list[tuple[Path, int, str | None]] = []
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("designs", tmp_path / "designs"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifact-files.jsonl",
        repositories=(),
        projects=(),
    )

    def _context(
        workspace: str | Path,
        workspace_num: int,
        project: str | None = None,
    ) -> ArtifactRefContext:
        calls.append((Path(workspace), workspace_num, project))
        return context

    def _catalog(
        project: str | None,
        loaded_context: ArtifactRefContext,
    ) -> ArtifactRefCompletionCatalog:
        assert loaded_context is context
        return ArtifactRefCompletionCatalog(project, loaded_context.known_kinds)

    monkeypatch.setattr(_artifact_ref_highlight, "artifact_ref_context", _context)
    monkeypatch.setattr(
        _artifact_ref_highlight,
        "load_artifact_ref_completion_catalog",
        _catalog,
    )
    return calls


def test_known_kinds_target_project_wins_over_caller_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target_workspace = tmp_path / "target"
    caller_workspace = tmp_path / "caller"
    monkeypatch.setattr(
        _artifact_ref_highlight,
        "known_project_namespaces",
        lambda: {"proj": target_workspace},
    )
    calls = _stub_known_kind_loaders(monkeypatch, tmp_path)

    result = _artifact_ref_highlight._load_known_artifact_ref_kinds(
        "proj",
        str(caller_workspace),
        7,
    )

    assert calls == [(target_workspace, 1, "proj")]
    assert "designs" in result.kinds


def test_known_kinds_without_project_keeps_caller_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    caller_workspace = tmp_path / "caller"
    monkeypatch.setattr(
        _artifact_ref_highlight,
        "known_project_namespaces",
        lambda: {"proj": tmp_path / "target"},
    )
    calls = _stub_known_kind_loaders(monkeypatch, tmp_path)

    result = _artifact_ref_highlight._load_known_artifact_ref_kinds(
        None,
        str(caller_workspace),
        7,
    )

    assert calls == [(caller_workspace, 7, None)]
    assert "designs" in result.kinds


def test_known_kinds_unknown_project_falls_back_to_caller_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    caller_workspace = tmp_path / "caller"
    monkeypatch.setattr(
        _artifact_ref_highlight,
        "known_project_namespaces",
        lambda: {},
    )
    calls = _stub_known_kind_loaders(monkeypatch, tmp_path)

    result = _artifact_ref_highlight._load_known_artifact_ref_kinds(
        "proj",
        str(caller_workspace),
        3,
    )

    assert calls == [(caller_workspace, 3, "proj")]
    assert "designs" in result.kinds


async def test_artifact_ref_overlay_marks_each_part_and_registers_styles() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        text_area.load_text("@plans:202607/design.md#L12-L18")
        text_area._build_highlight_map()

        names = [name for *_range, name in _artifact_highlights(text_area)]
        for name in (
            "artifact_ref.sigil",
            "artifact_ref.kind",
            "artifact_ref.separator",
            "artifact_ref.payload",
            "artifact_ref.fragment",
        ):
            assert name in names
            assert name in text_area._theme.syntax_styles

        styles = text_area._theme.syntax_styles
        assert styles["artifact_ref.kind"].color == Color.parse(
            app.current_theme.success
        )
        assert styles["artifact_ref.kind"].bold is True
        assert styles["artifact_ref.payload"].color != styles["artifact_ref.kind"].color
        assert styles["artifact_ref.fragment"].italic is True


async def test_artifact_ref_overlay_subdues_well_formed_unknown_kind() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        text_area.load_text("@user:handle")
        text_area._build_highlight_map()

        highlights = _artifact_highlights(text_area)
        assert highlights == [(0, 0, 12, "artifact_ref.unknown")]
        assert text_area._theme.syntax_styles["artifact_ref.unknown"].dim is True


async def test_artifact_ref_overlay_uses_neutral_style_while_cache_is_cold() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("@plans:202607/design.md")
        text_area._build_highlight_map()

        assert _artifact_highlights(text_area) == [(0, 0, 23, "artifact_ref.neutral")]


async def test_artifact_ref_overlay_skips_fenced_and_inline_literal_zones() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        text_area.load_text(
            "`@plans:inline.md`\n```\n@commit:sase@abcdef1\n```\n@plans:live.md"
        )
        text_area._build_highlight_map()

        highlights = _artifact_highlights(text_area)
        assert {row for row, *_rest in highlights} == {4}
        assert {name for *_range, name in highlights} == {
            "artifact_ref.sigil",
            "artifact_ref.kind",
            "artifact_ref.separator",
            "artifact_ref.payload",
        }


async def test_artifact_ref_overlay_marks_two_refs_on_one_line() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        text_area.load_text(
            "Compare @plans:a.md with @commit:sase@abcdef1 before launch"
        )
        text_area._build_highlight_map()

        highlights = _artifact_highlights(text_area)
        assert [name for *_range, name in highlights].count("artifact_ref.sigil") == 2
        assert [name for *_range, name in highlights].count("artifact_ref.payload") == 2


async def test_artifact_ref_overlay_converts_scanner_utf8_byte_offsets() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        text_area.load_text("é @plans:x.md")
        text_area._build_highlight_map()

        highlights = _artifact_highlights(text_area)
        assert (0, 3, 4, "artifact_ref.sigil") in highlights
        assert (0, 4, 9, "artifact_ref.kind") in highlights


async def test_artifact_ref_overlay_includes_exact_80kb_boundary() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        _seed_known_kinds(text_area)
        reference = "@plans:boundary.md"
        text_area.load_text(
            "x" * (_MAX_OVERLAY_BYTES - len(reference) - 1) + " " + reference
        )
        text_area._build_highlight_map()

        assert "artifact_ref.sigil" in [
            name for *_range, name in _artifact_highlights(text_area)
        ]

        text_area.load_text(text_area.text + "x")
        text_area._build_highlight_map()
        assert not _artifact_highlights(text_area)


async def test_artifact_ref_kind_cache_warms_off_thread(monkeypatch) -> None:
    caller_thread = threading.get_ident()
    loader_threads: list[int] = []

    def _load(
        project: str | None,
        _workspace_dir: str | None,
        _workspace_num: int,
    ) -> _artifact_ref_highlight._KnownKindsResult:
        loader_threads.append(threading.get_ident())
        return _artifact_ref_highlight._KnownKindsResult(project, _KNOWN_KINDS)

    monkeypatch.setattr(
        _artifact_ref_highlight,
        "_load_known_artifact_ref_kinds",
        _load,
    )
    app = _WarmCompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        for _ in range(20):
            if text_area._get_warm_artifact_ref_known_kinds() is not None:
                break
            await pilot.pause(0.01)

        assert text_area._get_warm_artifact_ref_known_kinds() == _KNOWN_KINDS
        assert loader_threads
        assert all(thread_id != caller_thread for thread_id in loader_threads)
