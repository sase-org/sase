"""Tests for portable completion loader rendering."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import os
from pathlib import Path

import pytest

from sase.completion.loader import emit_loader


def test_bash_loader_resolves_runtime_and_sources_cached_grammar() -> None:
    script = emit_loader("bash")

    assert "completion ensure bash" in script
    assert '--loader-path "${loader}"' in script
    assert '[[ -n "${grammar}" && -r "${grammar}" ]]' in script
    assert 'source "${grammar}"' in script
    assert "_sase" in script
    assert str(Path.home()) not in script
    assert "/sase_[0-9]*/.venv/bin/sase" in script


def test_fish_loader_can_embed_owner_metadata() -> None:
    script = emit_loader("fish", owner="chezmoi")

    assert "completion ensure fish" in script
    assert "--owner 'chezmoi'" in script
    assert 'source "$grammar"' in script
    assert "functions -e __sase_loader_run" in script
    assert str(Path.home()) not in script


def test_zsh_loader_is_compdef_and_sources_grammar_file() -> None:
    script = emit_loader("zsh", owner="local")

    assert script.startswith("#compdef sase\n")
    assert "completion ensure zsh" in script
    assert "--owner 'local'" in script
    assert 'source "$grammar"' in script
    assert 'source "$grammar.zwc"' not in script
    assert "local status=" not in script
    assert "local loader_rc=$?" in script
    assert '_sase() { _sase_root "$@"; }' in script
    assert str(Path.home()) not in script


def _write_ensure_sase(bin_dir: Path, grammar: Path, log: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "sase"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        'if [[ "$1" == completion && "$2" == ensure ]]; then\n'
        f"  printf '%s\\n' {shlex.quote(str(grammar))}\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _ensure_call_count(log: Path) -> int:
    if not log.exists():
        return 0
    return sum("completion ensure " in line for line in log.read_text().splitlines())


def test_bash_loader_sources_grammar_once_and_skips_later_ensure(
    tmp_path: Path,
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not on PATH")
    cache = tmp_path / "sase home" / "grammar"
    cache.mkdir(parents=True)
    grammar = cache / "sase.bash"
    grammar.write_text("_sase() { COMPREPLY=(from-grammar); }\n", encoding="utf-8")
    log = tmp_path / "ensure.log"
    bin_dir = tmp_path / "bin dir"
    _write_ensure_sase(bin_dir, grammar, log)
    loader_dir = tmp_path / "load ers"
    loader_dir.mkdir()
    loader = loader_dir / "sase"
    loader.write_text(emit_loader("bash"), encoding="utf-8")

    snippet = f"""
set +e
export PATH={shlex.quote(str(bin_dir))}:$PATH
source {shlex.quote(str(loader))}
COMP_WORDS=(sase "")
COMP_CWORD=1
_sase
printf 'FIRST:%s\\n' "${{COMPREPLY[@]}}"
_sase
printf 'SECOND:%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "FIRST:from-grammar" in result.stdout
    assert "SECOND:from-grammar" in result.stdout
    assert _ensure_call_count(log) == 1


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not on PATH")
def test_zsh_loader_sources_grammar_once_and_skips_later_ensure(
    tmp_path: Path,
) -> None:
    zsh = shutil.which("zsh")
    assert zsh is not None
    cache = tmp_path / "sase home" / "grammar"
    cache.mkdir(parents=True)
    grammar = cache / "_sase"
    grammar.write_text(
        '_sase_root() { print -r -- from-grammar; }\n_sase_root "$@"\n',
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [zsh, "-c", "zcompile -U -- $1", "sase-zcompile", str(grammar)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    assert grammar.with_name("_sase.zwc").is_file()
    log = tmp_path / "ensure.log"
    bin_dir = tmp_path / "bin dir"
    _write_ensure_sase(bin_dir, grammar, log)
    fpath_dir = tmp_path / "load ers"
    fpath_dir.mkdir()
    (fpath_dir / "_sase").write_text(emit_loader("zsh"), encoding="utf-8")

    snippet = (
        f"export PATH={shlex.quote(str(bin_dir))}:$PATH\n"
        f"fpath=({shlex.quote(str(fpath_dir))} $fpath)\n"
        "autoload -U _sase\n"
        "_sase\n"
        "_sase\n"
    )
    result = subprocess.run(
        [zsh, "-f", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "parse error" not in result.stderr
    assert "read-only variable" not in result.stderr
    assert result.stdout.splitlines() == ["from-grammar", "from-grammar"]
    assert _ensure_call_count(log) == 1


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish is not on PATH")
def test_fish_loader_sources_grammar_once_and_skips_later_ensure(
    tmp_path: Path,
) -> None:
    fish = shutil.which("fish")
    assert fish is not None
    cache = tmp_path / "sase home" / "grammar"
    cache.mkdir(parents=True)
    grammar = cache / "sase.fish"
    grammar.write_text("complete -c sase -a 'bead'\n", encoding="utf-8")
    log = tmp_path / "ensure.log"
    bin_dir = tmp_path / "bin dir"
    _write_ensure_sase(bin_dir, grammar, log)
    loader_dir = tmp_path / "load ers"
    loader_dir.mkdir()
    empty_completion_dir = tmp_path / "empty completions"
    empty_completion_dir.mkdir()
    loader = loader_dir / "sase.fish"
    loader.write_text(emit_loader("fish"), encoding="utf-8")

    snippet = (
        f"set -g fish_complete_path {shlex.quote(str(empty_completion_dir))}; "
        f"set -gx PATH {shlex.quote(str(bin_dir))} $PATH; "
        f"source {shlex.quote(str(loader))}; "
        "complete -C 'sase '; "
        "complete -C 'sase '"
    )
    result = subprocess.run(
        [fish, "-N", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "bead" in result.stdout
    assert _ensure_call_count(log) == 1
