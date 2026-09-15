"""Real-zsh smoke tests for the generated compsys script.

Skipped when ``zsh`` is not on PATH. The registration probe is the
durable check; the TAB probe drives a pty through ``sase bead +<TAB>``.
"""

from __future__ import annotations

import os
import pty
import select
import shlex
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import NamedTuple

import pytest

from sase.completion.build import build_spec
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


class _CompletionCapture(NamedTuple):
    buffer: str
    screen: str
    options: dict[str, str]


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


def _run_prompt_spec() -> CompletionSpec:
    run = _command(
        name="run",
        path=("run",),
        summary="Launch an agent",
        positionals=(
            PositionalSpec(
                metavar="PROMPT",
                dest="prompt",
                summary="Prompt text",
                nargs="?",
                choices=None,
                kind=None,
                is_remainder=False,
            ),
        ),
    )
    root = _command(
        name="sase",
        path=(),
        summary="",
        options=(_option(),),
        subcommands=(run,),
    )
    return CompletionSpec(prog="sase", version="0.0-test", root=root)


def _write_script(directory: Path) -> Path:
    path = directory / "_sase"
    path.write_text(emit_zsh(_plus_one_spec()), encoding="utf-8")
    return path


def _write_run_prompt_script(directory: Path) -> Path:
    path = directory / "_sase"
    path.write_text(emit_zsh(_run_prompt_spec()), encoding="utf-8")
    return path


def _write_live_script(directory: Path) -> Path:
    path = directory / "_sase"
    path.write_text(emit_zsh(build_spec()), encoding="utf-8")
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


def test_zsh_syntax_accepts_the_full_live_script(tmp_path: Path) -> None:
    """Every quoted description in the real tree parses as valid zsh.

    Complements ``test_live_script_descriptions_fit_column`` (length) with a
    real-shell parse: any unescaped ``'``, ``[``, ``]``, or ``:`` in a help
    string would break ``_arguments`` here, not just read oddly.
    """
    script = tmp_path / "_sase"
    script.write_text(emit_zsh(build_spec()), encoding="utf-8")
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
    captured = _pty_capture_completion(tmp_path, fpath_dir, "sase bead +")
    assert captured.buffer == "sase bead +1 "


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("sase bead sh", "sase bead show "),
        ("sase -p bead sh", "sase -p bead show "),
        ("sase --print-command bead sh", "sase --print-command bead show "),
    ],
)
def test_tab_completes_after_root_print_command_option(
    tmp_path: Path, typed: str, expected: str
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)

    captured = _pty_capture_completion(tmp_path, fpath_dir, typed)

    assert captured.buffer == expected
    assert "\u276f" not in captured.screen


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("sbd sh", "sbd show "),
        ("sbd show --for", "sbd show --format "),
    ],
)
def test_alias_sbd_completes_static_bead_tree(
    tmp_path: Path, typed: str, expected: str
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        typed,
        zshrc_extra="alias sbd='sase -p bead'\n",
    )

    assert captured.buffer == expected
    assert "\u276f" not in captured.screen


def test_alias_sbd_completes_dynamic_bead_id_without_running_bead(
    tmp_path: Path,
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)
    bin_dir, calls = _write_logged_fixture_sase(
        tmp_path,
        "zzz-fixture-alpha\tAlpha desc",
        "zzz-fixture-beta\tBeta desc",
    )

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        "sbd +1 ",
        bin_dir=bin_dir,
        zshrc_extra="alias sbd='sase -p bead'\n",
        taps=2,
    )

    assert captured.buffer == "sbd +1 zzz-fixture-"
    assert "Alpha desc" in captured.screen
    assert "Beta desc" in captured.screen
    assert "\u276f" not in captured.screen
    call_lines = calls.read_text(encoding="utf-8").splitlines()
    assert call_lines == ["<completion><candidates><bead>"]


