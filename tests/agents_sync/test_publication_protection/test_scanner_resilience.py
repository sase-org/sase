"""Scanner failure modes for publication protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync import publication_protection as protection
from tests.agents_sync.test_publication_protection._helpers import (
    install_fake_core,
    install_fake_scanner,
)


def test_scanner_exception_is_unverified_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )

    def broken_binding(_name: str):
        def fail(*_args: object) -> dict[str, object]:
            raise RuntimeError("SYNTHETIC_SECRET_DO_NOT_LOG")

        return fail

    monkeypatch.setattr("sase.core.rust.require_rust_binding", broken_binding)
    source = tmp_path / "source.txt"
    source.write_bytes(b"candidate")
    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.disposition == {
            "schema_version": 1,
            "status": "unverified",
            "reason": "scan_error",
            "hit": None,
            "rules_version": None,
        }
        assert source.read_bytes() == b"candidate"


def test_missing_scanner_binding_is_unverified_and_value_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )

    def missing_binding(name: str) -> None:
        raise AttributeError(f"missing binding {name}")

    monkeypatch.setattr("sase.core.rust.require_rust_binding", missing_binding)
    source = tmp_path / "source.txt"
    source.write_bytes(b"SYNTHETIC_SECRET_DO_NOT_LOG")
    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == "unverified"
        assert candidate.disposition["reason"] == "scanner_unavailable"
        assert "SYNTHETIC_SECRET_DO_NOT_LOG" not in str(candidate.disposition)
        assert source.exists()


def test_oversized_text_is_skipped_without_raising_scanner_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    scanned_paths = install_fake_scanner(monkeypatch, outcome="skipped")
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 16)

    with protection.scan_publication_candidate(source, max_bytes=8) as candidate:
        assert not candidate.is_publishable
        assert candidate.staged_path is None
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == "unverified"
        assert candidate.sha256 is not None
        assert scanned_paths == [source]


def test_symlink_candidate_is_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_core(monkeypatch)
    install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(
        "sase.agents_sync._publication_protection_scan.sase_home",
        lambda: tmp_path / ".sase",
    )
    source = tmp_path / "source.txt"
    source.write_text("clean", encoding="utf-8")
    symlink = tmp_path / "link.txt"
    symlink.symlink_to(source)

    with protection.scan_publication_candidate(symlink, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.sha256 is None
