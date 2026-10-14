"""Inspect one agent's recorded instruction bundle and manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.instructions.manifests import _RunManifest, read_run_manifests
from sase.instructions.run_index import (
    UnknownAgentError,
    enumerate_runs,
    read_json_object,
)


@dataclass(frozen=True)
class _Integrity:
    """Result of comparing stored bundle bytes to the manifest digest."""

    label: str
    data: bytes | None
    source: str
    expected_sha: str
    actual_sha: str | None

    @property
    def ok(self) -> bool:
        return self.label == "bytes match"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def check_bundle_integrity(entry: _RunManifest) -> _Integrity:
    """Sha256 the run copy, falling back to ``bundle.store_path``."""
    expected = ""
    store_path: str | None = None
    payload = entry.manifest if isinstance(entry.manifest, dict) else entry.raw
    if isinstance(payload, dict):
        bundle = payload.get("bundle")
        if isinstance(bundle, dict):
            raw_sha = bundle.get("sha256")
            if isinstance(raw_sha, str):
                expected = raw_sha
            raw_store = bundle.get("store_path")
            if isinstance(raw_store, str) and raw_store:
                store_path = raw_store
    data: bytes | None = None
    source = "missing"
    if entry.bundle_path is not None:
        data = _read_bytes(entry.bundle_path)
        if data is not None:
            source = "run"
    if data is None and store_path:
        data = _read_bytes(Path(store_path).expanduser())
        if data is not None:
            source = "store"
    if data is None:
        return _Integrity(
            label="missing",
            data=None,
            source=source,
            expected_sha=expected,
            actual_sha=None,
        )
    actual = _sha256_bytes(data)
    label = "bytes match" if expected and actual == expected else "MISMATCH"
    if not expected:
        label = "MISMATCH"
    return _Integrity(
        label=label,
        data=data,
        source=source,
        expected_sha=expected,
        actual_sha=actual,
    )


def _payload(entry: _RunManifest) -> dict[str, Any] | None:
    if isinstance(entry.manifest, dict):
        return entry.manifest
    if isinstance(entry.raw, dict):
        return entry.raw
    return None


def _delivery_fields(manifest: dict[str, Any] | None) -> tuple[str, str, int]:
    status = "—"
    channel = "—"
    attempt = 0
    if not isinstance(manifest, dict):
        return status, channel, attempt
    delivery = manifest.get("delivery")
    if not isinstance(delivery, dict):
        return status, channel, attempt
    raw_status = delivery.get("status")
    if isinstance(raw_status, str) and raw_status:
        status = raw_status
    raw_channel = delivery.get("channel")
    if isinstance(raw_channel, str) and raw_channel:
        channel = raw_channel
    raw_attempt = delivery.get("attempt")
    if isinstance(raw_attempt, int):
        attempt = raw_attempt
    return status, channel, attempt


def _bundle_fields(manifest: dict[str, Any] | None) -> tuple[str, str, int, int]:
    sha = ""
    common = ""
    size = 0
    tokens = 0
    if not isinstance(manifest, dict):
        return sha, common, size, tokens
    bundle = manifest.get("bundle")
    if not isinstance(bundle, dict):
        return sha, common, size, tokens
    raw_sha = bundle.get("sha256")
    if isinstance(raw_sha, str):
        sha = raw_sha
    raw_common = bundle.get("common_digest")
    if isinstance(raw_common, str):
        common = raw_common
    raw_bytes = bundle.get("bytes")
    if isinstance(raw_bytes, int):
        size = raw_bytes
    raw_tokens = bundle.get("tokens_est")
    if isinstance(raw_tokens, int):
        tokens = raw_tokens
    return sha, common, size, tokens


def _purpose(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict):
        return "—"
    facts = manifest.get("facts")
    if isinstance(facts, dict):
        raw = facts.get("purpose")
        if isinstance(raw, str) and raw:
            return raw
    return "—"


def _actor(entry: _RunManifest) -> str:
    if entry.actor:
        return entry.actor
    return "native_helper" if entry.is_helper else "sase_root"


def format_list_row(entry: _RunManifest, integrity: _Integrity) -> str:
    """One compact inventory row for ``show -l``."""
    payload = _payload(entry)
    status, channel, attempt = _delivery_fields(payload)
    sha, common, size, tokens = _bundle_fields(payload)
    return (
        f"{entry.seq:02d}  {entry.provider}  {_purpose(payload)}  "
        f"{attempt or '—'}  {_actor(entry)}  {status}  {channel}  "
        f"{(sha or '—')[:12]}  {(common or '—')[:12]}  {size}  {tokens}  "
        f"{integrity.label}"
    )


def list_row_dict(entry: _RunManifest, integrity: _Integrity) -> dict[str, Any]:
    """JSON object for one ``show -l -j`` row."""
    payload = _payload(entry)
    status, channel, attempt = _delivery_fields(payload)
    sha, common, size, tokens = _bundle_fields(payload)
    return {
        "seq": entry.seq,
        "provider": entry.provider,
        "purpose": _purpose(payload),
        "attempt": attempt or None,
        "actor": _actor(entry),
        "delivery_status": status,
        "channel": None if channel == "—" else channel,
        "sha256_prefix": sha[:12] if sha else None,
        "common_digest_prefix": common[:12] if common else None,
        "bytes": size,
        "tokens_est": tokens,
        "integrity": integrity.label,
        "is_helper": entry.is_helper,
        "parent_invocation_id": entry.parent_invocation_id,
    }


def _latest_seq(artifact_dir: str, entries: list[_RunManifest]) -> int | None:
    meta = read_json_object(Path(artifact_dir) / "agent_meta.json")
    instructions = meta.get("instructions")
    if isinstance(instructions, dict):
        latest = instructions.get("latest")
        if isinstance(latest, dict):
            raw = latest.get("seq")
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
    roots = [entry.seq for entry in entries if not entry.is_helper]
    if roots:
        return max(roots)
    if entries:
        return max(entry.seq for entry in entries)
    return None


def _pick_entry(
    entries: list[_RunManifest], *, seq: int, helper: bool
) -> _RunManifest | None:
    matches = [
        entry for entry in entries if entry.seq == seq and entry.is_helper is helper
    ]
    return matches[0] if matches else None


def _summary_line(entry: _RunManifest, integrity: _Integrity, *, agent: str) -> str:
    sha, _common, size, _tokens = _bundle_fields(_payload(entry))
    shown = (integrity.actual_sha or sha or "")[:12]
    role = "helper" if entry.is_helper else "root"
    return (
        f"show {agent} {entry.seq:02d} {entry.provider} {role} "
        f"{shown} bytes={size} source={integrity.source} {integrity.label}"
    )


def run_instructions_show(args: Any) -> int:
    """Print one agent's archived bundle or inventory and return an exit code."""
    agent = str(getattr(args, "agent", "") or "")
    want_json = bool(getattr(args, "json", False))
    want_list = bool(getattr(args, "list", False))
    want_helper = bool(getattr(args, "helper", False))
    want_sections = bool(getattr(args, "sections", False))
    seq_arg = getattr(args, "seq", None)
    try:
        scored = enumerate_runs(
            limit_per_provider=1,
            since=None,
            until=None,
            project=None,
            agent=agent,
            providers=(),
        )
    except UnknownAgentError as exc:
        print(f"sase instructions show: {exc}", file=sys.stderr)
        return 2
    if not scored:
        print(
            f"sase instructions show: agent {agent} has no recorded run artifacts",
            file=sys.stderr,
        )
        return 2
    artifact_dir = scored[0].artifact_dir
    instructions_dir = Path(artifact_dir) / "instructions"
    if not instructions_dir.is_dir():
        print(
            f"sase instructions show: agent {agent} has no instructions/ directory",
            file=sys.stderr,
        )
        return 2
    entries = read_run_manifests(artifact_dir)
    if not entries:
        print(
            f"sase instructions show: agent {agent} has no instruction manifests",
            file=sys.stderr,
        )
        return 2
    if want_list:
        rows = [(entry, check_bundle_integrity(entry)) for entry in entries]
        if want_json:
            print(
                json.dumps(
                    [list_row_dict(entry, integrity) for entry, integrity in rows],
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            for entry, integrity in rows:
                print(format_list_row(entry, integrity))
        if any(not integrity.ok for _entry, integrity in rows):
            return 1
        return 0
    if seq_arg is None:
        seq = _latest_seq(artifact_dir, entries)
    else:
        seq = int(seq_arg)
    if seq is None:
        print(
            f"sase instructions show: agent {agent} has no recorded invocation",
            file=sys.stderr,
        )
        return 2
    chosen = _pick_entry(entries, seq=seq, helper=want_helper)
    if chosen is None:
        kind = "helper bundle" if want_helper else "invocation"
        print(
            f"sase instructions show: agent {agent} has no {kind} for seq {seq:02d}",
            file=sys.stderr,
        )
        return 2
    integrity = check_bundle_integrity(chosen)
    print(_summary_line(chosen, integrity, agent=agent), file=sys.stderr)
    payload = _payload(chosen)
    if want_json:
        if payload is None:
            print(
                f"sase instructions show: seq {seq:02d} has no readable manifest",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif want_sections:
        from sase.main.instructions_handler import render_sections_table

        sections = []
        if isinstance(payload, dict):
            raw_sections = payload.get("sections")
            if isinstance(raw_sections, list):
                sections = raw_sections
        render_sections_table(_SectionView(sections))
    else:
        if integrity.data is None:
            print(
                f"sase instructions show: seq {seq:02d} bundle bytes are missing",
                file=sys.stderr,
            )
            return 2
        sys.stdout.buffer.write(integrity.data)
        if not integrity.data.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
    if integrity.label == "MISMATCH":
        return 1
    if integrity.label == "missing":
        return 2
    return 0


class _SectionView:
    """Adapter so archived sections reuse the render ``-s`` table."""

    def __init__(self, sections: list[Any]) -> None:
        self.sections = sections


__all__ = [
    "check_bundle_integrity",
    "format_list_row",
    "list_row_dict",
    "run_instructions_show",
]
