"""Tests for ``sase artifact read``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.artifact_cli.read import handle_read
from sase.artifact_read_log import ArtifactReadError, read_artifact_read_events
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_cli_reference_helpers import resolved_reference


def _read_args(
    reference: str = "plan:doc.md", **overrides: object
) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "reference": reference,
        "reason": "Need the design of record",
        "format": "markdown",
        "lines": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_read_strips_frontmatter_and_managed_blocks_and_audits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = tmp_path / "doc.md"
    path.write_text(
        "---\ntitle: Doc\n---\n"
        "<!-- sase:links:start -->\n## Links\n\n|\n<!-- sase:links:end -->\n"
        "# Heading\n\nbody line\n"
        "<!-- sase:referenced-by:start -->\n## Referenced By\n"
        "<!-- sase:referenced-by:end -->\n",
        encoding="utf-8",
    )
    result = resolved_reference(path, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_artifact_link_store",
        lambda: (_ for _ in ()).throw(RuntimeError("no store")),
    )

    assert handle_read(_read_args()) == 0

    output = capsys.readouterr()
    assert "# Heading" in output.out
    assert "body line" in output.out
    assert "title: Doc" not in output.out
    assert "sase:links:start" not in output.out
    assert "Referenced By" not in output.out
    assert "not recorded as a graph edge" in output.err
    from sase.core.paths import sase_projects_dir

    candidates = list(sase_projects_dir().glob("*/artifact_reads.jsonl"))
    assert candidates, "expected an artifact_reads.jsonl audit log"
    logged = read_artifact_read_events(log_path=candidates[0])
    assert logged[0].reason == "Need the design of record"
    assert logged[0].recorded_link is False
    assert logged[0].ref == "plan:doc.md"
    assert logged[0].resolved_path == str(path)


def test_read_refuses_to_print_when_audit_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Doc\n", encoding="utf-8")
    result = resolved_reference(path, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise ArtifactReadError("could not record artifact read audit row: boom")

    monkeypatch.setattr(
        "sase.artifact_cli.read.append_artifact_read_event", fail_append
    )

    assert handle_read(_read_args()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not record artifact read audit row" in captured.err


def test_read_records_prepared_path_not_resolution_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    stored = tmp_path / "stored.md"
    stored.write_text("# unused\n", encoding="utf-8")
    prepared = tmp_path / "vcs-cache" / "materialized.md"
    prepared.parent.mkdir()
    prepared.write_text("# Heading\nbody line\n", encoding="utf-8")
    result = resolved_reference(stored, reference="plan:doc.md", status="vcs_backed")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolved_file_path",
        lambda _result: prepared,
    )

    assert handle_read(_read_args()) == 0

    from sase.core.paths import sase_projects_dir

    candidates = list(sase_projects_dir().glob("*/artifact_reads.jsonl"))
    logged = read_artifact_read_events(log_path=candidates[0])
    assert logged[0].resolved_path == str(prepared)
    assert logged[0].resolved_path != str(stored)


def test_read_json_and_line_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = tmp_path / "doc.md"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = resolved_reference(path, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )

    assert handle_read(_read_args(format="json", lines=2)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reference"] == "plan:doc.md"
    assert payload["recorded_link"] is False
    assert payload["text"].splitlines() == ["one", "two"]


def test_read_prints_link_neighborhood_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = tmp_path / "doc.md"
    path.write_text("# Heading\nbody line\n", encoding="utf-8")
    result = resolved_reference(path, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )
    from sase.sdd.artifact_link_store import canonicalize_artifact_link_ref

    canonical = canonicalize_artifact_link_ref("plan:doc.md")
    rows = (
        {
            "source_ref": canonical,
            "relation": "implements",
            "target_ref": "bead:sase-r8",
        },
        {
            "source_ref": "agent:sase-tj.land",
            "relation": "read",
            "target_ref": canonical,
        },
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.load_neighborhood_rows",
        lambda _canonical: rows,
    )

    assert handle_read(_read_args()) == 0

    err = capsys.readouterr().err
    assert "Links: implements bead:sase-r8 · read-by agent:sase-tj.land" in err


def test_read_warns_when_artifact_is_superseded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = tmp_path / "doc.md"
    path.write_text("# Heading\nbody line\n", encoding="utf-8")
    result = resolved_reference(path, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )
    from sase.sdd.artifact_link_store import canonicalize_artifact_link_ref

    canonical = canonicalize_artifact_link_ref("plan:doc.md")
    rows = (
        {
            "source_ref": "plan:202608/v2_design.md",
            "relation": "supersedes",
            "target_ref": canonical,
        },
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.load_neighborhood_rows",
        lambda _canonical: rows,
    )

    assert handle_read(_read_args()) == 0

    err = capsys.readouterr().err
    assert "warning: superseded by plan:202608/v2_design.md" in err


def test_read_binary_prints_open_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG")
    result = resolved_reference(
        path, reference="file:explicit:0123456789abcdef01234567"
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: result,
    )

    assert (
        handle_read(_read_args(reference=result.input, reason="Inspect the diagram"))
        == 0
    )
    output = capsys.readouterr().out
    assert "sase artifact open" in output
    assert result.canonical_reference in output
