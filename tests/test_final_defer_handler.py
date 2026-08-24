"""Coverage for the ``sase final defer`` CLI handler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import FinalizerDeclarationError
from sase.main.final_handler import _handle_defer

from .finalizer_declaration_channel_test_helpers import prepare_dirty_declaration


def _defer_args(
    repo_id: str,
    reason: str,
    paths: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(repo_id=repo_id, reason=reason, paths=paths)


def test_defer_accepts_and_reports_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    repo_id = publish_final_context().context.obligations[0].obligation_id

    exit_code = _handle_defer(_defer_args(repo_id, "unsafe_content"))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Deferred:" in out
    assert "unsafe_content" in out
    assert "src/app.py" in out


def test_defer_defaults_to_every_dirty_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context, submit_final_manifest

    repo_id = publish_final_context().context.obligations[0].obligation_id
    submitted: dict[str, object] = {}
    original = submit_final_manifest

    def _capture(manifest: dict[str, object], **kwargs: object) -> object:
        submitted["manifest"] = manifest
        return original(manifest, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("sase.main.final_handler.submit_final_manifest", _capture)

    _handle_defer(_defer_args(repo_id, "unsafe_content"))

    manifest = submitted["manifest"]
    deferral = manifest["payloads"][0]["payload"]["deferrals"][0]  # type: ignore[index]
    assert deferral["paths"] == ["src/app.py"]


def test_defer_unknown_repo_id_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)

    exit_code = _handle_defer(_defer_args("no-such-repo", "unsafe_content"))

    assert exit_code == 1
    assert "unknown repository obligation" in capsys.readouterr().err


def test_defer_rejects_unfounded_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    (tmp_path / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "event": "ToolUse",
                "tool_name": "Edit",
                "tool_input_summary": {"file_path": "src/app.py"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    from sase.finalizers.declaration import publish_final_context

    repo_id = publish_final_context().context.obligations[0].obligation_id

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        _handle_defer(_defer_args(repo_id, "belongs_to_another_turn"))

    assert exc_info.value.code == "commit_deferral_rejected"
