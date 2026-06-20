#!/usr/bin/env python3
"""Manually capture a benign Antigravity trajectory fixture.

This script is intentionally not used by CI. Run it only in a disposable
workspace with a prompt that performs harmless actions, then inspect the copied
database before committing any fixture derived from it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--prompt",
        default="Run `echo agy fixture` and then finish.",
    )
    parser.add_argument("--agy", default="agy")
    args = parser.parse_args()

    conversations_dir = Path.home() / ".gemini" / "antigravity-cli" / "conversations"
    cache_path = conversations_dir.parent / "cache" / "last_conversations.json"
    before = _db_mtimes(conversations_dir)

    subprocess.run(
        [
            args.agy,
            "--print",
            args.prompt,
            "--dangerously-skip-permissions",
        ],
        check=True,
    )

    touched = [
        path
        for path, mtime_ns in _db_mtimes(conversations_dir).items()
        if before.get(path) != mtime_ns
    ]
    if not touched:
        raise SystemExit("no touched Antigravity conversation DB found")

    conversation_id = _last_conversation_id(cache_path, Path.cwd())
    if conversation_id:
        touched = [path for path in touched if path.stem == conversation_id]
    if len(touched) != 1:
        raise SystemExit(f"expected one touched DB, got: {touched!r}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(touched[0], args.output)
    print(args.output)
    return 0


def _db_mtimes(conversations_dir: Path) -> dict[Path, int]:
    if not conversations_dir.is_dir():
        return {}
    return {
        path: path.stat().st_mtime_ns
        for path in conversations_dir.glob("*.db")
        if path.is_file()
    }


def _last_conversation_id(cache_path: Path, cwd: Path) -> str | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get(str(cwd.resolve())) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


if __name__ == "__main__":
    raise SystemExit(main())
