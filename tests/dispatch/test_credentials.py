"""Local dispatch credential store tests.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.dispatch.credentials import CredentialStoreError, LocalCredentialStore
from sase.dispatch.models import CredentialRecord
from tests.conftest import redirect_sase_home


def _credential(
    ref: str = "fleet:alpha",
    *,
    token: str = "secret-token",
) -> CredentialRecord:
    return CredentialRecord(
        ref=ref,
        token=token,
        token_type="bearer",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        installation_id="sase_inst_v1_" + "a" * 64,
    )


def test_credential_store_round_trip_uses_restrictive_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = LocalCredentialStore()

    store.put(_credential())

    assert store.path.stat().st_mode & 0o777 == 0o600
    loaded = store.get("fleet:alpha")
    assert loaded is not None
    assert loaded.token == "secret-token"
    assert store.has("fleet:alpha")
    assert store.delete("fleet:alpha") is True
    assert store.delete("fleet:alpha") is False


def test_credential_metadata_never_exposes_tokens(tmp_path: Path) -> None:
    store = LocalCredentialStore(tmp_path / "credentials.json")
    store.put(_credential())

    rows = store.metadata()

    assert len(rows) == 1
    assert "token" not in rows[0]
    assert "secret-token" not in json.dumps(rows)


def test_credential_store_rejects_invalid_records(tmp_path: Path) -> None:
    store = LocalCredentialStore(tmp_path / "credentials.json")

    with pytest.raises(CredentialStoreError):
        store.put(_credential(ref="not a reference id"))
    with pytest.raises(CredentialStoreError):
        store.put(_credential(token=""))


def test_credential_store_rejects_corrupt_payloads(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(CredentialStoreError):
        LocalCredentialStore(path).get("fleet:alpha")

    path.write_text(
        json.dumps({"schema_version": 999, "records": {}}),
        encoding="utf-8",
    )
    with pytest.raises(CredentialStoreError):
        LocalCredentialStore(path).get("fleet:alpha")
