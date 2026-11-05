"""Ledger rescan and stale-block recovery for publication protection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync import publication_protection as protection
from tests.agents_sync.test_publication_protection._helpers import (
    install_fake_core,
    install_fake_scanner,
    seed_stale_openai_block,
)


def test_clean_scan_resolves_transient_unverified_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_ledger.sase_projects_dir",
        lambda: projects_root,
    )
    source = tmp_path / "source.txt"
    source.write_bytes(b"candidate bytes")
    results = iter(("skipped", "clean"))

    def scan_file(
        path: Path,
        *,
        max_bytes: int,
        env: dict[str, str] | None,
    ) -> tuple[dict[str, object], None]:
        del env
        return (
            {
                "outcome": next(results),
                "hit": None,
                "bytes_scanned": path.stat().st_size,
                "rules_version": 2,
            },
            None,
        )

    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan._scan_file", scan_file
    )
    identity = {
        "repository_identity": "sase-org/sase--agents",
        "relative_destination": "agents/a/run/chat.md",
    }
    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        first = protection.record_publication_scan(
            "alpha", **identity, candidate=candidate, timestamp=1.0
        )
    assert first is not None and first["records"][0]["status"] == "unverified"

    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        second = protection.record_publication_scan(
            "alpha", **identity, candidate=candidate, timestamp=2.0
        )
    assert second == {"schema_version": 1, "records": []}
    ledger_path = (
        projects_root / "alpha" / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    )
    assert not ledger_path.exists()


def test_stale_scanner_block_is_rescanned_and_superseded_on_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    scanned_paths = install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_ledger.sase_projects_dir",
        lambda: projects_root,
    )
    source = tmp_path / "run" / "meta.json"
    source.parent.mkdir()
    task_marker = b"ta" + b"sk-" + b"meta-name-with-a-long-tail"
    content = b'{"agent":"' + task_marker + b'"}\n'
    source.write_bytes(content)
    ledger_path, identity = seed_stale_openai_block(
        projects_root,
        relative_destination="agents/alice/run/meta.json",
        content=content,
    )

    assert protection.lookup_publication_content_record("alpha", **identity) is None
    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        result = protection.record_publication_scan(
            "alpha",
            repository_identity=str(identity["repository_identity"]),
            relative_destination=str(identity["relative_destination"]),
            candidate=candidate,
            affected_requests=("request-a",),
            timestamp=10.0,
        )

    assert scanned_paths
    assert result is not None
    assert result["records"] == []
    superseded = result["superseded"]
    assert isinstance(superseded, list) and len(superseded) == 1
    entry = superseded[0]
    assert isinstance(entry, dict)
    assert entry["record"]["evidence"][0]["rule_id"] == "openai-key"
    assert entry["superseded_at"] == 10.0
    assert entry["superseded_by_rules_version"] == 2
    assert entry["reason"] == "rescanned_clean"
    assert ledger_path.exists()
    persisted = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert persisted["superseded"] == superseded


def test_stale_scanner_block_that_still_hits_is_reblocked_with_current_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    install_fake_scanner(monkeypatch, outcome="hit")
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_ledger.sase_projects_dir",
        lambda: projects_root,
    )
    source = tmp_path / "run" / "meta.json"
    source.parent.mkdir()
    content = b"still blocked candidate bytes\n"
    source.write_bytes(content)
    _, identity = seed_stale_openai_block(
        projects_root,
        relative_destination="agents/alice/run/meta.json",
        content=content,
    )

    assert protection.lookup_publication_content_record("alpha", **identity) is None
    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        result = protection.record_publication_scan(
            "alpha",
            repository_identity=str(identity["repository_identity"]),
            relative_destination=str(identity["relative_destination"]),
            candidate=candidate,
            affected_requests=("request-a",),
            timestamp=10.0,
        )

    assert result is not None
    current = protection.lookup_publication_content_record("alpha", **identity)
    assert current is not None
    evidence = current["evidence"]
    assert isinstance(evidence, list)
    assert max(hit["rules_version"] for hit in evidence) == 2
