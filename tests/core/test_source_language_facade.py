"""Tests for the typed source-language Rust facade."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME, require_rust_binding
from sase.core.source_language_facade import (
    SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION,
    logical_source_filename,
    resolve_source_language,
)
from tests._rust_extension_module_helpers import (
    evict_rust_extension,
    patch_rust_extension,
)


@pytest.mark.parametrize(
    ("filename", "language", "reason"),
    [
        ("app.py", "python", "filename"),
        ("types.pyi", "python", "filename"),
        ("main.rs", "rust", "filename"),
        ("main.go", "go", "filename"),
        ("file.c", "c", "filename"),
        ("file.h", "c", "filename"),
        ("file.cpp", "cpp", "filename"),
        ("app.js", "javascript", "filename"),
        ("app.jsx", "jsx", "filename"),
        ("app.ts", "typescript", "filename"),
        ("app.tsx", "tsx", "filename"),
        ("run.sh", "sh", "filename"),
        ("run.bash", "bash", "filename"),
        ("run.zsh", "zsh", "filename"),
        ("data.json", "json", "filename"),
        ("events.jsonl", "json", "filename"),
        ("config.yaml", "yaml", "filename"),
        ("Cargo.toml", "toml", "filename"),
        ("uv.lock", "toml", "filename"),
        ("note.md", "markdown", "filename"),
        ("prompt.xprompt", "markdown", "filename"),
        ("README", "markdown", "filename"),
        ("README.rst", "rst", "filename"),
        ("index.html", "html", "filename"),
        ("theme.css", "css", "filename"),
        ("app.tcss", "css", "filename"),
        ("query.sql", "sql", "filename"),
        ("changes.diff", "diff", "filename"),
        ("Makefile", "make", "filename"),
        ("Dockerfile", "docker", "filename"),
        ("page.j2", "jinja", "filename"),
        (".env", "bash", "filename"),
        (".env.local", "bash", "filename"),
        ("notes.txt", None, "plain_filename"),
        ("server.log", None, "plain_filename"),
        ("project.sase", None, "plain_filename"),
        (".gitignore", None, "plain_filename"),
        ("Justfile", None, "plain_filename"),
        ("justfile", None, "plain_filename"),
    ],
)
def test_filename_mapping_table(
    filename: str,
    language: str | None,
    reason: str,
) -> None:
    result = resolve_source_language(
        category="raw_file",
        logical_filename=filename,
    )
    assert result.language == language
    assert result.reason == reason
    assert result.supported_text is True


def test_suffix_is_case_insensitive_and_readme_rst_is_not_markdown() -> None:
    python = resolve_source_language(
        category="raw_file",
        logical_filename="FOO.PY",
    )
    rst = resolve_source_language(
        category="raw_file",
        logical_filename="README.rst",
    )
    make = resolve_source_language(
        category="raw_file",
        logical_filename="MAKEFILE",
    )
    assert python.language == "python"
    assert rst.language == "rst"
    assert make.language is None
    assert make.reason == "unknown"
    assert make.supported_text is False


def test_trusted_categories_override_filename() -> None:
    markdown = resolve_source_language(
        category="markdown_document",
        logical_filename="note.py",
        prefix="#!/usr/bin/env python3\n",
    )
    diff = resolve_source_language(
        category="diff",
        logical_filename="note.md",
    )
    formatted = resolve_source_language(
        category="formatted",
        logical_filename="note.py",
    )
    assert markdown.language == "markdown"
    assert markdown.reason == "trusted_markdown"
    assert diff.language == "diff"
    assert formatted.language is None
    assert formatted.reason == "ineligible"
    assert formatted.supported_text is False


@pytest.mark.parametrize(
    ("prefix", "language"),
    [
        ("#!/usr/bin/env python3\n", "python"),
        ("#!/usr/bin/env -S python3 -u\n", "python"),
        ("#!/bin/bash\n", "bash"),
        ("#!/usr/bin/env zsh\n", "zsh"),
        ("#!/bin/sh\n", "sh"),
    ],
)
def test_extensionless_shebangs(prefix: str, language: str) -> None:
    result = resolve_source_language(
        category="raw_file",
        logical_filename="myscript",
        prefix=prefix,
    )
    assert result.language == language
    assert result.reason == "shebang"
    assert result.supported_text is False


def test_shebang_is_not_used_when_suffix_is_present() -> None:
    result = resolve_source_language(
        category="raw_file",
        logical_filename="myscript.foo",
        prefix="#!/usr/bin/env python3\n",
    )
    assert result.language is None
    assert result.reason == "unknown"


def test_stdin_diff_sniff_positive_and_negative_samples() -> None:
    git = resolve_source_language(
        category="stdin",
        prefix="diff --git a/old b/new\n",
    )
    unified = resolve_source_language(
        category="stdin",
        prefix="--- /dev/null\n+++ b/created\n@@ -0,0 +1,1 @@\n+hi\n",
    )
    json_body = resolve_source_language(
        category="stdin",
        prefix='{"name": "--- a/foo", "hunk": "@@ -1 +1 @@"}\n',
    )
    isolated = resolve_source_language(
        category="stdin",
        prefix="@@ -1,1 +1,1 @@\n",
    )
    raw_file = resolve_source_language(
        category="raw_file",
        logical_filename="notes",
        prefix="diff --git a/old b/new\n",
    )
    assert git.language == "diff"
    assert git.reason == "diff_prefix"
    assert unified.language == "diff"
    assert json_body.language is None
    assert json_body.reason == "untyped"
    assert isolated.reason == "untyped"
    assert raw_file.reason == "unknown"


def test_prefix_budget_ignores_diff_after_eight_kib() -> None:
    budget = int(require_rust_binding("source_language_prefix_budget_bytes")())
    prefix = ("x" * budget) + "\ndiff --git a/old b/new\n"
    result = resolve_source_language(category="stdin", prefix=prefix)
    assert result.language is None
    assert result.reason == "untyped"


def test_logical_filename_precedence() -> None:
    assert (
        logical_source_filename(
            source_path="/orig/app.py",
            vcs_relpath="docs/app.py",
            resolved_path="/objects/abc",
        )
        == "/orig/app.py"
    )
    assert (
        logical_source_filename(
            source_path="",
            vcs_relpath="docs/app.py",
            resolved_path="/objects/abc",
        )
        == "docs/app.py"
    )
    assert (
        logical_source_filename(
            resolved_path="/objects/abc",
        )
        == "/objects/abc"
    )
    assert logical_source_filename() is None


def test_schema_version_matches_binding() -> None:
    assert (
        require_rust_binding("source_language_wire_schema_version")()
        == SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION
    )


def test_missing_binding_raises_instead_of_unknown_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ModuleType(RUST_EXTENSION_MODULE_NAME)
    patch_rust_extension(monkeypatch, fake)
    with pytest.raises(AttributeError, match="resolve_source_language") as excinfo:
        resolve_source_language(category="raw_file", logical_filename="app.py")
    message = str(excinfo.value)
    assert RUST_EXTENSION_MODULE_NAME in message
    assert "stale" in message


def test_missing_extension_raises_instead_of_unknown_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evict_rust_extension(monkeypatch)

    def _missing(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", _missing)
    with pytest.raises(ImportError, match="sase_core_rs is not importable"):
        resolve_source_language(category="raw_file", logical_filename="app.py")
