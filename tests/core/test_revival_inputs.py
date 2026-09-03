from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifacts import create_artifacts_directory
from sase.core.revival_inputs import (
    capture_revival_inputs,
    revival_input_file,
    revival_input_file_for_dismissed,
)


def _write_inputs(
    artifacts_dir: Path,
    *,
    raw: str = "raw prompt\n",
    submitted: str | None = "submitted prompt\n",
    xprompts: str | None = '[{"name": "plan"}]\n',
) -> None:
    (artifacts_dir / "raw_xprompt.md").write_text(raw, encoding="utf-8")
    if submitted is not None:
        (artifacts_dir / "submitted_xprompt.md").write_text(submitted, encoding="utf-8")
    if xprompts is not None:
        (artifacts_dir / "xprompts.json").write_text(xprompts, encoding="utf-8")


def test_capture_copies_all_launch_boundary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = Path(
        create_artifacts_directory("ace-run", "proj", timestamp="260903_120000")
    )
    _write_inputs(artifacts)

    archive = capture_revival_inputs(artifacts)

    assert archive is not None
    assert archive.parts[-4:] == ("ace-run", "202609", "03", "20260903120000")
    assert (archive / "raw_xprompt.md").read_text(encoding="utf-8") == "raw prompt\n"
    assert (archive / "submitted_xprompt.md").read_text(
        encoding="utf-8"
    ) == "submitted prompt\n"
    assert (archive / "xprompts.json").read_text(encoding="utf-8") == (
        '[{"name": "plan"}]\n'
    )


def test_capture_skips_optional_files_that_are_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = Path(
        create_artifacts_directory("ace-run", "proj", timestamp="260903_120100")
    )
    _write_inputs(artifacts, submitted=None, xprompts=None)

    archive = capture_revival_inputs(artifacts)

    assert archive is not None
    assert (archive / "raw_xprompt.md").is_file()
    assert not (archive / "submitted_xprompt.md").exists()
    assert not (archive / "xprompts.json").exists()


def test_capture_survives_deleting_the_live_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = Path(
        create_artifacts_directory("ace-run", "proj", timestamp="260903_120200")
    )
    _write_inputs(artifacts)
    capture_revival_inputs(artifacts)
    artifacts_path = str(artifacts)
    for child in artifacts.iterdir():
        child.unlink()
    artifacts.rmdir()

    found = revival_input_file(artifacts_path, "raw_xprompt.md")
    assert found is not None
    assert found.read_text(encoding="utf-8") == "raw prompt\n"
    dismissed = revival_input_file_for_dismissed(
        {"artifacts_dir": artifacts_path, "raw_suffix": "20260903120200"},
        "proj",
        "submitted_xprompt.md",
    )
    assert dismissed is not None
    assert dismissed.read_text(encoding="utf-8") == "submitted prompt\n"


def test_unparsed_artifacts_dir_uses_stable_digest_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = tmp_path / "scratch-run"
    artifacts.mkdir()
    _write_inputs(artifacts, submitted=None, xprompts=None)

    first = capture_revival_inputs(artifacts)
    archived = revival_input_file(artifacts, "raw_xprompt.md")

    assert first is not None
    assert archived is not None
    assert archived.parent == first
    assert first.parent.name == ".unparsed"
    assert (first / "raw_xprompt.md").read_text(encoding="utf-8") == "raw prompt\n"


def test_dismissed_bundle_without_artifacts_dir_uses_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = Path(
        create_artifacts_directory("ace-run", "proj", timestamp="260903_120300")
    )
    _write_inputs(artifacts, submitted=None, xprompts=None)
    capture_revival_inputs(artifacts)

    found = revival_input_file_for_dismissed(
        {
            "raw_suffix": "20260903120300",
            "project_file": str(tmp_path / ".sase" / "projects" / "proj" / "proj.sase"),
        },
        "proj",
        "raw_xprompt.md",
    )
    assert found is not None
    assert found.read_text(encoding="utf-8") == "raw prompt\n"
