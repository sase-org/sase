"""Clean and blocked scan staging for publication protection."""

from __future__ import annotations

import hashlib
from pathlib import Path
import stat

import pytest

from sase.agents_sync import publication_protection as protection
from tests.agents_sync.test_publication_protection._helpers import (
    install_fake_core,
    install_fake_scanner,
)


def test_clean_scan_stages_private_bytes_and_copies_only_the_verified_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    scanned_paths = install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    source = tmp_path / "source.txt"
    source.write_bytes(b"clean transcript bytes\n")

    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert candidate.is_publishable
        assert candidate.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        assert len(scanned_paths) == 1
        assert scanned_paths[0] == candidate.staged_path
        assert scanned_paths[0] != source
        assert str(scanned_paths[0]).startswith(
            str(
                tmp_path
                / ".sase"
                / "private"
                / protection.PRIVATE_SCAN_STAGING_DIRECTORY
            )
        )
        assert scanned_paths[0].read_bytes() == source.read_bytes()
        assert stat.S_IMODE(scanned_paths[0].stat().st_mode) == 0o600

        destination = tmp_path / "publication" / "chat.md"
        candidate.copy_verified_to(destination)
        assert destination.read_bytes() == source.read_bytes()
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == candidate.sha256


def test_hit_is_withheld_and_persists_only_metadata_across_restart(
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
    source = tmp_path / "source.txt"
    source.write_bytes(b"SYNTHETIC_SECRET_DO_NOT_STORE\n")

    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == "blocked"
        ledger = protection.record_publication_scan(
            "alpha",
            repository_identity="sase-org/sase--agents",
            relative_destination="agents/alice/run/chat.md",
            candidate=candidate,
            affected_requests=("request-a",),
            timestamp=10.0,
        )

    assert ledger is not None
    ledger_path = (
        projects_root / "alpha" / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    )
    persisted = ledger_path.read_text(encoding="utf-8")
    assert "SYNTHETIC_SECRET_DO_NOT_STORE" not in persisted
    assert "private-key-header" in persisted
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    reloaded = protection.read_publication_protection_ledger_from_path(
        ledger_path, "alpha"
    )
    assert reloaded is not None
    row = reloaded["records"][0]
    identity = {
        "repository_identity": "sase-org/sase--agents",
        "relative_destination": "agents/alice/run/chat.md",
        "sha256": candidate.sha256,
    }
    assert not protection.publication_content_retry_allowed(
        "alpha",
        **identity,
    )
    assert protection.publication_content_retry_allowed(
        "alpha",
        **{**identity, "sha256": "b" * 64},
    )
    assert row["affected_requests"] == ["request-a"]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("skipped", "unverified"), ("hit", "blocked")],
)
def test_nonclean_scan_never_authorizes_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected: str,
) -> None:
    install_fake_core(monkeypatch)
    install_fake_scanner(monkeypatch, outcome=outcome)
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    source = tmp_path / "source.txt"
    source.write_bytes(b"synthetic candidate bytes")

    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == expected
        with pytest.raises(RuntimeError, match="complete text scan"):
            candidate.copy_verified_to(tmp_path / "publication.txt")
    assert source.exists()
