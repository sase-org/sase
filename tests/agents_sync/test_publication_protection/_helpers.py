"""Shared builders for publication-protection tests.

Split from ``tests.agents_sync.test_publication_protection``; the names here
are public so sibling test modules can import them without touching a
``_``-prefixed symbol across files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sase.agents_sync import publication_protection as protection


def install_fake_core(monkeypatch: pytest.MonkeyPatch) -> None:
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


def install_fake_scanner(
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


def seed_stale_openai_block(
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