@pytest.mark.parametrize(
    ("use_cache", "expected_call_count"),
    [
        (True, "1"),
        (False, "2"),
    ],
)
def test_dynamic_slot_fetches_fixture_candidates_with_cache_contract(
    tmp_path: Path, use_cache: bool, expected_call_count: str
) -> None:
    """A kinded positional obeys compsys's cache contract.

    Drives ``sase bead +1 <TAB><TAB>`` against a fixture ``sase`` on PATH
    that records every invocation. The plus-one spec's ``id`` positional
    already carries ``ValueKind.BEAD`` (see ``_plus_one_spec``), so no
    separate spec is needed. Two candidates share a common, non-empty
    prefix so the first TAB inserts only that prefix (leaving the cursor on
    the same word) and the second TAB re-triggers completion at the same
    position -- the scenario where a stale in-shell cache would otherwise
    cause a second fork of ``sase``. With caching disabled, the same buffer
    assertion still holds while both TAB presses call the fast path.
    """
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_script(fpath_dir)
    bin_dir, call_count = _write_fixture_sase(
        tmp_path,
        "zzz-fixture-alpha\tAlpha desc",
        "zzz-fixture-beta\tBeta desc",
    )

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        "sase bead +1 ",
        bin_dir=bin_dir,
        taps=2,
        use_cache=use_cache,
    )
    assert captured.buffer == "sase bead +1 zzz-fixture-"
    assert call_count.read_text().strip() == expected_call_count


@pytest.mark.parametrize(
    ("typed", "expected", "alias"),
    [
        ("sbd show zzz", "sbd show zzz-completion-fixture ", True),
        ("sbd +1 zzz", "sbd +1 zzz-completion-fixture ", True),
        ("sase bead show zzz", "sase bead show zzz-completion-fixture ", False),
        (
            "sase -p bead show zzz",
            "sase -p bead show zzz-completion-fixture ",
            False,
        ),
    ],
)
def test_dynamic_bead_id_typed_prefix_completes_direct_and_aliased_commands(
    tmp_path: Path, typed: str, expected: str, alias: bool
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)
    bin_dir, calls = _write_logged_fixture_sase(
        tmp_path,
        "zzz-completion-fixture\tFixture bead",
        "other-bead\tOther bead",
    )

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        typed,
        bin_dir=bin_dir,
        zshrc_extra="alias sbd='sase -p bead'\n" if alias else "",
    )

    assert captured.buffer == expected
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "<completion><candidates><bead>"
    ]


def test_dynamic_bead_id_nonmatching_prefix_leaves_buffer_unchanged(
    tmp_path: Path,
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)
    bin_dir, calls = _write_logged_fixture_sase(
        tmp_path,
        "zzz-completion-fixture\tFixture bead",
    )

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        "sbd show nope",
        bin_dir=bin_dir,
        zshrc_extra="alias sbd='sase -p bead'\n",
    )

    assert captured.buffer == "sbd show nope"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "<completion><candidates><bead>"
    ]


def test_dynamic_completion_does_not_leak_extendedglob_to_shell(
    tmp_path: Path,
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_live_script(fpath_dir)
    bin_dir, _calls = _write_logged_fixture_sase(
        tmp_path,
        "zzz-completion-fixture\tFixture bead",
    )

    captured = _pty_capture_completion(
        tmp_path,
        fpath_dir,
        "sase bead show zzz",
        bin_dir=bin_dir,
    )

    assert captured.buffer == "sase bead show zzz-completion-fixture "
    assert captured.options["extendedglob"] == "off"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ('sase run "ask #zz', '"ask #zzz-fixture-xprompt"'),
        ('sase run "ask %mo', '"ask %model"'),
        ('sase run "ask @file:e', '"ask @file:explicit:abc123"'),
    ],
)
def test_run_prompt_completes_embedded_markers_in_spaced_prompt(
    tmp_path: Path,
    typed: str,
    expected: str,
) -> None:
    fpath_dir = tmp_path / "fpath"
    fpath_dir.mkdir()
    _write_run_prompt_script(fpath_dir)
    bin_dir, _call_count = _write_fixture_sase(
        tmp_path,
        "zzz-fixture-xprompt\tA fixture xprompt",
        "model\tOverride the LLM model",
        "file:explicit:abc123\tScreenshot",
    )

    captured = _pty_capture_completion(tmp_path, fpath_dir, typed, bin_dir=bin_dir)

    assert expected in captured.buffer


