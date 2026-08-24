"""Coverage for declaration-channel publish/submit lock serialization."""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from sase.finalizers import declaration as declaration_module
from sase.finalizers.declaration import (
    FINAL_CONTEXT_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def test_submit_rereads_context_and_rejects_in_lock_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)

    def hook(point: str) -> None:
        if point != "submit_after_validate":
            return
        payload = json.loads(
            (tmp_path / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8")
        )
        payload["context"]["context_digest"] = "0" * 64
        (tmp_path / FINAL_CONTEXT_FILENAME).write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)
    with pytest.raises(FinalizerDeclarationError, match="changed|stale"):
        submit_final_manifest(manifest)
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).is_file()


def test_publish_and_submit_serialize_on_declaration_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    publisher_holding = threading.Event()
    submitter_before = threading.Event()
    submitter_holding = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hook(point: str) -> None:
        name = threading.current_thread().name
        if point == "before_declaration_lock" and name == "submitter":
            submitter_before.set()
        if point != "holding_declaration_lock":
            return
        if name == "publisher":
            publisher_holding.set()
            assert release.wait(timeout=5)
            return
        submitter_holding.set()

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)

    def publish() -> None:
        try:
            publish_final_context()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    def submit() -> None:
        try:
            submit_final_manifest(manifest)
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    publisher = threading.Thread(target=publish, name="publisher")
    submitter = threading.Thread(target=submit, name="submitter")
    publisher.start()
    assert publisher_holding.wait(timeout=5)
    submitter.start()
    assert submitter_before.wait(timeout=5)
    assert not submitter_holding.is_set()
    release.set()
    publisher.join(timeout=5)
    submitter.join(timeout=5)
    assert not publisher.is_alive()
    assert not submitter.is_alive()
    assert errors == []
    assert submitter_holding.is_set()


def test_simultaneous_republish_and_submit_keep_acceptance_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = {"src/app.py": ("M", "abc123")}
    prepare_dirty_declaration(monkeypatch, tmp_path, fingerprints=fingerprints)
    publication = publish_final_context()
    manifest = valid_manifest(publication)
    start = threading.Barrier(2)
    accepted: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def hook(point: str) -> None:
        if point == "before_declaration_lock":
            start.wait(timeout=5)

    monkeypatch.setattr(declaration_module, "_declaration_sync_hook", hook)

    def do_submit() -> None:
        try:
            accepted.append(submit_final_manifest(manifest))
        except FinalizerDeclarationError as exc:
            errors.append(exc)

    def do_publish() -> None:
        fingerprints["src/app.py"] = ("M", "changed")
        try:
            publish_final_context()
        except BaseException as exc:  # noqa: BLE001 - collected by parent
            errors.append(exc)

    threads = [
        threading.Thread(target=do_submit, name="submitter"),
        threading.Thread(target=do_publish, name="publisher"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    latest = json.loads((tmp_path / FINAL_CONTEXT_FILENAME).read_text(encoding="utf-8"))
    assert accepted == []
    assert len(errors) == 1
    assert isinstance(errors[0], FinalizerDeclarationError)
    assert errors[0].code == "stale_final_context"
    assert latest["context"]["context_digest"] != publication.context.context_digest
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()
