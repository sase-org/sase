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
                hit = scan.get("hit")
                if isinstance(hit, dict) and type(scan.get("rules_version")) is int:
                    hit = {**hit, "rules_version": scan["rules_version"]}
                return {
                    "schema_version": 1,
                    "status": status,
                    "reason": "scanner_hit" if outcome == "hit" else str(outcome),
                    "hit": hit,
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
                rows = ledger["records"]
                assert isinstance(rows, list)
                previous = next(
                    (
                        row
                        for row in rows
                        if isinstance(row, dict)
                        and (
                            str(row["repository_identity"]),
                            str(row["relative_destination"]),
                            str(row["sha256"]),
                        )
                        == key
                    ),
                    None,
                )
                if previous is not None:
                    record = {
                        **previous,
                        **record,
                        "affected_requests": sorted(
                            set(previous["affected_requests"])
                            | set(record["affected_requests"])
                        ),
                        "evidence": [
                            *previous.get("evidence", []),
                            *record.get("evidence", []),
                        ],
                        "rules_versions": sorted(
                            set(previous.get("rules_versions", []))
                            | set(record.get("rules_versions", []))
                        ),
                        "created_at": min(previous["created_at"], record["created_at"]),
                        "updated_at": max(previous["updated_at"], record["updated_at"]),
                    }
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
                    )
                ]
                retained.append(record)
                ledger_by_identity.clear()
                ledger_by_identity.update(
                    {
                        (
                            str(row["repository_identity"]),
                            str(row["relative_destination"]),
                            str(row["sha256"]),
                        ): row
                        for row in retained
                        if isinstance(row, dict)
                    }
                )
                result: dict[str, object] = {
                    "schema_version": 1,
                    "records": retained,
                }
                superseded = ledger.get("superseded")
                if superseded:
                    result["superseded"] = superseded
                return result

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
                clean_version = request.get("clean_rules_version")
                timestamp = request.get("timestamp")
                superseded = list(ledger.get("superseded", []))
                moved: dict[str, object] | None = None
                if type(clean_version) is int and type(timestamp) in {int, float}:
                    for row in rows:
                        if (
                            not isinstance(row, dict)
                            or (
                                str(row["repository_identity"]),
                                str(row["relative_destination"]),
                                str(row["sha256"]),
                            )
                            != key
                        ):
                            continue
                        evidence = row.get("evidence")
                        versions = (
                            [
                                hit.get("rules_version")
                                for hit in evidence
                                if isinstance(hit, dict)
                                and type(hit.get("rules_version")) is int
                            ]
                            if isinstance(evidence, list)
                            else []
                        )
                        known_value = isinstance(evidence, list) and any(
                            isinstance(hit, dict) and hit.get("kind") == "known_value"
                            for hit in evidence
                        )
                        if (
                            row.get("status") == "blocked"
                            and row.get("reason") == "scanner_hit"
                            and versions
                            and not known_value
                            and max(versions) < clean_version
                        ):
                            moved = row
                        break
                if moved is not None:
                    superseded.append(
                        {
                            "record": moved,
                            "superseded_at": timestamp,
                            "superseded_by_rules_version": clean_version,
                            "reason": "rescanned_clean",
                        }
                    )
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
                        and (row["status"] == "unverified" or row is moved)
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
                result: dict[str, object] = {
                    "schema_version": 1,
                    "records": retained,
                }
                if superseded:
                    result["superseded"] = superseded
                return result

            return resolve_clean
        if name == "publication_protection_lookup_enforced":

            def lookup(request: dict[str, object]) -> dict[str, object] | None:
                ledger = request["ledger"]
                identity = request["identity"]
                assert isinstance(ledger, dict) and isinstance(identity, dict)
                rows = ledger["records"]
                assert isinstance(rows, list)
                key = (
                    str(identity["repository_identity"]),
                    str(identity["relative_destination"]),
                    str(identity["sha256"]),
                )
                record = next(
                    (
                        row
                        for row in rows
                        if isinstance(row, dict)
                        and (
                            str(row["repository_identity"]),
                            str(row["relative_destination"]),
                            str(row["sha256"]),
                        )
                        == key
                    ),
                    None,
                )
                if name == "publication_protection_lookup_enforced" and record:
                    if not record_enforced(record):
                        return None
                return record

            return lookup
        if name == "publication_protection_record_enforced":
            return record_enforced
        raise AssertionError(f"unexpected Rust binding: {name}")

    def record_enforced(record: dict[str, object]) -> bool:
        if record.get("status") != "blocked" or record.get("reason") != "scanner_hit":
            return True
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return True
        if any(
            isinstance(hit, dict) and hit.get("kind") == "known_value"
            for hit in evidence
        ):
            return True
        versions = [
            hit.get("rules_version")
            for hit in evidence
            if isinstance(hit, dict) and type(hit.get("rules_version")) is int
        ]
        return not versions or max(versions) >= 2

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
                "rules_version": 2,
            }

        return scan

    monkeypatch.setattr("sase.core.rust.require_rust_binding", require_binding)
    return scanned_paths


def _seed_stale_openai_block(
    projects_root: Path,
    *,
    relative_destination: str,
    content: bytes,
) -> tuple[Path, dict[str, object]]:
    identity = {
        "repository_identity": "sase-org/sase--agents",
        "relative_destination": relative_destination,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    record: dict[str, object] = {
        **identity,
        "status": "blocked",
        "reason": "scanner_hit",
        "affected_requests": ["request-a"],
        "evidence": [
            {
                "kind": "credential_pattern",
                "rule_id": "openai-key",
                "line": 1,
                "rules_version": 1,
            }
        ],
        "rules_versions": [1],
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    path = projects_root / "alpha" / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "records": [record]}),
        encoding="utf-8",
    )
    return path, identity


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
                "rules_version": 2,
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


def test_stale_scanner_block_is_rescanned_and_superseded_on_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_core(monkeypatch)
    scanned_paths = _install_fake_scanner(monkeypatch, outcome="clean")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
    source = tmp_path / "run" / "meta.json"
    source.parent.mkdir()
    task_marker = b"ta" + b"sk-" + b"meta-name-with-a-long-tail"
    content = b'{"agent":"' + task_marker + b'"}\n'
    source.write_bytes(content)
    ledger_path, identity = _seed_stale_openai_block(
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
    _install_fake_core(monkeypatch)
    _install_fake_scanner(monkeypatch, outcome="hit")
    monkeypatch.setattr(protection_scan, "sase_home", lambda: tmp_path / ".sase")
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(protection_ledger, "sase_projects_dir", lambda: projects_root)
    source = tmp_path / "run" / "meta.json"
    source.parent.mkdir()
    content = b"still blocked candidate bytes\n"
    source.write_bytes(content)
    _, identity = _seed_stale_openai_block(
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
