"""Tests for private staging and durable publication-protection state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

import pytest

from sase.agents_sync import (
    _publication_protection_ledger as protection_ledger,
    _publication_protection_scan as protection_scan,
    publication_protection as protection,
)


def _install_fake_core(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_by_identity: dict[tuple[str, str, str], dict[str, object]] = {}

    def require_binding(name: str):
        if name == "publication_scan_disposition":

            def disposition(request: dict[str, object]) -> dict[str, object]:
                scan = request.get("scan")
                failure = request.get("failure")
                if failure is not None:
                    return {
                        "schema_version": 1,
                        "status": "unverified",
                        "reason": failure,
                        "hit": None,
                        "rules_version": None,
                    }
                assert isinstance(scan, dict)
                outcome = scan["outcome"]
                status = {
                    "clean": "clean",
                    "hit": "blocked",
                    "skipped": "unverified",
                }[str(outcome)]
                return {
                    "schema_version": 1,
                    "status": status,
                    "reason": "scanner_hit" if outcome == "hit" else str(outcome),
                    "hit": scan.get("hit"),
                    "rules_version": scan.get("rules_version"),
                }

            return disposition
        if name == "publication_protection_ledger_empty":
            return lambda: {"schema_version": 1, "records": []}
        if name == "publication_protection_ledger_validate":
            return lambda ledger: ledger
        if name == "publication_protection_record_from_scan":

            def record(request: dict[str, object]) -> dict[str, object] | None:
                disposition = request["disposition"]
                assert isinstance(disposition, dict)
                if disposition["status"] == "clean":
                    return None
                identity = request["identity"]
                assert isinstance(identity, dict)
                timestamp = request["timestamp"]
                return {
                    **identity,
                    "status": disposition["status"],
                    "reason": disposition["reason"],
                    "affected_requests": request["affected_requests"],
                    "evidence": [disposition["hit"]] if disposition["hit"] else [],
                    "rules_versions": [disposition["rules_version"]]
                    if disposition["rules_version"]
                    else [],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }

            return record
        if name == "publication_protection_record_from_rejection":
            return lambda _request: None
        if name == "publication_protection_upsert":

            def upsert(request: dict[str, object]) -> dict[str, object]:
                ledger = request["ledger"]
                record = request["record"]
                assert isinstance(ledger, dict) and isinstance(record, dict)
                key = (
                    str(record["repository_identity"]),
                    str(record["relative_destination"]),
                    str(record["sha256"]),
                )
                previous = ledger_by_identity.get(key)
                if previous is not None:
                    record = {
                        **previous,
                        **record,
                        "affected_requests": sorted(
                            set(previous["affected_requests"])
                            | set(record["affected_requests"])
                        ),
                    }
                ledger_by_identity[key] = record
                return {
                    "schema_version": 1,
                    "records": list(ledger_by_identity.values()),
                }

            return upsert
        if name == "publication_protection_retry_allowed":

            def retry_allowed(request: dict[str, object]) -> bool:
                identity = request["identity"]
                assert isinstance(identity, dict)
                key = (
                    str(identity["repository_identity"]),
                    str(identity["relative_destination"]),
                    str(identity["sha256"]),
                )
                record = ledger_by_identity.get(key)
                return record is None or record["status"] != "blocked"

            return retry_allowed
        if name == "publication_protection_resolve_verified_clean":

            def resolve_clean(request: dict[str, object]) -> dict[str, object]:
                ledger = request["ledger"]
                identity = request["identity"]
                assert isinstance(ledger, dict) and isinstance(identity, dict)
                key = (
                    str(identity["repository_identity"]),
                    str(identity["relative_destination"]),
                    str(identity["sha256"]),
                )
                rows = ledger["records"]
                assert isinstance(rows, list)
                retained = [
                    row
                    for row in rows
                    if not (
                        isinstance(row, dict)
                        and (
                            str(row["repository_identity"]),
                            str(row["relative_destination"]),
                            str(row["sha256"]),
                        )
                        == key
                        and row["status"] == "unverified"
                    )
                ]
                ledger_by_identity.clear()
                for row in retained:
                    assert isinstance(row, dict)
                    ledger_by_identity[
                        (
                            str(row["repository_identity"]),
                            str(row["relative_destination"]),
                            str(row["sha256"]),
                        )
                    ] = row
                return {"schema_version": 1, "records": retained}

            return resolve_clean
        if name == "publication_protection_lookup":
            return lambda _request: None
        raise AssertionError(f"unexpected Rust binding: {name}")

    monkeypatch.setattr(
        "sase.core.agent_publication_protection.require_rust_binding",
        require_binding,
    )


def _install_fake_scanner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: str,
) -> list[Path]:
    scanned_paths: list[Path] = []

    def require_binding(name: str):
        assert name == "attachment_scan_file"

        def scan(
            path: str,
            max_bytes: int,
            _env: dict[str, str],
            _home: str,
            _sase_home: str,
        ) -> dict[str, object]:
            candidate = Path(path)
            scanned_paths.append(candidate)
            count = candidate.stat().st_size
            return {
                "outcome": outcome,
                "hit": (
                    {
                        "kind": "credential_pattern",
                        "rule_id": "private-key-header",
                        "line": 2,
                    }
                    if outcome == "hit"
                    else None
                ),
                "bytes_scanned": (
                    min(count, max_bytes) if outcome == "skipped" else count
                ),
                "rules_version": 1,
            }

        return scan

    monkeypatch.setattr("sase.core.rust.require_rust_binding", require_binding)
    return scanned_paths


def test_clean_scan_stages_private_bytes_and_copies_only_the_verified_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_core(monkeypatch)
    scanned_paths = _install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
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
    _install_fake_core(monkeypatch)
    _install_fake_scanner(monkeypatch, outcome="hit")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
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
    reloaded = protection_ledger._read_publication_protection_ledger(
        "alpha",
        projects_root=projects_root,
    )
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
    _install_fake_core(monkeypatch)
    _install_fake_scanner(monkeypatch, outcome=outcome)
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    source = tmp_path / "source.txt"
    source.write_bytes(b"synthetic candidate bytes")

    with protection.scan_publication_candidate(source, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == expected
        with pytest.raises(RuntimeError, match="complete text scan"):
            candidate.copy_verified_to(tmp_path / "publication.txt")
    assert source.exists()


def test_scanner_exception_is_unverified_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_core(monkeypatch)
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")

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
    _install_fake_core(monkeypatch)
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")

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
    _install_fake_core(monkeypatch)
    scanned_paths = _install_fake_scanner(monkeypatch, outcome="skipped")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 16)

    with protection.scan_publication_candidate(source, max_bytes=8) as candidate:
        assert not candidate.is_publishable
        assert candidate.staged_path is None
        assert candidate.disposition is not None
        assert candidate.disposition["status"] == "unverified"
        assert candidate.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        assert scanned_paths == [source]


def test_clean_scan_resolves_transient_unverified_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_core(monkeypatch)
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
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
                "rules_version": 1,
            },
            None,
        )

    monkeypatch.setattr(protection_scan, "_scan_file", scan_file)
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


def test_symlink_candidate_is_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_core(monkeypatch)
    _install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    source = tmp_path / "source.txt"
    source.write_text("clean", encoding="utf-8")
    symlink = tmp_path / "link.txt"
    symlink.symlink_to(source)

    with protection.scan_publication_candidate(symlink, max_bytes=1024) as candidate:
        assert not candidate.is_publishable
        assert candidate.sha256 is None
