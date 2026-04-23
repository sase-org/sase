"""Smoke tests for ``sase migrate shard-dirs``."""

from __future__ import annotations

import argparse
import unittest.mock
from pathlib import Path

from sase.main.migrate_handler import handle_migrate_command


def _patch_sase_home(tmp_path: Path):
    sase_dir = tmp_path
    original = Path.expanduser

    def _fake(self: Path) -> Path:
        s = str(self)
        if s.startswith("~/.sase/"):
            return sase_dir / s[len("~/.sase/") :]
        if s == "~/.sase":
            return sase_dir
        return original(self)

    return unittest.mock.patch.object(Path, "expanduser", _fake)


def _args(**kw) -> argparse.Namespace:
    base = {
        "command": "migrate",
        "migrate_subcommand": "shard-dirs",
        "dry_run": False,
        "force": False,
        "only": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_migration_moves_files_into_shards(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir(parents=True)
    (chats / "cl-run-260101_120000.md").write_text("jan")
    (chats / "cl-run-260315_090000.md").write_text("mar")
    (chats / "no-timestamp.md").write_text("unknown")

    hooks = tmp_path / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "cl-260215_100000.txt").write_text("feb")

    with _patch_sase_home(tmp_path):
        handle_migrate_command(_args(only=["chats", "hooks"]))

    assert (chats / "202601" / "cl-run-260101_120000.md").is_file()
    assert (chats / "202603" / "cl-run-260315_090000.md").is_file()
    # no-timestamp.md falls back to mtime-based shard — just assert it was moved.
    assert not (chats / "no-timestamp.md").exists()
    assert (hooks / "202602" / "cl-260215_100000.txt").is_file()

    # Sentinel written.
    assert (chats / ".sharded").exists()
    assert (hooks / ".sharded").exists()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir(parents=True)
    (chats / "cl-run-260101_120000.md").write_text("jan")

    with _patch_sase_home(tmp_path):
        handle_migrate_command(_args(only=["chats"]))
        # A second run is a no-op — the sentinel short-circuits.
        handle_migrate_command(_args(only=["chats"]))

    # Still exactly in its shard, not re-moved or duplicated.
    shard_file = chats / "202601" / "cl-run-260101_120000.md"
    assert shard_file.is_file()
    assert shard_file.read_text() == "jan"


def test_dry_run_does_not_touch_disk(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir(parents=True)
    src = chats / "cl-run-260101_120000.md"
    src.write_text("jan")

    with _patch_sase_home(tmp_path):
        handle_migrate_command(_args(only=["chats"], dry_run=True))

    # File still at its legacy location.
    assert src.is_file()
    # No sentinel because dry-run.
    assert not (chats / ".sharded").exists()


def test_plan_approval_moves_uuid_dirs(tmp_path: Path) -> None:
    pa = tmp_path / "plan_approval"
    legacy = pa / "uuid-a"
    legacy.mkdir(parents=True)
    (legacy / "plan_request.json").write_text("{}")

    with _patch_sase_home(tmp_path):
        handle_migrate_command(_args(only=["plan_approval"]))

    # Directory was moved into a shard; the concrete shard depends on
    # the directory's mtime, but there must be exactly one shard with
    # the uuid-a subdirectory.
    shards = [p for p in pa.iterdir() if p.is_dir() and p.name.isdigit()]
    assert len(shards) == 1
    assert (shards[0] / "uuid-a" / "plan_request.json").is_file()
    assert not (pa / "uuid-a").exists()
