from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_drain as publication_drain
from sase.agents_sync.models import ProjectTarget
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests._sched_clock import SchedulerAdjustedClock

# How long after a blocked stage starts the drain's alarm fires.
_BLOCKED_STAGE_ALARM_SECONDS = 0.2


class BlockedStageAlarm:
    """Expire the drain budget from inside a deliberately blocked stage.

    The drain arms its one-shot ``SIGALRM`` before the payload clean, pull,
    and inventory stages. On a loaded runner a short configured budget can
    run out in one of those stages instead of the blocked stage the test is
    about. The request then never records the attempt the test expects, and
    a fail-open ``OSError`` handler on the way can even swallow the
    ``TimeoutError``-derived drain timeout.

    So the drain runs under a hang-guard budget, and the blocked stage calls
    :meth:`expire` to re-arm the same timer to fire shortly. The drain's own
    handler then raises inside that stage, exactly as it would for a budget
    that ran out there. :meth:`seconds_since_block` leaves out time spent
    waiting for a CPU, but still counts the blocked stage's own sleep.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            publication_drain,
            "_configured_publication_drain_timeout",
            lambda: LOAD_TOLERANT_TIMEOUT,
        )
        self._clock: SchedulerAdjustedClock | None = None

    def expire(self) -> None:
        """Arm the drain alarm; call this first thing in the blocked stage."""
        assert callable(signal.getsignal(signal.SIGALRM)), (
            "the drain installed no SIGALRM handler to expire"
        )
        self._clock = SchedulerAdjustedClock()
        signal.setitimer(signal.ITIMER_REAL, _BLOCKED_STAGE_ALARM_SECONDS)

    def seconds_since_block(self) -> float:
        """Return how long the drain ran after the blocked stage started."""
        assert self._clock is not None, "the blocked stage never ran"
        return self._clock.elapsed()


def fulfilled_completion(*_args: object, **_kwargs: object) -> SimpleNamespace:
    """Fake a fulfilled completion decision for publication drains."""

    return SimpleNamespace(fulfilled=True, reason="", required_page="")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def setup_target(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init")
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "seed")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    primary = tmp_path / "primary"
    primary.mkdir()
    return (
        ProjectTarget(
            "proj",
            "Project",
            primary,
            (primary.resolve(),),
            sidecar,
            str(remote),
        ),
        remote,
    )
