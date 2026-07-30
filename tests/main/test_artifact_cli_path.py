"""Tests for ``sase artifact path``."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pytest

from sase.artifact_cli.path import handle_path
from tests.main.artifact_cli_reference_helpers import (
    ARTIFACT_DIGEST,
    artifact_file,
    artifact_ref_context,
    resolved_reference,
)


@pytest.mark.parametrize("status", ["ambiguous", "missing", "unknown_kind"])
def test_path_reports_resolution_failures_without_stdout(
    tmp_path: Path,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = tmp_path / "candidate.md"
    result = resolved_reference(
        None,
        status=status,
        candidates=(str(candidate),),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_path(argparse.Namespace(reference=result.input)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert status in captured.err
    assert str(candidate) in captured.err


@pytest.mark.parametrize("status", ["exact", "drifted"])
def test_path_prints_exactly_one_absolute_path(
    tmp_path: Path,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "path with spaces.md"
    result = resolved_reference(path, status=status)
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_path(argparse.Namespace(reference=result.input)) == 0
    assert capsys.readouterr().out == f"{path.resolve()}\n"


@pytest.mark.parametrize(
    "reference",
    [
        "bead:sase-9z",
        "agent:alice.athena.9w",
    ],
)
def test_path_accepts_entity_page_references(
    tmp_path: Path,
    reference: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "README.md"
    result = resolved_reference(path, reference=reference)
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_path(argparse.Namespace(reference=reference)) == 0
    assert capsys.readouterr().out == f"{path.resolve()}\n"


@pytest.mark.parametrize(
    "reference",
    [
        "commit:sase@0123456789abcdef0123456789abcdef01234567",
        "bug:sase#123",
    ],
)
def test_path_nonfilesystem_references_exit_two_with_show_hint(
    reference: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = resolved_reference(None, reference=reference)
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_path(argparse.Namespace(reference=reference)) == 2
    assert "sase artifact show" in capsys.readouterr().err


def test_path_malformed_reference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: (_ for _ in ()).throw(ValueError("bad reference")),
    )

    assert handle_path(argparse.Namespace(reference="bad")) == 1
    assert "malformed" in capsys.readouterr().err


def test_path_materializes_vcs_backed_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache_path = tmp_path / "vcs-cache" / "report.md"
    cache_path.parent.mkdir()
    cache_path.write_text("# report\n", encoding="utf-8")
    file = replace(
        artifact_file(tmp_path / "unused"),
        path=None,
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/report.md",
    )
    result = resolved_reference(
        None,
        reference=f"file:explicit:{ARTIFACT_DIGEST}",
        status="vcs_backed",
        file=file,
        locator=f"sase@{'b' * 40}:docs/report.md",
        context=artifact_ref_context(tmp_path),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolved_file_path",
        lambda _result: cache_path,
    )

    assert handle_path(argparse.Namespace(reference=result.input)) == 0
    assert capsys.readouterr().out.strip() == str(cache_path)
