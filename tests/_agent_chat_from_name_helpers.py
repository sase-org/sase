"""Shared helpers for agent chat resolver tests."""

from __future__ import annotations

import json
from pathlib import Path


def write_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    done: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
    malformed_meta: bool = False,
) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    if malformed_meta:
        (artifacts_dir / "agent_meta.json").write_text("{", encoding="utf-8")
    else:
        meta_data: dict[str, object] = {"name": name}
        if meta:
            meta_data.update(meta)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(meta_data), encoding="utf-8"
        )
    if done is not None:
        (artifacts_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    for data, field in ((done, "response_path"), (meta, "chat_path")):
        value = data.get(field) if data else None
        if isinstance(value, str):
            transcript = Path(value).expanduser()
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(f"transcript for {name}", encoding="utf-8")
    return artifacts_dir
