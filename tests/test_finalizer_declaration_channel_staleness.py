"""Coverage for finalizer declaration-channel staleness and drift detection."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_CONTEXT_HOST_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    FINAL_SUBMISSION_HOST_FILENAME,
    FinalizerDeclarationError,
    final_submission_is_current,
    publish_final_context,
    submit_final_manifest,
)

from .finalizer_declaration_channel_test_helpers import (
    attempt_records,
    clean_state,
    dirty_state,
    prepare_dirty_declaration,
    valid_manifest,
)


def test_submit_accepts_manifest_and_retains_invalid_attempt_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    accepted = submit_final_manifest(manifest)

    stale = deepcopy(manifest)
    stale["context_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError, match="context"):
        submit_final_manifest(stale)

    assert accepted["validation"]["accepted_instances"] == ["commit"]
    assert (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()
    attempts = attempt_records(tmp_path)
    assert attempts[-2]["accepted"] is True
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_fingerprint_changed_since_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {"src/app.py": ("M", "abc123")}
    prepare_dirty_declaration(monkeypatch, tmp_path, fingerprints=fingerprints)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    fingerprints["src/app.py"] = ("M", "def456")

    with pytest.raises(FinalizerDeclarationError, match="rerun `sase final context`"):
        submit_final_manifest(manifest)

    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    assert not (tmp_path / FINAL_SUBMISSION_HOST_FILENAME).exists()
    attempts = attempt_records(tmp_path)
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "stale_final_context"
    assert "rerun `sase final context`" in str(attempts[-1]["message"])
    assert attempts[-1]["content_digest"]


def test_submit_rejects_dirty_context_that_became_clean_before_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = {"value": True}
    prepare_dirty_declaration(
        monkeypatch,
        tmp_path,
        collect=lambda _root: (
            dirty_state(tmp_path) if dirty["value"] else clean_state(tmp_path)
        ),
    )
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    dirty["value"] = False

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "stale_final_context"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
    refreshed = publish_final_context()
    assert refreshed.submission_required is False
    assert refreshed.payload["manifest_template"]["payloads"] == []
    assert final_submission_is_current(artifacts_dir=str(tmp_path)) is True


def test_submit_rejects_host_repository_snapshot_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    host_payload = json.loads(
        (tmp_path / FINAL_CONTEXT_HOST_FILENAME).read_text(encoding="utf-8")
    )
    host_payload["repositories"] = []
    (tmp_path / FINAL_CONTEXT_HOST_FILENAME).write_text(
        json.dumps(host_payload),
        encoding="utf-8",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest)

    assert exc_info.value.code == "stale_final_context"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_submit_rejects_stale_nonce_and_plan_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    stale_nonce = deepcopy(valid_manifest(publication))
    stale_nonce["turn_nonce"] = "other-nonce"
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_nonce)

    stale_plan = deepcopy(valid_manifest(publication))
    stale_plan["plan_digest"] = "0" * 64
    with pytest.raises(FinalizerDeclarationError):
        submit_final_manifest(stale_plan)
