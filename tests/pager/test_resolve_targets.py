"""Tests for basic ``resolve_ref`` target construction and copy text behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.link_scan import LinkSpanKind
from sase.pager.resolve import LinkTargetKind, copy_text_for_target, resolve_ref

from ._resolve_helpers import _context, _write


def test_resolve_ref_opens_a_text_file_as_a_document(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("hello world\n", encoding="utf-8")

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert target.document.sections[0].plain_text == "hello world\n"
    assert target.edit_path == path


def test_resolve_ref_returns_none_for_a_missing_path(tmp_path: Path) -> None:
    assert resolve_ref(str(tmp_path / "does-not-exist.txt")) is None


def test_resolve_ref_opens_a_directory_as_a_sorted_listing(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    target = resolve_ref(str(tmp_path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    body = target.document.sections[0].plain_text
    assert body.index(str(tmp_path / "a.txt")) < body.index(str(tmp_path / "b.txt"))


def test_resolve_ref_returns_a_media_target_for_an_image_path(tmp_path: Path) -> None:
    path = tmp_path / "screenshot.png"
    path.write_bytes(b"\x89PNG\r\n")

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.MEDIA
    assert target.media_specs[0].path == path
    assert target.media_specs[0].kind == "image"
    assert target.edit_path == path


def test_resolve_ref_returns_a_binary_card_for_an_unrecognized_binary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(bytes(range(256)))

    target = resolve_ref(str(path))

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    body = target.document.sections[0].plain_text
    assert f"path: {path}" in body
    assert target.edit_path == path


@pytest.mark.parametrize("ref", ["", "   "])
def test_resolve_ref_rejects_blank_input(ref: str) -> None:
    assert resolve_ref(ref) is None


def test_copy_text_for_target_keeps_the_logical_token_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    copied = copy_text_for_target("sub/file.py", LinkSpanKind.FILE_PATH.value)

    assert copied == "sub/file.py"


def test_copy_text_for_target_returns_the_existing_resolution(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "file.py")

    copied = copy_text_for_target(
        "src/file.py",
        LinkSpanKind.FILE_PATH.value,
        context=_context(first, second),
    )

    assert copied == str(live.resolve())


def test_copy_text_for_target_returns_artifact_refs_unchanged() -> None:
    assert (
        copy_text_for_target("bead:sase-uk.5", LinkSpanKind.ARTIFACT_REF.value)
        == "bead:sase-uk.5"
    )