def _write_fixture_sase(tmp_path: Path, *candidate_lines: str) -> tuple[Path, Path]:
    """Write a fake ``sase`` that records its call count and answers
    ``completion candidates`` with fixed lines, for a bin dir put ahead of
    the real ``sase`` on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_count = tmp_path / "call_count"
    call_count.write_text("0", encoding="utf-8")
    prints = "\n".join(
        f"printf {shlex.quote(line + chr(10))}" for line in candidate_lines
    )
    script = bin_dir / "sase"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "count=0\n"
        f"[[ -f {shlex.quote(str(call_count))} ]] && "
        f"count=$(cat {shlex.quote(str(call_count))})\n"
        f"echo $((count + 1)) > {shlex.quote(str(call_count))}\n"
        'if [[ "$1" == completion && "$2" == candidates ]]; then\n'
        '  case "$3" in\n'
        f"    xprompt) printf 'zzz-fixture-xprompt\\tA fixture xprompt\\n' ;;\n"
        f"    directive) printf 'model\\tOverride the LLM model\\n' ;;\n"
        f"    artifact_ref) printf 'file:explicit:abc123\\tScreenshot\\n' ;;\n"
        f"    *) {prints} ;;\n"
        "  esac\n"
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir, call_count


def _write_logged_fixture_sase(
    tmp_path: Path, *candidate_lines: str
) -> tuple[Path, Path]:
    """Write a fake ``sase`` that logs each argv vector and returns candidates."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    prints = "\n".join(
        f"printf {shlex.quote(line + chr(10))}" for line in candidate_lines
    )
    script = bin_dir / "sase"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"log={shlex.quote(str(calls))}\n"
        'printf "<%s>" "$@" >> "$log"\n'
        'printf "\\n" >> "$log"\n'
        'if [[ "$1" == completion && "$2" == candidates ]]; then\n'
        f"  {prints}\n"
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir, calls


def _pty_capture_completion(
    tmp_path: Path,
    fpath_dir: Path,
    typed: str,
    *,
    bin_dir: Path | None = None,
    zshrc_extra: str = "",
    taps: int = 1,
    use_cache: bool = True,
) -> _CompletionCapture:
    """Press TAB in interactive zsh, then capture ZLE's BUFFER without Enter."""
    nonce = time.monotonic_ns()
    zdot = tmp_path / f"zdot-capture-{nonce}"
    zdot.mkdir()
    capture_path = tmp_path / f"zle-buffer-{nonce}"
    marker = f"__SASE_CAPTURE_{nonce}__"
    cache_value = "on" if use_cache else "off"
    (zdot / ".zshrc").write_text(
        "unsetopt zle_bracketed_paste beep extendedglob\n"
        "PS1='READY>'\n"
        "PS2=\n"
        "RPS1=\n"
        f"fpath=({shlex.quote(str(fpath_dir))} $fpath)\n"
        "autoload -Uz compinit\n"
        "compinit -u -D\n"
        "zstyle ':completion:*' insert-tab false\n"
        "zstyle ':completion:*' menu false\n"
        "zstyle ':completion:*' list-colors ''\n"
        f"zstyle ':completion:*' use-cache {cache_value}\n"
        f"{zshrc_extra}"
        "__sase_capture_buffer() {\n"
        f'  print -r -- "$BUFFER" >| {shlex.quote(str(capture_path))}\n'
        "  print -r -- "
        f'"extendedglob=${{options[extendedglob]}}" '
        f">> {shlex.quote(str(capture_path))}\n"
        "  zle -I\n"
        f"  print -r -- {shlex.quote(marker)}\n"
        "}\n"
        "zle -N __sase_capture_buffer\n"
        "bindkey '^X^B' __sase_capture_buffer\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "ZDOTDIR": str(zdot),
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("zsh", ["zsh", "-i"], env)
    screen = b""
    try:
        _read_until(fd, b"READY>", timeout=8.0)
        os.write(fd, typed.encode() + b"\t" * taps + b"\x18\x02")
        screen = _read_until(fd, marker.encode(), timeout=5.0)
        screen += _read_for(fd, 0.2)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if capture_path.exists():
                payload = capture_path.read_text(encoding="utf-8").splitlines()
                buffer = payload[0] if payload else ""
                options: dict[str, str] = {}
                for line in payload[1:]:
                    key, _, value = line.partition("=")
                    options[key] = value
                return _CompletionCapture(
                    buffer,
                    screen.decode("utf-8", errors="replace"),
                    options,
                )
            time.sleep(0.05)  # sase-test-wait: poll for ZLE capture file output
        raise TimeoutError(
            f"completion capture file was not written; screen={screen!r}"
        )
    finally:
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        os.close(fd)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


def _read_for(fd: int, seconds: float) -> bytes:
    buf = b""
    deadline = time.monotonic() + seconds
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
    return buf


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
