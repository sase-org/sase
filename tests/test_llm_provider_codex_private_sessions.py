"""Private Codex shadow-home sessions tree, rescue, and orphan sweep."""

from __future__ import annotations

import errno
import json
import os
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sase.instructions import run_index as run_mod
from sase.llm_provider import _codex_home as homemod
from sase.llm_provider._codex_home import (
    ORPHAN_SHADOW_HOME_MAX_AGE_SECONDS,
    _local_session_dates,
    _session_day_path,
    codex_subprocess_env,
)


def _day_link(shadow_home: Path, day: date) -> Path:
    return _session_day_path(shadow_home / "sessions", day)


def _real_day(real_home: Path, day: date) -> Path:
    return _session_day_path(real_home / "sessions", day)


def _age_path(
    path: Path, *, seconds: float = ORPHAN_SHADOW_HOME_MAX_AGE_SECONDS + 30
) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _orphan_home(cache_root: Path, pid: int) -> Path:
    home = cache_root / f"{pid}-{uuid.uuid4().hex}"
    home.mkdir(parents=True)
    return home


def _assert_private_day_links(
    shadow_home: Path, real_home: Path, days: tuple[date, date]
) -> None:
    sessions = shadow_home / "sessions"
    assert sessions.is_dir()
    assert not sessions.is_symlink()
    for day in days:
        link = _day_link(shadow_home, day)
        target = _real_day(real_home, day)
        assert link.is_symlink(), day
        assert link.resolve() == target.resolve()
        assert target.is_dir()
        assert not target.is_symlink()


def test_private_sessions_tree_links_today_and_tomorrow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shadow sessions tree is real; only local today/tomorrow days are links."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    (real_home / "sessions").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))

    with codex_subprocess_env() as env:
        shadow_home = Path(env["CODEX_HOME"])
        _assert_private_day_links(shadow_home, real_home, _local_session_dates())


@pytest.mark.parametrize(
    "today, tomorrow",
    [
        (date(2026, 1, 31), date(2026, 2, 1)),
        (date(2026, 12, 31), date(2027, 1, 1)),
    ],
)
def test_private_sessions_day_links_cross_month_and_year(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    today: date,
    tomorrow: date,
) -> None:
    """Day links are created across month and year boundaries."""
    real_home = tmp_path / ".codex"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setattr(homemod, "_local_session_dates", lambda: (today, tomorrow))

    with codex_subprocess_env() as env:
        shadow_home = Path(env["CODEX_HOME"])
        _assert_private_day_links(shadow_home, real_home, (today, tomorrow))
        assert (
            _day_link(shadow_home, today).parent
            != _day_link(shadow_home, tomorrow).parent
        )


def test_rescue_moves_straggler_rollout_into_real_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A regular file left in the private tree is moved into the real sessions root."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    stray_rel = Path("2026") / "01" / "01" / "rollout-stray.jsonl"
    payload = "stray-rollout\n"

    with codex_subprocess_env() as env:
        shadow_home = Path(env["CODEX_HOME"])
        stray = shadow_home / "sessions" / stray_rel
        stray.parent.mkdir(parents=True)
        stray.write_text(payload, encoding="utf-8")

    dest = real_home / "sessions" / stray_rel
    assert dest.read_text(encoding="utf-8") == payload
    assert not shadow_home.exists()


