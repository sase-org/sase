"""Parity + smoke tests for ``tools/migrate_sase_shard_dirs.py``."""

from __future__ import annotations

import argparse
import ast
import filecmp
import os
import subprocess
import sys
import unittest.mock
from pathlib import Path

from sase.main.migrate_handler import handle_migrate_command


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "tools" / "migrate_sase_shard_dirs.py"


def _patch_sase_home(sase_dir: Path):
    original = Path.expanduser

    def _fake(self: Path) -> Path:
        s = str(self)
        if s.startswith("~/.sase/"):
            return sase_dir / s[len("~/.sase/") :]
        if s == "~/.sase":
            return sase_dir
        return original(self)

    return unittest.mock.patch.object(Path, "expanduser", _fake)


def _in_process_args(**kw) -> argparse.Namespace:
    base = {
        "command": "migrate",
        "migrate_subcommand": "shard-dirs",
        "dry_run": False,
        "force": False,
        "only": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_tree(base: Path) -> None:
    """Build a synthetic ``~/.sase``-like tree with deterministic content+mtimes."""
    layout = {
        "chats": [
            ("cl-run-260101_120000.md", "jan-chat"),
            ("cl-run-260315_090000.md", "mar-chat"),
            ("cl-run-260215_233000.md", "feb-chat"),
        ],
        "workflows": [
            ("wf-260110_100000.md", "wf-jan"),
        ],
        "checks": [
            ("chk-260220_140000.md", "chk-feb"),
        ],
        "dismissed_bundles": [
            ("20260105120000__c1.json", "{}"),
        ],
        "plans": [
            ("plan-260301_080000.md", "mar-plan"),
        ],
        "hooks": [
            ("hk-260215_100000.txt", "hook-feb"),
        ],
        "diffs": [
            ("df-260120_130000.diff", "diff-jan"),
        ],
        "mentors": [
            ("mtr-260225_120000.md", "mentor-feb"),
        ],
    }
    for subdir, files in layout.items():
        d = base / subdir
        d.mkdir(parents=True, exist_ok=True)
        for name, content in files:
            p = d / name
            p.write_text(content)
            # Deterministic mtime so fallback (by mtime) is reproducible,
            # even though every filename above has an embedded timestamp.
            os.utime(p, (1700000000, 1700000000))

    # plan_approval: UUID-style directories (the only "dir" kind).
    pa = base / "plan_approval"
    pa.mkdir(parents=True, exist_ok=True)
    for uid in ("uuid-a", "uuid-b"):
        sub = pa / uid
        sub.mkdir()
        (sub / "plan_request.json").write_text("{}")
        os.utime(sub / "plan_request.json", (1700000000, 1700000000))
        os.utime(sub, (1700000000, 1700000000))


def _tree_snapshot(root: Path) -> dict[str, str | None]:
    """Return {relpath: content or None-for-dir} for every entry under ``root``."""
    out: dict[str, str | None] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            out[rel] = None
        else:
            out[rel] = p.read_text()
    return out


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


def test_script_is_python_39_compatible() -> None:
    """Script must parse under Python 3.9 — no newer syntax snuck in."""
    source = _SCRIPT.read_text()
    ast.parse(source, feature_version=(3, 9))


def test_parity_with_in_process_handler(tmp_path: Path) -> None:
    """Running the standalone script produces a byte-identical tree to the CLI."""
    in_process_home = tmp_path / "a"
    standalone_home = tmp_path / "b"
    _seed_tree(in_process_home)
    _seed_tree(standalone_home)

    with _patch_sase_home(in_process_home):
        handle_migrate_command(_in_process_args())

    result = _run_script("--sase-home", str(standalone_home))
    assert result.returncode == 0, result.stderr

    left = _tree_snapshot(in_process_home)
    right = _tree_snapshot(standalone_home)
    assert left == right, f"tree divergence:\nleft={left}\nright={right}"

    # Spot-check that every file pair is byte-identical too.
    for rel, content in left.items():
        if content is None:
            continue
        assert filecmp.cmp(
            in_process_home / rel, standalone_home / rel, shallow=False
        ), rel


# ---------------------------------------------------------------------------
# Smoke tests for the standalone script
# ---------------------------------------------------------------------------


def test_fresh_migrate_then_noop(tmp_path: Path) -> None:
    _seed_tree(tmp_path)

    first = _run_script("--sase-home", str(tmp_path))
    assert first.returncode == 0, first.stderr
    assert (tmp_path / "chats" / "202601" / "cl-run-260101_120000.md").is_file()
    assert (tmp_path / "chats" / ".sharded").is_file()
    assert (tmp_path / "hooks" / "202602" / "hk-260215_100000.txt").is_file()

    # Second run: sentinel short-circuits every subdir.
    second = _run_script("--sase-home", str(tmp_path))
    assert second.returncode == 0, second.stderr
    assert "already migrated" in second.stdout


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    before = _tree_snapshot(tmp_path)

    result = _run_script("--dry-run", "--sase-home", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "would move" in result.stdout
    assert "Would move" in result.stdout

    after = _tree_snapshot(tmp_path)
    assert before == after
    assert not (tmp_path / "chats" / ".sharded").exists()


def test_force_reruns_past_sentinel(tmp_path: Path) -> None:
    _seed_tree(tmp_path)

    first = _run_script("--sase-home", str(tmp_path))
    assert first.returncode == 0

    # Drop a new legacy file after the sentinel has been written.
    latecomer = tmp_path / "chats" / "cl-run-260410_110000.md"
    latecomer.write_text("apr-late")

    # Without --force, the second run is a no-op and leaves the latecomer.
    noop = _run_script("--sase-home", str(tmp_path))
    assert noop.returncode == 0
    assert latecomer.is_file()

    # With --force, the latecomer gets sharded.
    forced = _run_script("--force", "--sase-home", str(tmp_path))
    assert forced.returncode == 0
    assert not latecomer.exists()
    assert (tmp_path / "chats" / "202604" / "cl-run-260410_110000.md").is_file()


def test_only_filters_subdirs(tmp_path: Path) -> None:
    _seed_tree(tmp_path)

    result = _run_script("--only", "plans,hooks", "--sase-home", str(tmp_path))
    assert result.returncode == 0, result.stderr

    # Selected subdirs were migrated.
    assert (tmp_path / "plans" / ".sharded").is_file()
    assert (tmp_path / "hooks" / ".sharded").is_file()

    # Untouched subdirs keep their legacy files and have no sentinel.
    assert (tmp_path / "chats" / "cl-run-260101_120000.md").is_file()
    assert not (tmp_path / "chats" / ".sharded").exists()
    assert (tmp_path / "workflows" / "wf-260110_100000.md").is_file()
    assert not (tmp_path / "workflows" / ".sharded").exists()


def test_only_rejects_unknown_name(tmp_path: Path) -> None:
    _seed_tree(tmp_path)
    result = _run_script("--only", "bogus", "--sase-home", str(tmp_path))
    assert result.returncode == 2
    assert "Unknown" in result.stderr


def test_sase_home_override_does_not_touch_real_home(tmp_path: Path) -> None:
    """--sase-home must redirect every path; never reach into the real ~/.sase."""
    _seed_tree(tmp_path)

    # Sentinel file in the real $HOME/.sase path that we must NOT touch.
    real_home = Path.home() / ".sase"
    real_home_existed = real_home.exists()
    canary = real_home / ".migration-canary-do-not-touch"
    created_canary = False
    if real_home_existed and not canary.exists():
        # Only plant a canary if the real ~/.sase already exists; don't create
        # it just for the test.
        try:
            canary.write_text("canary")
            created_canary = True
        except OSError:
            created_canary = False

    try:
        result = _run_script("--sase-home", str(tmp_path))
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "chats" / ".sharded").is_file()
        if created_canary:
            assert canary.read_text() == "canary"
    finally:
        if created_canary:
            try:
                canary.unlink()
            except OSError:
                pass


def test_plan_approval_dir_kind(tmp_path: Path) -> None:
    """plan_approval is the ``dir`` kind — UUID subdirs move intact."""
    _seed_tree(tmp_path)
    pa = tmp_path / "plan_approval"

    result = _run_script("--only", "plan_approval", "--sase-home", str(tmp_path))
    assert result.returncode == 0, result.stderr

    shards = [p for p in pa.iterdir() if p.is_dir() and p.name.isdigit()]
    assert shards, "expected at least one YYYYMM shard"
    moved_uids = set()
    for shard in shards:
        for sub in shard.iterdir():
            moved_uids.add(sub.name)
            assert (sub / "plan_request.json").is_file()
    assert moved_uids == {"uuid-a", "uuid-b"}
    assert not (pa / "uuid-a").exists()
    assert not (pa / "uuid-b").exists()
