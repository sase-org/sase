"""Shared builders for the fork-history test modules."""

from __future__ import annotations

import json
from pathlib import Path


def write_member_artifacts(
    root: Path,
    timestamp: str,
    *,
    model: str,
    provider: str,
) -> Path:
    artifact_dir = root / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"model": model, "llm_provider": provider}),
        encoding="utf-8",
    )
    (artifact_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    return artifact_dir


def write_chat(path: Path, prompt: str, response: str = "") -> None:
    path.write_text(
        f"## Prompt\n\n{prompt}\n\n## Response\n\n{response}\n",
        encoding="utf-8",
    )


def proc_source(name: str, **proc_overrides: object) -> dict[str, object]:
    proc: dict[str, object] = {
        "proc_id": "proc0123456789ab",
        "is_monitor": False,
        "terminal": True,
        "failed": False,
        "shell_name": "build-docs",
        "command": "just docs",
        "cwd": "/tmp/work",
        "project": "sase",
        "started_at": "2026-08-24T15:00:00Z",
        "finished_at": "2026-08-24T15:00:05Z",
        "status": "success",
        "exit_code": 0,
        "timeout_seconds": None,
        "elapsed_seconds": None,
        "log_path": "/tmp/logs/proc0123456789ab.log",
        "log_tail": "building docs\ndone",
        "log_truncated": False,
        **proc_overrides,
    }
    return {"kind": "proc", "name": name, "proc": proc}
