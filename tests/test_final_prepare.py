"""Host-sealed conditional completion preparation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    publish_final_context,
)
from sase.finalizers.prepare import (
    prepare_conditional_completion,
    read_prepare_manifest,
)
from sase.main.parser import create_parser

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _observation(repo_id: str) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "kind": "main",
        "name": "main",
        "head": _digest("head"),
        "head_tree": _digest("head-tree"),
        "index_tree": _digest("index-tree"),
        "complete": True,
        "paths": [
            {
                "path": "src/app.py",
                "xy": "M",
                "content_hash": _digest("app"),
                "mode": "100644",
                "kind": "file",
                "protected": False,
                "foreign": False,
            }
        ],
    }


def test_final_parser_registers_prepare() -> None:
    parser = create_parser(only="final")
    args = parser.parse_args(["final", "prepare", "completion.json", "-j"])

    assert args.final_subcommand == "prepare"
    assert args.manifest == "completion.json"
    assert args.json is True


def test_prepare_seals_an_intent_without_submitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check-full"]},
        "declaration": valid_manifest(publication),
    }

    prepared = prepare_conditional_completion(wrapper)

    assert prepared.intent["status"] == "prepared"
    assert prepared.intent_ref
    assert prepared.preview["success_action"] == "complete"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_prepare_rejects_missing_repository_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.declaration import FinalizerDeclarationError

    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    manifest = valid_manifest(publication)
    manifest["payloads"][0]["payload"]["repositories"] = []  # type: ignore[index]

    with pytest.raises(FinalizerDeclarationError, match="missing repository decisions"):
        prepare_conditional_completion(
            {
                "success_message": "Required checks passed.",
                "verification": {"command": ["just", "check-full"]},
                "declaration": manifest,
            }
        )
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_read_prepare_manifest_from_file(tmp_path: Path) -> None:
    path = tmp_path / "completion.json"
    path.write_text(
        '{"success_message": "ok", "verification": {"command": ["just", "check"]}, '
        '"declaration": {"payloads": []}}',
        encoding="utf-8",
    )

    payload = read_prepare_manifest(str(path))

    assert payload["success_message"] == "ok"
