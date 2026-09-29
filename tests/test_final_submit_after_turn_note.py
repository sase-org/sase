"""After-turn commit timing note on ``sase final submit`` output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import publish_final_context
from sase.main.final_handler import _handle_submit

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _submit_and_read_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    bead_action: str | None,
) -> str:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    if bead_action == "close":
        monkeypatch.setenv("SASE_BEAD_ID", "sase-zq.1")
        monkeypatch.setattr(
            "sase.finalizers.declaration_manifest._assigned_bead_status",
            lambda bead_id, cwd: "in_progress",
        )
    declaration = valid_manifest(publish_final_context())
    if bead_action is not None:
        repositories = declaration["payloads"][0]["payload"]["repositories"]
        for repository in repositories:
            repository["bead_action"] = bead_action
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(declaration), encoding="utf-8")
    assert _handle_submit(argparse.Namespace(manifest=str(path))) == 0
    return capsys.readouterr().out


def test_submit_commit_with_keep_names_keep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _submit_and_read_out(tmp_path, monkeypatch, capsys, bead_action="keep")
    assert "Accepted final declaration for:" in out
    assert "after this turn ends" in out
    assert "`git log` is unchanged" in out
    assert "without re-checking or resubmitting" in out
    assert "keep leaves it open with nothing resuming it" in out
    assert "closes the assigned bead" not in out


def test_submit_commit_with_close_names_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _submit_and_read_out(tmp_path, monkeypatch, capsys, bead_action="close")
    assert "Accepted final declaration for:" in out
    assert "after this turn ends" in out
    assert "close closes the assigned bead after the primary commit lands" in out
    assert "leaves it open with nothing resuming it" not in out
