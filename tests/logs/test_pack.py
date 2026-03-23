"""Integration tests for sase.logs.pack."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.logs.pack import build_pack
from sase.core.time import get_timezone


class TestBuildPack:
    def test_creates_pack_with_manifest(self, tmp_path: Path) -> None:
        sase_dir = tmp_path / "sase_home"
        sase_dir.mkdir()
        pack_base = tmp_path / "pack_output"

        # Create some test data
        chats_dir = sase_dir / "chats"
        chats_dir.mkdir()
        (chats_dir / "branch-ace_run-260315_120000.md").write_text("chat content")

        hooks_dir = sase_dir / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "feat-260315_100000.txt").write_text("hook output")

        start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2026, 3, 16, 23, 59, 59, tzinfo=get_timezone())

        original_expanduser = Path.expanduser

        def _fake_expanduser(self: Path) -> Path:
            s = str(self)
            if s.startswith("~/.sase/logs/pack"):
                return pack_base / s[len("~/.sase/logs/pack/") :]
            if s.startswith("~/.sase/"):
                return sase_dir / s[len("~/.sase/") :]
            return original_expanduser(self)

        with patch.object(Path, "expanduser", _fake_expanduser):
            pack_dir = build_pack(start, end, "-2d..0d")

        pack_path = Path(pack_dir)
        assert pack_path.exists()

        # Check manifest
        manifest = json.loads((pack_path / "manifest.json").read_text())
        assert manifest["range_spec"] == "-2d..0d"
        assert manifest["file_count"] >= 2

        # Check collected files
        assert (pack_path / "chats" / "branch-ace_run-260315_120000.md").exists()
        assert (pack_path / "hooks" / "feat-260315_100000.txt").exists()

    def test_empty_pack(self, tmp_path: Path) -> None:
        sase_dir = tmp_path / "sase_home"
        sase_dir.mkdir()
        pack_base = tmp_path / "pack_output"

        start = datetime(2020, 1, 1, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2020, 1, 2, 23, 59, 59, tzinfo=get_timezone())

        original_expanduser = Path.expanduser

        def _fake_expanduser(self: Path) -> Path:
            s = str(self)
            if s.startswith("~/.sase/logs/pack"):
                return pack_base / s[len("~/.sase/logs/pack/") :]
            if s.startswith("~/.sase/"):
                return sase_dir / s[len("~/.sase/") :]
            return original_expanduser(self)

        with patch.object(Path, "expanduser", _fake_expanduser):
            pack_dir = build_pack(start, end, "200101..200102")

        manifest = json.loads((Path(pack_dir) / "manifest.json").read_text())
        assert manifest["file_count"] == 0
