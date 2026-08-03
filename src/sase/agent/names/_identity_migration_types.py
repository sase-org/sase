"""Internal records shared by historical identity migration modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class JsonPayload:
    path: Path
    data: dict[str, Any]
    preimage: bytes


@dataclass(frozen=True, slots=True)
class AffectedArtifact:
    path: Path
    primary: JsonPayload
    payloads: tuple[JsonPayload, ...]
    timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AffectedBundle:
    payload: JsonPayload
    timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RewriteContext:
    bead_map: Mapping[str, str]
    local_name_map: Mapping[str, str]
    global_name_map: Mapping[str, str]
    chat_path_map: Mapping[str, str]

    @property
    def all_text_replacements(self) -> dict[str, str]:
        return {
            **dict(self.bead_map),
            **dict(self.local_name_map),
            **dict(self.global_name_map),
        }
