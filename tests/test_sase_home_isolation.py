from __future__ import annotations

import os
import pwd
from datetime import datetime
from pathlib import Path

from sase.core.paths import get_sase_directory, sase_home, sharded_path


def test_sase_home_honors_sase_home_env(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "custom-sase-home"

    monkeypatch.setenv("SASE_HOME", str(configured))

    assert sase_home() == configured


def test_sase_home_defaults_to_path_home_when_env_absent(
    monkeypatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "user-home"

    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    assert sase_home() == fake_home / ".sase"


def test_sase_directory_helpers_stay_under_sase_home(
    monkeypatch, tmp_path: Path
) -> None:
    configured = tmp_path / "isolated-sase"

    monkeypatch.setenv("SASE_HOME", str(configured))

    assert Path(get_sase_directory("hooks")) == configured / "hooks"
    path = Path(
        sharded_path(
            "chats",
            "agent-260527_123456.md",
            ts=datetime(2026, 5, 27, 12, 34, 56),
        )
    )
    assert path == configured / "chats" / "202605" / "agent-260527_123456.md"
    assert path.parent.is_dir()


def test_autouse_fixture_isolates_default_sase_home() -> None:
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)

    assert Path.home() / ".sase" != real_home / ".sase"
    assert sase_home() == Path.home() / ".sase"
