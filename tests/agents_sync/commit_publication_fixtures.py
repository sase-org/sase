from __future__ import annotations

import json
from pathlib import Path
import subprocess

from sase.agents_sync.models import ProjectTarget


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
