"""Continuation capture storage and checkpoint tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests._continuation_capture_helpers import json_record


def test_immutable_writes_are_idempotent_and_reject_conflicts(tmp_path: Path) -> None:
    from sase.continuation_capture import PublicationTransaction
    from sase.continuation_capture._storage import _PublicationConflictError

    root = tmp_path / "continuation"
    payload = {"schema_version": 1, "kind": "record", "value": "same"}
    first = PublicationTransaction(root)
    first.write_record("records", "item.json", payload=payload)
    first.commit()
    retry = PublicationTransaction(root)
    retry.write_record("records", "item.json", payload=payload)
    retry.commit()
    conflict = PublicationTransaction(root)
    conflict.write_record("records", "item.json", payload={**payload, "value": "other"})
    with pytest.raises(_PublicationConflictError):
        conflict.commit()


def test_journal_pointer_failure_does_not_publish_success(tmp_path: Path) -> None:
    from sase.continuation_capture import PublicationTransaction
    from sase.continuation_capture._storage import _write_pointer_bytes

    root = tmp_path / "continuation"
    original = _write_pointer_bytes

    def fail_on_manifest(path: Path, data: bytes) -> str:
        if path.name == "manifest.json":
            raise OSError("injected disk failure")
        return original(path, data)

    txn = PublicationTransaction(root)
    txn.write_record("records", "item.json", payload={"ok": True})
    txn.write_pointer("manifest.json", payload={"pointer": True})
    with patch(
        "sase.continuation_capture._storage._write_pointer_bytes",
        side_effect=fail_on_manifest,
    ):
        with pytest.raises(OSError, match="injected disk failure"):
            txn.commit()
    assert not (root / "manifest.json").exists()
    assert (root / "records" / "item.json").exists()
    assert not (root / ".publication_journal.json").exists()


def test_authored_checkpoint_parses_yaml_and_rejects_next_action(
    tmp_path: Path,
) -> None:
    from sase.continuation_capture import (
        AuthoredCheckpointError,
        load_authored_checkpoint,
        persist_authored_checkpoint,
    )

    path = tmp_path / "checkpoint.yml"
    path.write_text(
        "\n".join(
            [
                "objective: Finish the landing",
                "constraints:",
                "  - Keep hostile # New Query headings literal",
                "findings: The parent node exists",
                "unresolved_decisions:",
                "  - Which model?",
                "remaining_work: Persist exact parents",
                "source_refs: [file:explicit:abc]",
                "coverage: [agent-delta:run:1]",
            ]
        ),
        encoding="utf-8",
    )
    authored = load_authored_checkpoint(path)
    assert authored.content_ref.startswith("sha256:")
    assert authored.payload["objective"] == "Finish the landing"
    assert "next_action" not in authored.payload
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    ref = persist_authored_checkpoint(artifacts, authored)
    assert ref.startswith("local:continuation/checkpoints/")
    stored = json_record(
        artifacts / "continuation" / ref.removeprefix("local:continuation/")
    )
    assert stored["author"]["actor_kind"] == "user"

    bad = tmp_path / "bad.yml"
    bad.write_text("next_action: do the thing\nobjective: nope\n", encoding="utf-8")
    with pytest.raises(AuthoredCheckpointError, match="next-action"):
        load_authored_checkpoint(bad)
