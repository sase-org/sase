"""Placeholder-message rejection and prepare-wrapper submit fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.prepare import prepare_conditional_completion
from sase.main.final_handler import _handle_submit

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _placeholder_manifest() -> dict[str, object]:
    publication = publish_final_context()
    return json.loads(json.dumps(publication.payload["manifest_template"]))


def _wrapper(declaration: dict[str, object]) -> dict[str, object]:
    return {
        "success_message": "ok",
        "verification": {"command": ["just", "check"]},
        "declaration": declaration,
    }


def test_submit_rejects_placeholder_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(_placeholder_manifest())
    assert exc_info.value.code == "commit_message_placeholder"


def test_prepare_rejects_placeholder_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        prepare_conditional_completion(_wrapper(_placeholder_manifest()))
    assert exc_info.value.code == "commit_message_placeholder"


def test_submit_accepts_real_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    submit_final_manifest(valid_manifest(publish_final_context()))


def test_submit_accepts_prepare_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    declaration = valid_manifest(publish_final_context())
    path = tmp_path / "wrapper.json"
    path.write_text(json.dumps(_wrapper(declaration)), encoding="utf-8")
    submitted: list[object] = []
    monkeypatch.setattr(
        "sase.main.final_handler.submit_final_manifest",
        lambda manifest: submitted.append(manifest) or {},
    )

    assert _handle_submit(argparse.Namespace(manifest=str(path))) == 0
    assert submitted == [declaration]


@pytest.mark.parametrize(
    "wrapper",
    [
        {"declaration": {"payloads": []}},
        {"verification": {"command": ["just", "check"]}},
        {"declaration": "nope", "verification": {}},
    ],
)
def test_submit_rejects_malformed_wrapper(
    tmp_path: Path, wrapper: dict[str, object]
) -> None:
    path = tmp_path / "wrapper.json"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        _handle_submit(argparse.Namespace(manifest=str(path)))
    assert exc_info.value.code == "wrapper_malformed"
