"""No-new prepare sealing and submit provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.prepare import (
    format_prepare_preview,
    prepare_conditional_completion,
)

from ..finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)
from ._no_new_receipt import needs_no_new_core

__all__ = [
    "test_ordinary_submit_records_unverified_provenance",
    "test_prepare_defaults_to_pass_and_rejects_malformed_accept",
    "test_prepare_seals_explicit_no_new",
]


def test_prepare_defaults_to_pass_and_rejects_malformed_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [
            {
                "repo_id": repo_id,
                "kind": "main",
                "name": "main",
                "head": "a" * 64,
                "head_tree": "a" * 64,
                "index_tree": "a" * 64,
                "complete": True,
                "paths": [],
            }
        ],
    )

    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check"]},
        "declaration": valid_manifest(publication),
    }
    prepared = prepare_conditional_completion(wrapper)
    assert prepared.intent.get("accept", "pass") == "pass"
    assert "accept" not in format_prepare_preview(prepared, json_output=False)

    with pytest.raises(FinalizerDeclarationError, match="must be 'pass'"):
        prepare_conditional_completion(dict(wrapper, accept="sometimes"))
    with pytest.raises(FinalizerDeclarationError, match="must be 'pass'"):
        prepare_conditional_completion(dict(wrapper, accept=7))


@needs_no_new_core
def test_prepare_seals_explicit_no_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [
            {
                "repo_id": repo_id,
                "kind": "main",
                "name": "main",
                "head": "a" * 64,
                "head_tree": "a" * 64,
                "index_tree": "a" * 64,
                "complete": True,
                "paths": [],
            }
        ],
    )
    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check"]},
        "declaration": valid_manifest(publication),
        "accept": "no-new",
    }

    prepared = prepare_conditional_completion(wrapper)

    assert prepared.intent["accept"] == "no_new_failures"
    assert "accept" in format_prepare_preview(prepared, json_output=False)


def test_ordinary_submit_records_unverified_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.finalizers.declaration import submit_final_manifest

    prepare_dirty_declaration(monkeypatch, tmp_path)
    from sase.finalizers.declaration import publish_final_context

    publication = publish_final_context()
    manifest = valid_manifest(publication)

    payload = submit_final_manifest(manifest)

    assert payload["verdict_provenance"] == "unverified"
