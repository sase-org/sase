"""Real-zsh install tests. Skipped when zsh is not on PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sase.completion.install import install_completion, zwc_path
from sase.completion.install_targets import ZSH_PROBE_TIMEOUT_SECONDS, probe_zsh_comps


zsh = shutil.which("zsh")
pytestmark = pytest.mark.skipif(zsh is None, reason="zsh is not on PATH")


def test_real_zsh_zcompile_and_registration(tmp_path: Path) -> None:
    zdot = tmp_path / "zdot"
    zfunc = tmp_path / "zfunc"
    zdot.mkdir()
    zfunc.mkdir()
    (zdot / ".zshrc").write_text(
        f"fpath=({zfunc} $fpath)\n"
        "autoload -Uz compinit\n"
        "compinit -u -d "
        f"{tmp_path / 'zcompdump'}\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "ZDOTDIR": str(zdot),
        "HOME": str(tmp_path),
    }

    assert ZSH_PROBE_TIMEOUT_SECONDS == 5.0

    def bounded_probe() -> str | None:
        return probe_zsh_comps(timeout=12.0, env=env)

    contender = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time\nend=time.monotonic()+2\nwhile time.monotonic()<end: pass\n",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        results = [
            install_completion(
                requested="zsh",
                target=zfunc,
                home=tmp_path,
                parent=None,
                environ=env,
                emit_fn=lambda _shell: ("#compdef sase\n_sase() { : }\n", "digest"),
                verify_fn=bounded_probe,
            )
            for _ in range(3)
        ]
    finally:
        contender.terminate()
        try:
            contender.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            contender.kill()
            contender.wait()

    result = results[-1]

    script = zfunc / "_sase"
    assert all(item.ok for item in results), [item.steps for item in results]
    assert script.is_file()
    assert zwc_path(script).is_file()
    assert result.registered is True
    assert result.exit_code == 0
