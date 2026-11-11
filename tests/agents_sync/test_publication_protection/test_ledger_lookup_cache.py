"""Validated-ledger lookup caching for publication protection."""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path

import pytest

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync import _publication_protection_ledger as ledger
from sase.agents_sync import publication_protection as protection
from sase.core.agent_publication_protection import (
    publication_protection_lookup_enforced as rust_lookup,
)
from tests.agents_sync.test_publication_protection._helpers import install_fake_core


@pytest.fixture(autouse=True)
def _clear_ledger_cache() -> Iterator[None]:
    ledger._clear_publication_protection_ledger_cache()
    yield
    ledger._clear_publication_protection_ledger_cache()


def _ledger_path(projects_root: Path, project_key: str = "alpha") -> Path:
    return (
        projects_root / project_key / protection.AGENT_PUBLICATION_PROTECTION_FILENAME
    )


def _identity(
    *,
    relative_destination: str = "agents/alice.athena.worker/chat.md",
    sha256: str = "a" * 64,
) -> dict[str, str]:
    return {
        "repository_identity": "sase-org/sase--agents",
        "relative_destination": relative_destination,
        "sha256": sha256,
    }


def _record(
    identity: dict[str, str], *, rules_version: int = 2, status: str = "blocked"
) -> dict[str, object]:
    return {
        **identity,
        "status": status,
        "reason": "scanner_hit" if status == "blocked" else "scanner_unavailable",
        "affected_requests": ["request-a"],
        "evidence": (
            [
                {
                    "kind": "credential_pattern",
                    "rule_id": "synthetic-rule",
                    "line": 1,
                    "rules_version": rules_version,
                }
            ]
            if status == "blocked"
            else []
        ),
        "rules_versions": [rules_version] if status == "blocked" else [],
        "created_at": 1.0,
        "updated_at": 1.0,
    }


def _write_ledger(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "records": records}), encoding="utf-8"
    )


def _install_projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    projects_root = tmp_path / ".sase" / "projects"
    monkeypatch.setattr(ledger, "sase_projects_dir", lambda: projects_root)
    return projects_root


def test_unchanged_ledger_is_read_once_and_absent_triples_skip_rust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    _write_ledger(_ledger_path(projects_root), [])
    read_count = 0
    read_ledger = ledger._read_ledger

    def count_read(path: Path) -> dict[str, object]:
        nonlocal read_count
        read_count += 1
        return read_ledger(path)

    monkeypatch.setattr(ledger, "_read_ledger", count_read)

    def unexpected_rust_lookup(*_args: object, **_kwargs: object) -> None:
        pytest.fail("absent ledger identities must not call Rust")

    monkeypatch.setattr(
        ledger, "publication_protection_lookup_enforced", unexpected_rust_lookup
    )
    for _ in range(20):
        assert ledger.lookup_publication_content_record("alpha", **_identity()) is None

    assert read_count == 1


def test_present_and_stale_records_match_the_uncached_rust_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    present = _identity()
    stale = _identity(
        relative_destination="agents/alice.athena.worker/prompt.md",
        sha256="b" * 64,
    )
    path = _ledger_path(projects_root)
    _write_ledger(
        path,
        [_record(present), _record(stale, rules_version=1)],
    )
    raw_ledger = json.loads(path.read_text(encoding="utf-8"))

    expected_present = rust_lookup(raw_ledger, present)
    expected_stale = rust_lookup(raw_ledger, stale)
    actual_present = ledger.lookup_publication_content_record("alpha", **present)
    actual_stale = ledger.lookup_publication_content_record("alpha", **stale)

    assert expected_present is not None and expected_present["status"] == "blocked"
    assert actual_present == expected_present
    assert expected_stale is None
    assert actual_stale == expected_stale


