"""Tests for pager syntax session policy and producer classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.adapters import path_section
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
    section_syntax_language,
)
from sase.pager.syntax_policy import (
    PagerSyntaxError,
    apply_explicit_syntax,
    classify_source,
    is_openable_text_path,
    pager_syntax_session_from_config,
    resolve_cli_syntax,
)


def test_classify_python_filename() -> None:
    spec = classify_source(
        category="raw_file",
        logical_filename="app.py",
        source="print(1)\n",
    )
    assert spec is not None
    assert spec.language == "python"
    assert spec.eligible is True


def test_classify_justfile_is_plain() -> None:
    spec = classify_source(
        category="raw_file",
        logical_filename="Justfile",
        source="default:\n    echo hi\n",
    )
    assert spec is not None
    assert spec.language is None


def test_classify_trusted_markdown_ignores_python_filename() -> None:
    spec = classify_source(
        category="markdown_document",
        logical_filename="note.py",
        source="# heading\n",
    )
    assert spec is not None
    assert spec.language == "markdown"


def test_classify_stdin_diff() -> None:
    spec = classify_source(
        category="stdin",
        source="diff --git a/old b/new\n",
    )
    assert spec is not None
    assert spec.language == "diff"


def test_classify_formatted_is_ineligible() -> None:
    assert (
        classify_source(category="formatted", logical_filename="app.py", source="x")
        is None
    )


def test_classify_rejects_embedded_nul() -> None:
    assert (
        classify_source(category="raw_file", logical_filename="app.py", source="x\x00y")
        is None
    )


def test_path_section_records_language_from_filename(tmp_path: Path) -> None:
    path = tmp_path / "main.rs"
    path.write_text("fn main() {}\n", encoding="utf-8")

    section = path_section(path)

    assert section.raw_source is not None
    assert section.raw_source.language == "rust"
    assert section_syntax_language(section) == "rust"


def test_path_section_uses_logical_filename_not_storage_basename(
    tmp_path: Path,
) -> None:
    stored = tmp_path / "0123456789abcdef"
    stored.write_text("def foo():\n    return 1\n", encoding="utf-8")

    section = path_section(stored, logical_filename="/orig/app.py")

    assert section.raw_source is not None
    assert section.raw_source.language == "python"


def test_explicit_override_applies_only_to_raw_sections() -> None:
    raw = PagerSection(
        identity="stdin",
        title="stdin",
        kind="stdin",
        body="key: 1\n",
        raw_source=RawSourceSpec(language=None),
    )
    card = PagerSection(
        identity="pager-commits",
        title="commits",
        kind="commit",
        body="abc123 subject\n",
    )
    document = PagerDocument(
        sections=(raw, card),
        title="mixed",
        origin=PagerOrigin.FILE,
    )

    updated = apply_explicit_syntax(document, "yaml")

    assert updated.sections[0].raw_source is not None
    assert updated.sections[0].raw_source.language == "yaml"
    assert updated.sections[1].raw_source is None


def test_resolve_cli_syntax_rejects_unknown_alias() -> None:
    with pytest.raises(PagerSyntaxError, match="unknown syntax alias"):
        resolve_cli_syntax(syntax="definitely-not-a-lexer", color="auto")


def test_resolve_cli_syntax_plain_alias_is_an_override_without_language() -> None:
    resolution = resolve_cli_syntax(syntax="plain", color="auto")
    assert resolution.apply_override is True
    assert resolution.explicit_language is None
    assert resolution.session.syntax_enabled is True


def test_color_never_wins_over_explicit_syntax() -> None:
    resolution = resolve_cli_syntax(syntax="python", color="never")
    assert resolution.session.syntax_enabled is False
    assert resolution.session.color_enabled is False
    assert resolution.apply_override is False


def test_explicit_auto_enables_syntax_even_when_config_is_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.config.get_pager_syntax", lambda: "never")
    omitted = resolve_cli_syntax(syntax=None, color="auto")
    explicit = resolve_cli_syntax(syntax="auto", color="auto")
    assert omitted.session.syntax_enabled is False
    assert explicit.session.syntax_enabled is True


def test_no_color_disables_auto_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    session = pager_syntax_session_from_config()
    assert session.color_enabled is False
    assert session.syntax_enabled is False


def test_is_openable_text_path_admits_rust_and_shebang(tmp_path: Path) -> None:
    rust = tmp_path / "lib.rs"
    rust.write_text("pub fn x() {}\n", encoding="utf-8")
    script = tmp_path / "myscript"
    script.write_text("#!/usr/bin/env python3\nprint(1)\n", encoding="utf-8")
    unknown = tmp_path / "blob.dat"
    unknown.write_bytes(b"\x00\x01\x02")

    assert is_openable_text_path(rust) is True
    assert is_openable_text_path(script) is True
    assert is_openable_text_path(unknown) is False


def test_is_openable_text_path_admits_swift_and_go_without_mime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.pager.syntax_policy.mimetypes.guess_type",
        lambda _path: (None, None),
    )
    swift = tmp_path / "Router.swift"
    go_file = tmp_path / "main.go"
    swift.write_text("import Foundation\n", encoding="utf-8")
    go_file.write_text("package main\n", encoding="utf-8")

    assert is_openable_text_path(swift) is True
    assert is_openable_text_path(go_file) is True


def test_get_pager_syntax_falls_back_on_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.config._settings import get_pager_syntax

    monkeypatch.setattr(
        "sase.config._settings._merged_config",
        lambda: {"pager": {"syntax": "always"}},
    )
    assert get_pager_syntax() == "auto"
    monkeypatch.setattr(
        "sase.config._settings._merged_config",
        lambda: {"pager": {"syntax": "never"}},
    )
    assert get_pager_syntax() == "never"


def test_nul_preview_excludes_falsely_named_python(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_bytes(b"print(1)\n\x00\xff")
    assert is_openable_text_path(path) is False
