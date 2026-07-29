"""Reference, show, path, and open tests for ``sase artifact``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sase.artifact_cli.open import handle_open
from sase.artifact_cli.path import handle_path
from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolve_cli_reference,
)
from sase.artifact_cli.show import handle_show
from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefResolution,
    parse_artifact_ref,
)
from sase.core.artifact_file_facade import ArtifactFile


_DIGEST = "0123456789abcdef01234567"


def _context(tmp_path: Path) -> ArtifactRefContext:
    plans = tmp_path / "plans"
    chats = tmp_path / "chats"
    plans.mkdir()
    chats.mkdir()
    return ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plans", plans),),
        chats_root=chats,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject("sase", "gh_sase-org__sase"),),
    )


def _artifact(path: Path, **overrides: object) -> ArtifactFile:
    values: dict[str, object] = {
        "id": f"explicit:{_DIGEST}",
        "label": "Artifact",
        "kind": "file",
        "path": str(path),
        "source_path": None,
        "workspace_dir": None,
        "created_at": "2026-07-29T12:34:56Z",
        "agent_artifacts_dir": "/agents/run",
        "project": "gh_sase-org__sase",
        "workflow": "ace-run",
        "raw_timestamp": "20260729123456",
        "agent_name": "agent.one",
        "explicit": True,
        "sha256": "abc",
        "size_bytes": 3,
        "mime_type": "text/plain",
    }
    values.update(overrides)
    return ArtifactFile(**values)  # type: ignore[arg-type]


def _result(
    path: Path | None,
    *,
    reference: str = "plans:doc.md",
    status: str = "exact",
    candidates: tuple[str, ...] = (),
    file: ArtifactFile | None = None,
    locator: str | None = None,
) -> ResolvedArtifactReference:
    parsed = parse_artifact_ref(reference)
    return ResolvedArtifactReference(
        input=reference,
        canonical_reference=parsed.rendered,
        parsed=parsed,
        resolution=ArtifactRefResolution(
            schema_version=1,
            status=status,  # type: ignore[arg-type]
            rendered=parsed.rendered,
            locator=locator,
            resolved_path=path,
            candidates=candidates,
        ),
        file=file,
    )


def test_shared_resolver_supports_bare_file_id_and_full_record(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    stored = tmp_path / "stored artifact.txt"
    stored.write_text("artifact", encoding="utf-8")
    row = _artifact(stored)
    context.artifact_index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact": dict(vars(row)),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = resolve_cli_reference(f"explicit:{_DIGEST}", context=context)

    assert result.canonical_reference == f"file:explicit:{_DIGEST}"
    assert result.resolution.status == "exact"
    assert result.resolution.resolved_path == stored
    assert result.file == row
    envelope = result.to_json_dict()
    assert envelope["file"]["ref"] == f"file:explicit:{_DIGEST}"  # type: ignore[index]


def test_shared_resolver_serializes_fragment_and_drift_candidates(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    drifted = context.document_roots[0].root / "nested" / "doc.md"
    drifted.parent.mkdir()
    drifted.write_text("one\ntwo\n", encoding="utf-8")

    result = resolve_cli_reference("plans:doc.md#L2", context=context)

    assert result.resolution.status == "drifted"
    assert result.resolution.resolved_path == drifted
    assert result.to_json_dict()["fragment"] == {
        "type": "lines",
        "start": 2,
        "end": 2,
        "page": None,
        "seconds": None,
    }
    assert result.to_json_dict()["resolution"]["candidates"] == [str(drifted)]  # type: ignore[index]


def test_show_json_uses_common_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "doc.md"
    result = _result(path, reference="plans:doc.md#L3")
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_show(argparse.Namespace(reference="plans:doc.md#L3", json=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == [
        "reference",
        "kind",
        "fragment",
        "file",
        "resolution",
    ]
    assert payload["reference"] == "plans:doc.md#L3"
    assert payload["kind"] == "plans"
    assert payload["fragment"]["start"] == 3
    assert payload["resolution"]["status"] == "exact"


def test_show_file_pretty_reports_every_field_and_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored = tmp_path / "stored.txt"
    stored.write_text("live", encoding="utf-8")
    missing_source = tmp_path / "missing-source.txt"
    file = _artifact(stored, source_path=str(missing_source))
    result = _result(
        stored,
        reference=f"file:explicit:{_DIGEST}",
        file=file,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.show.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_show(argparse.Namespace(reference=result.input, json=False)) == 0

    output = capsys.readouterr().out
    for field in vars(file):
        assert field in output
    assert f"file:explicit:{_DIGEST}" in output
    assert "stored_path_status" in output
    assert "source_path_status" in output
    assert "live" in output
    assert "missing" in output


@pytest.mark.parametrize("status", ["ambiguous", "missing", "unknown_kind"])
def test_path_reports_resolution_failures_without_stdout(
    tmp_path: Path,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = tmp_path / "candidate.md"
    result = _result(
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
    result = _result(path, status=status)
    monkeypatch.setattr(
        "sase.artifact_cli.path.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_path(argparse.Namespace(reference=result.input)) == 0
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
    result = _result(None, reference=reference)
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


def test_open_text_falls_back_without_bat_and_preserves_safe_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "-leading name.txt"
    path.write_text("text", encoding="utf-8")
    result = _result(path, file=_artifact(path))
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: None,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(list(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 0
    assert commands == [
        [
            sys.executable,
            "-m",
            "sase.ace.tui.graphics.artifact_text_dump",
            "--",
            str(path.resolve()),
        ]
    ]


@pytest.mark.parametrize(
    ("kind", "mime_type", "suffix", "viewer"),
    [
        ("image", "image/png", ".png", "kitten"),
        ("file", "video/mp4", ".mp4", "mpv"),
        ("pdf", "application/pdf", ".pdf", "xdg-open"),
        ("file", "application/octet-stream", ".bin", "xdg-open"),
    ],
)
def test_open_selects_bounded_media_and_external_viewers(
    tmp_path: Path,
    kind: str,
    mime_type: str,
    suffix: str,
    viewer: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / f"artifact with spaces{suffix}"
    path.write_bytes(b"data")
    result = _result(
        path,
        file=_artifact(path, kind=kind, mime_type=mime_type),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: "/usr/bin/viewer",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(list(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 0
    [command] = commands
    assert command[0] == viewer
    boundary = command.index("--")
    assert command[boundary + 1 :] == [str(path.resolve())]
    if viewer == "mpv":
        assert "--no-config" in command
    if viewer == "kitten":
        assert "--place" in command


def test_open_reports_missing_viewer_and_nonzero_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "artifact.pdf"
    result = _result(
        path,
        file=_artifact(path, kind="pdf", mime_type="application/pdf"),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: None,
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 1
    error = capsys.readouterr().err
    assert "xdg-open" in error
    assert str(path) in error

    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: "/usr/bin/xdg-open",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 9),
    )
    assert handle_open(argparse.Namespace(reference=result.input)) == 1
    error = capsys.readouterr().err
    assert "exit code 9" in error
    assert str(path) in error


def test_open_bug_uses_tracker_url_and_commit_has_show_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bug = _result(None, reference="bug:sase#123", locator="gh_sase-org__sase#123")
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: bug,
    )
    monkeypatch.setattr(
        "sase.ace.tui.artifacts_bugs.issue_url_for_number",
        lambda project, number: f"https://tracker/{project}/{number}",
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.webbrowser.open",
        lambda url: opened.append(url) or True,
    )

    assert handle_open(argparse.Namespace(reference=bug.input)) == 0
    assert opened == ["https://tracker/gh_sase-org__sase/123"]

    commit = _result(
        None,
        reference="commit:sase@0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: commit,
    )
    assert handle_open(argparse.Namespace(reference=commit.input)) == 2
    assert "sase artifact show" in capsys.readouterr().err
