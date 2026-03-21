"""Tests for sase.logs.collectors."""

import json
from datetime import datetime
from pathlib import Path

from sase.logs.collectors import (
    _ts_from_artifacts_dir,
    _ts_from_filename_suffix,
    collect_chats,
    collect_diffs,
    collect_hooks,
)
from sase.sase_utils import get_timezone


class TestTimestampExtraction:
    def test_filename_suffix_md(self) -> None:
        ts = _ts_from_filename_suffix("branch-ace_run-260318_143052.md")
        assert ts is not None
        assert ts == datetime(2026, 3, 18, 14, 30, 52, tzinfo=get_timezone())

    def test_filename_suffix_txt(self) -> None:
        ts = _ts_from_filename_suffix("sase_banana-260314_195329.txt")
        assert ts is not None
        assert ts == datetime(2026, 3, 14, 19, 53, 29, tzinfo=get_timezone())

    def test_filename_suffix_no_match(self) -> None:
        ts = _ts_from_filename_suffix("README.md")
        assert ts is None

    def test_artifacts_dir_name(self) -> None:
        ts = _ts_from_artifacts_dir("20260313211940")
        assert ts is not None
        assert ts == datetime(2026, 3, 13, 21, 19, 40, tzinfo=get_timezone())

    def test_artifacts_dir_no_match(self) -> None:
        ts = _ts_from_artifacts_dir("not-a-timestamp")
        assert ts is None


class TestCollectByFilenameSuffix:
    def test_collect_chats_filters_by_range(self, tmp_path: Path) -> None:
        chats_dir = tmp_path / "chats"
        chats_dir.mkdir()
        # In range
        (chats_dir / "branch-ace_run-260315_120000.md").write_text("chat1")
        # Out of range (too early)
        (chats_dir / "branch-ace_run-260310_120000.md").write_text("chat2")
        # Out of range (too late)
        (chats_dir / "branch-ace_run-260320_120000.md").write_text("chat3")

        start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2026, 3, 16, 23, 59, 59, tzinfo=get_timezone())

        with _patch_expanduser(tmp_path):
            results = collect_chats(start, end)

        assert len(results) == 1
        assert results[0].name == "branch-ace_run-260315_120000.md"

    def test_collect_hooks(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "sase_feat-260315_100000.txt").write_text("output")

        start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2026, 3, 16, 23, 59, 59, tzinfo=get_timezone())

        with _patch_expanduser(tmp_path):
            results = collect_hooks(start, end)

        assert len(results) == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2026, 3, 16, 23, 59, 59, tzinfo=get_timezone())

        with _patch_expanduser(tmp_path):
            results = collect_chats(start, end)

        assert results == []


class TestCollectByMtime:
    def test_collect_diffs_by_mtime(self, tmp_path: Path) -> None:
        diffs_dir = tmp_path / "diffs"
        diffs_dir.mkdir()
        diff_file = diffs_dir / "branch-260315_100000.diff"
        diff_file.write_text("diff content")

        start = datetime(2020, 1, 1, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2030, 12, 31, 23, 59, 59, tzinfo=get_timezone())

        with _patch_expanduser(tmp_path):
            results = collect_diffs(start, end)

        assert len(results) == 1


class TestCollectJsonl:
    def test_collect_run_log(self, tmp_path: Path) -> None:
        from sase.logs.collectors import collect_run_log

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        runs_file = logs_dir / "runs.jsonl"
        lines = [
            json.dumps({"timestamp": "260315_120000", "event": "agent_run"}),
            json.dumps({"timestamp": "260310_120000", "event": "agent_run"}),
        ]
        runs_file.write_text("\n".join(lines) + "\n")

        start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=get_timezone())
        end = datetime(2026, 3, 16, 23, 59, 59, tzinfo=get_timezone())

        with _patch_expanduser(tmp_path):
            results = collect_run_log(start, end)

        assert len(results) == 1
        assert "260315" in results[0]


def _patch_expanduser(tmp_path: Path):
    """Patch Path.expanduser so ``~/.sase/`` resolves inside tmp_path."""
    import unittest.mock

    sase_dir = tmp_path

    original_expanduser = Path.expanduser

    def _fake_expanduser(self: Path) -> Path:
        s = str(self)
        if s.startswith("~/.sase/"):
            return sase_dir / s[len("~/.sase/") :]
        return original_expanduser(self)

    return unittest.mock.patch.object(Path, "expanduser", _fake_expanduser)
