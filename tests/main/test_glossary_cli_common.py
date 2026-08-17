"""Tests for shared ``sase glossary`` project resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.glossary import cli_common
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalogResult,
    _EditorGlossaryProject,
)


def _project(name: str = "sase", key: str = "sase") -> _EditorGlossaryProject:
    return _EditorGlossaryProject(
        key=key, name=name, aliases=(), workspace_dir=Path("/tmp/sase")
    )


def test_resolve_raises_when_project_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_common,
        "editor_glossary_catalog_for_project",
        lambda *_a, **_kw: EditorGlossaryCatalogResult(
            None, None, ("project ref 'missing' did not resolve to a workspace",)
        ),
    )

    with pytest.raises(cli_common.GlossaryCliError, match="did not resolve"):
        cli_common.resolve_glossary_cli_project("missing")


def test_resolve_raises_when_project_has_no_glossary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_common,
        "editor_glossary_catalog_for_project",
        lambda *_a, **_kw: EditorGlossaryCatalogResult(_project(), None, ()),
    )

    with pytest.raises(cli_common.GlossaryCliError, match="no glossary configured"):
        cli_common.resolve_glossary_cli_project("sase")


def test_resolve_raises_with_diagnostics_on_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_common,
        "editor_glossary_catalog_for_project",
        lambda *_a, **_kw: EditorGlossaryCatalogResult(
            _project(), None, ("sase.yml: glossary.Foo: bad shape",)
        ),
    )

    with pytest.raises(cli_common.GlossaryCliError, match="bad shape"):
        cli_common.resolve_glossary_cli_project("sase")
