"""Key helpers for episode component planning."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.source_refs import normalize_source_path


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self.parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def record_key(record: AgentArtifactRecordWire) -> str:
    return record_key_from_path(record.artifact_dir)


def record_key_from_path(path: str | Path) -> str:
    return f"artifact:{normalize_source_path(path)}"


def chat_key(path: str | Path) -> str:
    return f"chat:{normalize_source_path(path)}"


def chat_timestamp(path: str) -> str | None:
    stem = Path(path).stem
    if "-" not in stem:
        return None
    suffix = stem.rsplit("-", 1)[-1]
    if len(suffix) == 13 and suffix[6] == "_":
        return compact_timestamp(suffix)
    return None


__all__ = [
    "UnionFind",
    "chat_key",
    "chat_timestamp",
    "record_key",
    "record_key_from_path",
]
