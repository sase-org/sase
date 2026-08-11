"""Immutable per-occurrence artifact-reference use records.

One row is appended for every ref occurrence successfully expanded during a
launch, builtins included, in the prompt's original occurrence order --
deliberately not deduped, unlike ``artifact_consumption.jsonl``'s
per-rendered-ref dedupe (see ``core/artifact_consumption.py``, whose dedupe
stays untouched). Modelled on ``core/prompt_artifact_staging.py``'s
``locked_file`` + fsync + Rust render/parse house pattern.

This is the resolution-time manifest; the publication step that later reads
it into ``agents/<agent>/ref-uses.json`` belongs to a future phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import logging
import os
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from sase.artifact_ref_operations import (
    artifact_ref_use_manifest_parse,
    artifact_ref_use_record_render,
    artifact_ref_use_wire_schema_version,
)
from sase.memory.locks import locked_file


log = logging.getLogger(__name__)

ARTIFACT_REF_USE_MANIFEST_NAME = "ref-uses.jsonl"
ARTIFACT_REF_USE_MANIFEST_LOCK_NAME = "ref-uses.lock"


@dataclass(frozen=True, slots=True)
class ArtifactRefUseRecord:
    """One immutable record of an artifact reference being used in a prompt."""

    schema_version: int
    recorded_at: str
    agent_name: str
    raw_ref: str
    canonical_ref: str
    ref_kind: str
    prompt_text: str
    stable_id: str | None = None
    publication_target: str | None = None
    captured_file: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefUseRecord:
        return cls(
            schema_version=int(raw["schema_version"]),
            recorded_at=str(raw["recorded_at"]),
            agent_name=str(raw["agent_name"]),
            raw_ref=str(raw["raw_ref"]),
            canonical_ref=str(raw["canonical_ref"]),
            ref_kind=str(raw["ref_kind"]),
            prompt_text=str(raw["prompt_text"]),
            stable_id=_optional_str(raw.get("stable_id")),
            publication_target=_optional_str(raw.get("publication_target")),
            captured_file=_optional_str(raw.get("captured_file")),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "recorded_at": self.recorded_at,
            "agent_name": self.agent_name,
            "raw_ref": self.raw_ref,
            "canonical_ref": self.canonical_ref,
            "ref_kind": self.ref_kind,
            "stable_id": self.stable_id,
            "prompt_text": self.prompt_text,
            "publication_target": self.publication_target,
            "captured_file": self.captured_file,
        }


def record_artifact_ref_use(
    *,
    agent_name: str,
    raw_ref: str,
    canonical_ref: str,
    ref_kind: str,
    prompt_text: str,
    stable_id: str | None = None,
    agent_artifacts_dir: Path | str | None = None,
) -> ArtifactRefUseRecord | None:
    """Append one immutable use row, never raising and never blocking launch.

    Returns ``None`` (and logs at debug) when there is no agent artifacts
    directory to write into -- a bare CLI invocation, for instance -- or when
    the write itself fails for any reason.
    """

    try:
        artifacts_dir = _resolve_agent_artifacts_dir(agent_artifacts_dir)
        if artifacts_dir is None:
            log.debug("No agent artifacts dir; skipping ref-use record for %s", raw_ref)
            return None

        record = ArtifactRefUseRecord(
            schema_version=artifact_ref_use_wire_schema_version(),
            recorded_at=datetime.now(tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            agent_name=agent_name,
            raw_ref=raw_ref,
            canonical_ref=canonical_ref,
            ref_kind=ref_kind,
            prompt_text=prompt_text,
            stable_id=stable_id,
        )
        manifest_path = artifacts_dir / ARTIFACT_REF_USE_MANIFEST_NAME
        lock_path = artifacts_dir / ARTIFACT_REF_USE_MANIFEST_LOCK_NAME
        line = artifact_ref_use_record_render(record.to_wire())
        with locked_file(lock_path, fcntl.LOCK_EX):
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        return record
    except Exception as exc:  # noqa: BLE001 - a use record must never fail launch.
        log.debug("Could not record artifact-reference use for %s: %s", raw_ref, exc)
        return None


def read_artifact_ref_uses(path: Path | str) -> list[ArtifactRefUseRecord]:
    """Read every valid row from a ``ref-uses.jsonl`` manifest."""

    data = Path(path).read_bytes()
    return [
        ArtifactRefUseRecord.from_wire(raw)
        for raw in artifact_ref_use_manifest_parse(data)
    ]


def _resolve_agent_artifacts_dir(value: Path | str | None) -> Path | None:
    raw = value if value is not None else os.environ.get("SASE_ARTIFACTS_DIR")
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "ARTIFACT_REF_USE_MANIFEST_NAME",
    "ArtifactRefUseRecord",
    "read_artifact_ref_uses",
    "record_artifact_ref_use",
]