def test_rescue_collision_keeps_shadow_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A destination collision leaves the shadow home in place."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    dest = real_home / "sessions" / "stray.jsonl"
    dest.parent.mkdir(parents=True)
    dest.write_text("already-there\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))

    with caplog.at_level("WARNING", logger=homemod.__name__):
        with codex_subprocess_env() as env:
            shadow_home = Path(env["CODEX_HOME"])
            stray = shadow_home / "sessions" / "stray.jsonl"
            stray.write_text("shadow-copy\n", encoding="utf-8")

    assert shadow_home.is_dir()
    assert stray.read_text(encoding="utf-8") == "shadow-copy\n"
    assert dest.read_text(encoding="utf-8") == "already-there\n"
    assert any("collision" in record.getMessage() for record in caplog.records)


def test_rescue_cross_device_copy_fsync_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXDEV falls back to copy, fsync, then unlink without clobbering."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))

    def _exdev(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "link", _exdev)
    stray_rel = Path("orphan.jsonl")
    payload = "copied-across-devices\n"

    with codex_subprocess_env() as env:
        shadow_home = Path(env["CODEX_HOME"])
        (shadow_home / "sessions" / stray_rel).write_text(payload, encoding="utf-8")

    dest = real_home / "sessions" / stray_rel
    assert dest.read_text(encoding="utf-8") == payload
    assert not shadow_home.exists()


def test_orphan_sweep_rescues_dead_old_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead, aged shadow home is swept and its stray rollout is rescued."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    cache_root = tmp_path / ".cache" / "sase" / "codex_home"
    cache_root.mkdir(parents=True)
    orphan = _orphan_home(cache_root, 2**30)
    stray = orphan / "sessions" / "2026" / "03" / "04" / "rollout-orphan.jsonl"
    stray.parent.mkdir(parents=True)
    stray.write_text("rescued\n", encoding="utf-8")
    _age_path(orphan)

    with codex_subprocess_env():
        pass

    dest = real_home / "sessions" / "2026" / "03" / "04" / "rollout-orphan.jsonl"
    assert dest.read_text(encoding="utf-8") == "rescued\n"
    assert not orphan.exists()


def test_orphan_sweep_removes_legacy_symlinked_home_without_touching_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy session and sqlite symlinks are unlinked; their targets stay intact."""
    real_home = tmp_path / ".codex"
    real_sessions = real_home / "sessions" / "2026" / "10" / "01"
    real_sessions.mkdir(parents=True)
    real_rollout = real_sessions / "rollout-real.jsonl"
    real_rollout.write_text("keep-me\n", encoding="utf-8")
    real_state = real_home / "state_5.sqlite"
    real_state.write_text("sqlite\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    cache_root = tmp_path / ".cache" / "sase" / "codex_home"
    cache_root.mkdir(parents=True)
    orphan = _orphan_home(cache_root, 2**30)
    (orphan / "sessions").symlink_to(real_home / "sessions", target_is_directory=True)
    (orphan / "state_5.sqlite").symlink_to(real_state)
    _age_path(orphan)

    with codex_subprocess_env():
        pass

    assert not orphan.exists()
    assert real_rollout.read_text(encoding="utf-8") == "keep-me\n"
    assert real_state.read_text(encoding="utf-8") == "sqlite\n"


def test_orphan_sweep_leaves_live_young_and_foreign_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live-pid, young, and non-managed directories are left untouched."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    cache_root = tmp_path / ".cache" / "sase" / "codex_home"
    cache_root.mkdir(parents=True)

    live = _orphan_home(cache_root, os.getpid())
    (live / "keep-live").write_text("live\n", encoding="utf-8")
    _age_path(live)

    young = _orphan_home(cache_root, 2**30)
    (young / "keep-young").write_text("young\n", encoding="utf-8")

    foreign_target = tmp_path / "foreign-codex"
    foreign_target.mkdir()
    marker = foreign_target / "do-not-delete"
    marker.write_text("foreign\n", encoding="utf-8")
    foreign_link = cache_root / f"{2**30}-{uuid.uuid4().hex}"
    foreign_link.symlink_to(foreign_target, target_is_directory=True)
    _age_path(foreign_link)

    with codex_subprocess_env():
        pass

    assert (live / "keep-live").read_text(encoding="utf-8") == "live\n"
    assert (young / "keep-young").read_text(encoding="utf-8") == "young\n"
    assert foreign_link.is_symlink()
    assert marker.read_text(encoding="utf-8") == "foreign\n"


def test_find_codex_sessions_discovers_rollout_written_through_day_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rollout written through a day link is visible in the real sessions store."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setattr(
        homemod,
        "_local_session_dates",
        lambda: (date(2026, 10, 26), date(2026, 10, 27)),
    )
    workspace = "/work/synthetic"
    started = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    meta = {
        "type": "session_meta",
        "payload": {
            "session_id": "01private-day-link",
            "timestamp": "2026-10-26T15:01:00Z",
            "cwd": workspace,
        },
    }

    with codex_subprocess_env() as env:
        shadow_home = Path(env["CODEX_HOME"])
        today, _tomorrow = homemod._local_session_dates()
        rollout = _day_link(shadow_home, today) / "rollout-2026-10-26T15-01-00.jsonl"
        rollout.write_text(json.dumps(meta) + "\n", encoding="utf-8")
        real_file = _real_day(real_home, today) / rollout.name
        assert real_file.is_file()
        assert not real_file.is_symlink()
        run = run_mod.ScoredRun(
            provider="codex",
            name="sase-1oj.5--1",
            workspace_dir=workspace,
            artifact_dir=workspace,
            started_at=started,
            ended_at=datetime(2026, 10, 26, 16, 0, tzinfo=UTC),
            project=None,
        )
        matches = run_mod.find_codex_sessions(run)

    assert matches == [real_file]
    assert real_file.exists()