def test_record_write_invalidates_cached_ledger_and_next_lookup_sees_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    path = _ledger_path(projects_root)
    _write_ledger(path, [])
    identity = _identity()
    assert ledger.lookup_publication_content_record("alpha", **identity) is None
    assert path in ledger._PUBLICATION_PROTECTION_LEDGER_CACHE

    protection.record_publication_bytes_scan(
        "alpha",
        repository_identity=identity["repository_identity"],
        relative_destination=identity["relative_destination"],
        verdict=protection.PublicationBytesVerdict(
            identity["sha256"],
            12,
            {
                "status": "blocked",
                "reason": "scanner_hit",
                "hit": {"kind": "credential_pattern", "rules_version": 2},
                "rules_version": 2,
            },
        ),
    )

    assert path not in ledger._PUBLICATION_PROTECTION_LEDGER_CACHE
    found = ledger.lookup_publication_content_record("alpha", **identity)
    assert found is not None and found["status"] == "blocked"


def test_clean_resolve_unlinks_last_record_and_drops_cache_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    path = _ledger_path(projects_root)
    identity = _identity()
    _write_ledger(path, [_record(identity, status="unverified")])
    assert ledger.lookup_publication_content_record("alpha", **identity) is not None
    assert path in ledger._PUBLICATION_PROTECTION_LEDGER_CACHE

    protection.record_publication_bytes_scan(
        "alpha",
        repository_identity=identity["repository_identity"],
        relative_destination=identity["relative_destination"],
        verdict=protection.PublicationBytesVerdict(
            identity["sha256"],
            12,
            {"status": "clean", "reason": "clean", "hit": None, "rules_version": 2},
        ),
    )

    assert not path.exists()
    assert path not in ledger._PUBLICATION_PROTECTION_LEDGER_CACHE
    assert ledger.lookup_publication_content_record("alpha", **identity) is None


def test_atomic_replacement_is_seen_on_the_next_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    path = _ledger_path(projects_root)
    first = _identity()
    second = _identity(
        relative_destination="agents/alice.athena.worker/prompt.md",
        sha256="b" * 64,
    )
    _write_ledger(path, [_record(first)])
    assert ledger.lookup_publication_content_record("alpha", **first) is not None

    replacement = path.with_suffix(".replacement")
    replacement.write_text(
        json.dumps({"schema_version": 1, "records": [_record(second)]}),
        encoding="utf-8",
    )
    os.replace(replacement, path)

    assert ledger.lookup_publication_content_record("alpha", **first) is None
    found = ledger.lookup_publication_content_record("alpha", **second)
    assert found is not None and found["sha256"] == second["sha256"]


def test_invalid_ledger_is_not_cached_and_later_valid_content_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_core(monkeypatch)
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    path = _ledger_path(projects_root)
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    identity = _identity()

    assert ledger.lookup_publication_content_record("alpha", **identity) is None
    assert path not in ledger._PUBLICATION_PROTECTION_LEDGER_CACHE

    replacement = path.with_suffix(".replacement")
    replacement.write_text(
        json.dumps({"schema_version": 1, "records": [_record(identity)]}),
        encoding="utf-8",
    )
    os.replace(replacement, path)

    found = ledger.lookup_publication_content_record("alpha", **identity)
    assert found is not None and found["status"] == "blocked"


def test_missing_ledger_returns_none_without_creating_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _install_projects_root(tmp_path, monkeypatch)

    assert ledger.lookup_publication_content_record("alpha", **_identity()) is None

    assert not projects_root.exists()


def test_drain_timeout_during_ledger_read_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _install_projects_root(tmp_path, monkeypatch)
    path = _ledger_path(projects_root)
    _write_ledger(path, [])

    def timeout(_path: Path) -> dict[str, object]:
        raise PublicationDrainTimedOut("publication drain deadline reached")

    monkeypatch.setattr(ledger, "_read_ledger", timeout)

    with pytest.raises(PublicationDrainTimedOut):
        ledger.lookup_publication_content_record("alpha", **_identity())
