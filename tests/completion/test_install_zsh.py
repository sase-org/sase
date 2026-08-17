"""Real-zsh install tests. Skipped when zsh is not on PATH."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from sase.completion.install import install_completion, zwc_path


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

    result = install_completion(
        requested="zsh",
        target=zfunc,
        home=tmp_path,
        parent=None,
        environ=env,
        emit_fn=lambda _shell: ("#compdef sase\n_sase() { : }\n", "digest"),
    )

    script = zfunc / "_sase"
    assert result.ok, result.steps
    assert script.is_file()
    assert zwc_path(script).is_file()
    assert result.registered is True
    assert result.exit_code == 0
