"""Reuse protection scans for bytes already published in a prior snapshot."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from sase.agents_sync import publication_protection as protection
from sase.agents_sync._publication_snapshot_gating import (
    gate_run_files,
    merge_richer_run_files,
)
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.publication_fixtures import _run


SCANNER_HIT = b"SYNTHETIC-PUBLICATION-SCANNER-HIT"


class _ProtectionSpies:
    def __init__(self) -> None:
        self.blocked: set[tuple[str, str]] = set()
        self.lookups: list[tuple[str, str]] = []
        self.scans: list[bytes] = []
        self.writes: list[tuple[str, str]] = []

    def reset(self) -> None:
        self.lookups.clear()
        self.scans.clear()
        self.writes.clear()


def _install_protection_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> _ProtectionSpies:
    spies = _ProtectionSpies()

    def lookup(
        _project_key: str,
        *,
        repository_identity: str,
        relative_destination: str,
        sha256: str,
    ) -> dict[str, str] | None:
        del repository_identity
        spies.lookups.append((relative_destination, sha256))
        if (relative_destination, sha256) in spies.blocked:
            return {"status": "blocked"}
        return None

    def scan(data: bytes, *, max_bytes: int):
        del max_bytes
        spies.scans.append(data)
        status = "blocked" if SCANNER_HIT in data else "clean"
        return protection.PublicationBytesVerdict(
            hashlib.sha256(data).hexdigest(),
            len(data),
            {"status": status},
        )

    def record(
        _project_key: str,
        *,
        repository_identity: str,
        relative_destination: str,
        verdict: protection.PublicationBytesVerdict,
        affected_requests=(),
    ) -> dict[str, str]:
        del repository_identity, affected_requests
        spies.writes.append((relative_destination, verdict.sha256 or ""))
        return {"status": verdict.disposition["status"]}  # type: ignore[index]

    monkeypatch.setattr(protection, "lookup_publication_content_record", lookup)
    monkeypatch.setattr(protection, "scan_publication_bytes", scan)
    monkeypatch.setattr(protection, "record_publication_bytes_scan", record)
    return spies


def _context() -> tuple[
    AgentOwnerIdentity, V2ProjectIdentity, protection.PublicationProtectionScope
]:
    owner = AgentOwnerIdentity("alice", "athena")
    project = V2ProjectIdentity("proj", "Project")
    scope = protection.PublicationProtectionScope(
        project_key="proj",
        repository_identity="https://example.test/agents.git",
    )
    return owner, project, scope


def _prior_record(
    run,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    scope: protection.PublicationProtectionScope,
    spies: _ProtectionSpies,
):
    initial = gate_run_files(run, owner, project, {}, scope=scope)
    assert initial.record is not None
    spies.reset()
    return initial.record


def test_unchanged_files_reuse_prior_verdict_without_scan_or_ledger_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    run = _run("foo.worker", "21")
    previous = _prior_record(run, owner, project, scope, spies)
    payload: dict[str, bytes] = {}

    gated = gate_run_files(run, owner, project, payload, scope=scope, previous=previous)

    assert gated.record is not None
    assert not spies.scans
    assert not spies.writes
    assert len(spies.lookups) == len(previous.files)
    assert payload["agents/alice.athena.foo.worker/chat.md"] == run.chat_bytes


def test_changed_chat_is_scanned_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    original = _run("foo.worker", "21")
    previous = _prior_record(original, owner, project, scope, spies)
    changed = replace(original, chat_bytes=b"updated chat\n")
    payload: dict[str, bytes] = {}

    gated = gate_run_files(
        changed, owner, project, payload, scope=scope, previous=previous
    )

    assert gated.record is not None
    assert spies.scans == [changed.chat_bytes]
    assert len(spies.writes) == 1
    assert payload["agents/alice.athena.foo.worker/chat.md"] == changed.chat_bytes


def test_new_run_scans_and_records_its_files(monkeypatch: pytest.MonkeyPatch) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    run = _run("foo.worker", "21")

    gated = gate_run_files(run, owner, project, {}, scope=scope)

    assert gated.record is not None
    assert len(spies.scans) == len(gated.record.files)
    assert len(spies.writes) == len(gated.record.files)


def test_blocked_identical_digest_is_withheld_before_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    run = _run("foo.worker", "21")
    previous = _prior_record(run, owner, project, scope, spies)
    chat = dict(previous.files)["chat"]
    spies.blocked.add((chat.path, chat.digest))
    payload: dict[str, bytes] = {}

    gated = gate_run_files(run, owner, project, payload, scope=scope, previous=previous)

    assert gated.record is not None
    assert "chat" in gated.blocked_kinds
    assert "chat" not in dict(gated.record.files)
    assert chat.path not in payload
    assert not spies.scans
    assert not spies.writes
    assert (chat.path, chat.digest) in spies.lookups


def test_scanner_hit_on_changed_chat_is_still_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    original = _run("foo.worker", "21")
    previous = _prior_record(original, owner, project, scope, spies)
    changed = replace(original, chat_bytes=b"changed " + SCANNER_HIT)
    payload: dict[str, bytes] = {}

    gated = gate_run_files(
        changed, owner, project, payload, scope=scope, previous=previous
    )

    assert gated.record is not None
    assert "chat" in gated.blocked_kinds
    assert "chat" not in dict(gated.record.files)
    assert "agents/alice.athena.foo.worker/chat.md" not in payload
    assert spies.scans == [changed.chat_bytes]
    assert len(spies.writes) == 1


def test_merge_reuses_matching_prior_content_without_scan_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _install_protection_spies(monkeypatch)
    owner, project, scope = _context()
    run = _run("foo.worker", "21")
    previous = _prior_record(run, owner, project, scope, spies)
    previous_files = dict(previous.files)
    for kind in ("prompt", "chat"):
        reference = previous_files[kind]
        path = tmp_path / reference.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(run.prompt_bytes if kind == "prompt" else run.chat_bytes)
    current = replace(
        previous,
        files=tuple(
            (kind, reference)
            for kind, reference in previous.files
            if kind not in {"prompt", "chat"}
        ),
    )
    payload: dict[str, bytes] = {}

    merged, _notes = merge_richer_run_files(
        current, previous, tmp_path, payload, scope=scope
    )

    assert {"prompt", "chat"} <= set(dict(merged.files))
    assert payload[previous_files["prompt"].path] == run.prompt_bytes
    assert payload[previous_files["chat"].path] == run.chat_bytes
    assert len(spies.lookups) == 2
    assert not spies.scans
    assert not spies.writes
