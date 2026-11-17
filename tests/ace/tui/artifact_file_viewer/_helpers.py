from __future__ import annotations

import re
from pathlib import Path

from sase.ace.tui.graphics.viewer import ArtifactFileImageArea, kitten_icat_command


_TEST_IMAGE_AREA = ArtifactFileImageArea(columns=90, rows=24)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def _test_icat_command(page: Path) -> list[str]:
    return kitten_icat_command(page, _TEST_IMAGE_AREA)


def _tmux_which(tool: str) -> str | None:
    return f"/usr/bin/{tool}" if tool == "tmux" else None


def _patch_tmux_which(monkeypatch, which=_tmux_which) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_tmux_common.shutil.which",
        which,
    )


def _patch_tmux_run(monkeypatch, fake_run) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_tmux_common.subprocess.run",
        fake_run,
    )


def _tmux_split_env(cmd: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    index = 0
    while index < len(cmd) - 1:
        if cmd[index] == "-e":
            key, _, value = cmd[index + 1].partition("=")
            env[key] = value
            index += 2
            continue
        index += 1
    return env
