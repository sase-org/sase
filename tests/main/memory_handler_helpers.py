"""Shared helpers for ``sase memory`` handler tests."""

from __future__ import annotations

from pathlib import Path

from sase.memory.read_log import MemoryReadEvent


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def memory_read_event(
    *,
    read_id: str,
    canonical_path: str,
    agent_name: str,
    timestamp: str,
    reason: str,
    project: str = "demo",
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=1,
        id=read_id,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/demo",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/demo/memory/{canonical_path}",
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason=reason,
        byte_count=123,
        frontmatter_stripped=True,
    )
