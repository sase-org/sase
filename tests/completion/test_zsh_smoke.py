"""Real-zsh smoke tests for the generated compsys script.

Skipped when ``zsh`` is not on PATH. The registration probe is the
durable check; the TAB probe drives a pty through ``sase bead +<TAB>``.
"""

from __future__ import annotations

import os
import pty
import re
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from sase.completion.emit_zsh import emit_zsh
from sase.completion.kinds import ValueKind
from sase.completion.model import (
    CommandSpec,
    CompletionSpec,
    OptionSpec,
    PositionalSpec,
)

zsh = shutil.which("zsh")
pytestmark = pytest.mark.skipif(zsh is None, reason="zsh is not on PATH")


def _option(**overrides: object) -> OptionSpec:
    base: dict[str, object] = {
        "strings": ("-h", "--help"),
        "dest": "help",
        "summary": "show help",
        "takes_value": False,
        "repeatable": False,
        "choices": None,
        "kind": None,
        "hidden": False,
    }
    base.update(overrides)
    return OptionSpec(**base)  # type: ignore[arg-type]


def _command(**overrides: object) -> CommandSpec:
    base: dict[str, object] = {
        "name": "show",
        "path": ("bead", "show"),
        "aliases": (),
        "hidden": False,
        "summary": "Show issue details",
        "options": (_option(),),
        "positionals": (),
        "subcommands": (),
        "default_child": None,
        "mutex_groups": (),
    }
    base.update(overrides)
    return CommandSpec(**base)  # type: ignore[arg-type]


def _plus_one_spec() -> CompletionSpec:
    plus = _command(
        name="+1",
        path=("bead", "+1"),
        summary="Add a plus-one",
        positionals=(
            PositionalSpec(
                metavar="id",
                dest="id",
                summary="Bead id",
                nargs=None,
                choices=None,
                kind=ValueKind.BEAD,
                is_remainder=False,
            ),
        ),
    )
    listing = _command(name="list", path=("bead", "list"), summary="List beads")
    bead = _command(
        name="bead",
        path=("bead",),
        summary="Inspect beads",
        options=(_option(),),
        subcommands=(plus, listing),
    )
    root = _command(
        name="sase",
        path=(),
        summary="",
        options=(_option(),),
        subcommands=(bead,),
    )
    return CompletionSpec(prog="sase", version="0.0-test", root=root)


def _write_script(directory: Path) -> Path:
    path = directory / "_sase"
    path.write_text(emit_zsh(_plus_one_spec()), encoding="utf-8")
    return path


def test_zsh_syntax_accepts_generated_script(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    result = subprocess.run(
        [zsh, "-n", "--", str(script)],  # type: ignore[list-item]
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_compinit_registers_sase(tmp_path: Path) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_script(fpath_dir)
    dump = tmp_path / "zcompdump"
    result = subprocess.run(
        [
            zsh,  # type: ignore[list-item]
            "-f",
            "-c",
            "fpath=($1 $fpath); autoload -U compinit; "
            "compinit -u -d $2; print -r -- ${_comps[sase]:-UNSET}",
            "probe",
            str(fpath_dir),
            str(dump),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "_sase"


def test_tab_completes_bead_plus_to_plus_one(tmp_path: Path) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_script(fpath_dir)
    completed = _pty_complete(tmp_path, fpath_dir, "sase bead +")
    assert re.search(r"sase bead \+1\b", completed), completed


def _pty_complete(tmp_path: Path, fpath_dir: Path, typed: str) -> str:
    """Drive an interactive zsh through TAB and return the visible line.

    Setup lives in ``ZDOTDIR/.zshrc`` so the first prompt is already a
    fully initialized compsys, and TAB is not interleaved with setup.
    """
    zdot = tmp_path / "zdot"
    zdot.mkdir()
    (zdot / ".zshrc").write_text(
        "unsetopt zle_bracketed_paste beep\n"
        "PS1='READY>'\n"
        "PS2=\n"
        "RPS1=\n"
        f"fpath=({fpath_dir} $fpath)\n"
        "autoload -Uz compinit\n"
        "compinit -u -D\n"
        "zstyle ':completion:*' insert-tab false\n"
        "zstyle ':completion:*' menu false\n"
        "zstyle ':completion:*' list-colors ''\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "ZDOTDIR": str(zdot),
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("zsh", ["zsh", "-i"], env)
    try:
        _read_until(fd, b"READY>", timeout=8.0)
        os.write(fd, typed.encode() + b"\t")
        completed = _read_until(fd, b"sase bead +1", timeout=5.0)
        os.write(fd, b"\n")
        rest = _read_until(fd, b"READY>", timeout=5.0)
        return (completed + rest).decode("utf-8", errors="replace")
    finally:
        os.close(fd)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


def _read_until(fd: int, needle: bytes, timeout: float = 5.0) -> bytes:
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([fd], [], [], max(0.0, remaining))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        if needle in buf:
            return buf
    raise TimeoutError(f"timed out waiting for {needle!r}; got {buf!r}")
