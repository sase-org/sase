"""Activation tests: real entry points, color policy, and first paint."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
    section_syntax_language,
)
from sase.pager.resolve import LinkTargetKind, resolve_ref
from sase.pager.screen import PagerScreen
from sase.pager.syntax_policy import PagerSyntaxSession
from tests.pager._app_helpers import pager_screen as _pager_screen


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_resolve_ref_opens_source_families_and_special_names(tmp_path: Path) -> None:
    cases = {
        "app.py": "python",
        "main.rs": "rust",
        "theme.tcss": "css",
        "uv.lock": "toml",
        "README": "markdown",
        "Dockerfile": "docker",
        "Makefile": "make",
    }
    for name, language in cases.items():
        path = _write(tmp_path / name, "content\n")
        target = resolve_ref(str(path))
        assert target is not None, name
        assert target.kind is LinkTargetKind.DOCUMENT
        assert target.document is not None
        section = target.document.sections[0]
        assert section_syntax_language(section) == language, name


def test_resolve_ref_opens_justfile_without_a_language_chip(tmp_path: Path) -> None:
    path = _write(tmp_path / "Justfile", "default:\n    echo hi\n")
    target = resolve_ref(str(path))
    assert target is not None
    assert target.document is not None
    assert section_syntax_language(target.document.sections[0]) is None
    assert target.document.sections[0].plain_text.startswith("default:")


def test_resolve_ref_opens_extensionless_shebang(tmp_path: Path) -> None:
    path = _write(tmp_path / "myscript", "#!/usr/bin/env python3\nprint(1)\n")
    target = resolve_ref(str(path))
    assert target is not None
    assert target.document is not None
    assert section_syntax_language(target.document.sections[0]) == "python"


def test_resolve_ref_keeps_media_and_binary_cards(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n")
    binary = tmp_path / "data.bin"
    binary.write_bytes(bytes(range(256)))
    fake_python = tmp_path / "app.py"
    fake_python.write_bytes(b"print(1)\n\x00\xff")

    image_target = resolve_ref(str(image))
    assert image_target is not None
    assert image_target.kind is LinkTargetKind.MEDIA

    binary_target = resolve_ref(str(binary))
    assert binary_target is not None
    assert binary_target.document is not None
    assert f"path: {binary}" in binary_target.document.sections[0].plain_text
    assert section_syntax_language(binary_target.document.sections[0]) is None

    fake_target = resolve_ref(str(fake_python))
    assert fake_target is not None
    assert fake_target.document is not None
    assert section_syntax_language(fake_target.document.sections[0]) is None
    assert f"path: {fake_python}" in fake_target.document.sections[0].plain_text


def test_negative_stdin_samples_stay_untyped() -> None:
    from sase.pager.syntax_policy import classify_source

    json_body = classify_source(
        category="stdin",
        source='{"name": "--- a/foo", "hunk": "@@ -1 +1 @@"}\n',
    )
    isolated = classify_source(category="stdin", source="@@ -1,1 +1,1 @@\n")
    assert json_body is not None
    assert json_body.language is None
    assert isolated is not None
    assert isolated.language is None


def _python_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body='path = "src/sase/cli_pager.py"\n# comment\n',
        raw_source=RawSourceSpec(language="python"),
    )
    return PagerDocument(
        sections=(section,),
        title="demo.py",
        origin=PagerOrigin.FILE,
    )


async def test_color_never_skips_syntax_and_sets_console_no_color() -> None:
    app = SasePager(
        _python_document(),
        syntax_session=PagerSyntaxSession(syntax_enabled=False, color_enabled=False),
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.console.no_color is True
        screen = _pager_screen(app)
        assert screen.syntax_enabled is False
        assert screen._syntax_prepared == {}
        assert screen.document.sections[0].plain_text.startswith("path =")


async def test_prepared_source_keeps_canonical_characters_and_link_spans() -> None:
    document = _python_document()
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await wait_for(pilot, lambda: "file:/tmp/demo.py" in screen._syntax_prepared)
        prepared = screen._syntax_prepared["file:/tmp/demo.py"]
        assert prepared.styled_text.plain == document.sections[0].plain_text
        assert prepared.hint == "py"
        assert prepared.styled_text.spans
        assert screen._label_layer is not None
        assert screen._label_layer.labels


async def test_first_paint_and_keys_work_before_slow_syntax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    from sase.pager import _screen_syntax as screen_syntax_mod

    real_lex = screen_syntax_mod._lex_and_style

    def _blocked(*args: object, **kwargs: object) -> object:
        entered.set()
        release.wait(timeout=5)
        return real_lex(*args, **kwargs)

    monkeypatch.setattr(screen_syntax_mod, "_lex_and_style", _blocked)
    app = SasePager(_python_document())
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = _pager_screen(app)
            await pilot.pause()
            assert screen._body is not None
            await wait_for(pilot, entered.is_set)
            scroll = screen.query_one("#pager-body-scroll", VerticalScroll)
            before = scroll.scroll_y
            await pilot.press("j")
            assert "file:/tmp/demo.py" not in screen._syntax_prepared
            release.set()
            await wait_for(
                pilot, lambda: "file:/tmp/demo.py" in screen._syntax_prepared
            )
            assert scroll.scroll_y >= before
    finally:
        release.set()
