"""Local bearer-token store for remote machine enrollment."""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.memory.locks import locked_file

from .models import CredentialRecord, MachineDiagnostic, is_reference_id

CREDENTIAL_STORE_SCHEMA_VERSION = 1
_MAX_CREDENTIAL_STORE_BYTES = 512 * 1024


class CredentialStoreError(RuntimeError):
    """Raised when the local dispatch credential store cannot be used."""


def _credential_store_path(home: Path | None = None) -> Path:
    """Return the local client credential store path."""
    root = home if home is not None else sase_home()
    return root / "fleet" / "credentials.json"


class LocalCredentialStore:
    """Small locked JSON store for remote-machine bearer tokens."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _credential_store_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def has(self, ref: str) -> bool:
        return self.get(ref) is not None

    def get(self, ref: str) -> CredentialRecord | None:
        payload = self._read_payload()
        raw = _records(payload).get(ref)
        if not isinstance(raw, Mapping):
            return None
        return _credential_from_payload(raw)

    def put(self, record: CredentialRecord) -> None:
        if not is_reference_id(record.ref):
            raise CredentialStoreError("credential ref must be an opaque reference id")
        if not record.token:
            raise CredentialStoreError("credential token must be non-empty")
        with locked_file(self.lock_path, fcntl.LOCK_EX, timeout=2.0):
            payload = self._read_payload()
            records = dict(_records(payload))
            records[record.ref] = _credential_to_payload(record)
            payload = {
                "schema_version": CREDENTIAL_STORE_SCHEMA_VERSION,
                "records": records,
            }
            self._write_payload(payload)

    def delete(self, ref: str) -> bool:
        with locked_file(self.lock_path, fcntl.LOCK_EX, timeout=2.0):
            payload = self._read_payload()
            records = dict(_records(payload))
            if ref not in records:
                return False
            del records[ref]
            payload = {
                "schema_version": CREDENTIAL_STORE_SCHEMA_VERSION,
                "records": records,
            }
            self._write_payload(payload)
            return True

    def metadata(self) -> tuple[dict[str, object], ...]:
        payload = self._read_payload()
        rows: list[dict[str, object]] = []
        for ref, raw in sorted(_records(payload).items()):
            if not isinstance(raw, Mapping):
                continue
            record = _credential_from_payload(raw)
            if record is None:
                continue
            rows.append(record.metadata())
        return tuple(rows)

    def diagnose(self, ref: str) -> MachineDiagnostic:
        try:
            record = self.get(ref)
        except CredentialStoreError as exc:
            return MachineDiagnostic(
                code="credential_store_unreadable",
                severity="error",
                message=f"credential store is unreadable: {exc}",
            )
        if record is None:
            return MachineDiagnostic(
                code="credential_missing",
                severity="error",
                message=f"credential ref {ref} is missing from the local store",
            )
        return MachineDiagnostic(
            code="credential_present",
            severity="info",
            message=f"credential ref {ref} is present",
        )

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": CREDENTIAL_STORE_SCHEMA_VERSION, "records": {}}
        try:
            if self.path.stat().st_size > _MAX_CREDENTIAL_STORE_BYTES:
                raise CredentialStoreError("credential store exceeds size limit")
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except CredentialStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize unsafe parse details.
            raise CredentialStoreError(
                f"credential store could not be loaded: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise CredentialStoreError("credential store root must be a JSON object")
        if payload.get("schema_version") != CREDENTIAL_STORE_SCHEMA_VERSION:
            raise CredentialStoreError("credential store schema version is unsupported")
        if not isinstance(payload.get("records"), dict):
            raise CredentialStoreError("credential store records must be a mapping")
        return payload

    def _write_payload(self, payload: Mapping[str, Any]) -> None:
        assert_test_state_write_isolated(
            self.path,
            category="dispatch credential",
        )
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(f"{text}\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.path)
        os.chmod(self.path, 0o600)


def _records(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    records = payload.get("records")
    return records if isinstance(records, Mapping) else {}


def _credential_to_payload(record: CredentialRecord) -> dict[str, object]:
    payload = record.metadata()
    payload.update(
        {
            "schema_version": CREDENTIAL_STORE_SCHEMA_VERSION,
            "token": record.token,
        }
    )
    return payload


def _credential_from_payload(raw: Mapping[str, Any]) -> CredentialRecord | None:
    ref = raw.get("ref")
    token = raw.get("token")
    token_type = raw.get("token_type")
    provider_ref = raw.get("provider_ref")
    endpoint = raw.get("endpoint")
    installation_id = raw.get("installation_id")
    if not isinstance(ref, str) or not ref:
        return None
    if not isinstance(token, str) or not token:
        return None
    if not isinstance(token_type, str) or not token_type:
        return None
    if not isinstance(provider_ref, str) or not provider_ref:
        return None
    if not isinstance(endpoint, str) or not endpoint:
        return None
    if not isinstance(installation_id, str) or not installation_id:
        return None
    credential_id = raw.get("credential_id")
    issued = raw.get("issued_at_unix")
    expires = raw.get("expires_at_unix")
    scopes_raw = raw.get("scopes", ())
    scopes = (
        tuple(str(item) for item in scopes_raw if isinstance(item, str))
        if isinstance(scopes_raw, list)
        else ()
    )
    return CredentialRecord(
        ref=ref,
        token=token,
        token_type=token_type,
        provider_ref=provider_ref,
        endpoint=endpoint,
        installation_id=installation_id,
        credential_id=credential_id if isinstance(credential_id, str) else "",
        scopes=scopes,
        issued_at_unix=float(issued) if isinstance(issued, (int, float)) else None,
        expires_at_unix=float(expires) if isinstance(expires, (int, float)) else None,
    )


__all__ = [
    "CREDENTIAL_STORE_SCHEMA_VERSION",
    "CredentialStoreError",
    "LocalCredentialStore",
]
