"""Real-bash smoke tests for the generated complete -F script.

Skipped when ``bash`` is not on PATH. Sources the script under
``bash --norc --noprofile`` and calls ``_sase`` with a synthetic
``COMP_WORDS`` / ``COMP_CWORD``.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from sase.completion.emit_bash import emit_bash
from sase.completion.kinds import ValueKind
from sase.completion.model import (
    CommandSpec,
    CompletionSpec,
    OptionSpec,
    PositionalSpec,
)

bash = shutil.which("bash")
pytestmark = pytest.mark.skipif(bash is None, reason="bash is not on PATH")


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
    fmt = _option(
        strings=("-f", "--format"),
        dest="format",
        summary="Output format",
        takes_value=True,
        choices=("json", "text"),
    )
    bead = _command(
        name="bead",
        path=("bead",),
        summary="Inspect beads",
        options=(_option(), fmt),
        subcommands=(plus, listing),
    )
    patch = _command(
        name="patch",
        path=("patch",),
        aliases=("changespec",),  # legacy command alias
        summary="Inspect patches",
    )
    root = _command(
        name="sase",
        path=(),
        summary="",
        options=(_option(),),
        subcommands=(bead, patch),
    )
    return CompletionSpec(prog="sase", version="0.0-test", root=root)


def _write_script(directory: Path) -> Path:
    path = directory / "sase.bash"
    path.write_text(emit_bash(_plus_one_spec()), encoding="utf-8")
    return path


def _complete(script: Path, words: list[str], cword: int | None = None) -> list[str]:
    if cword is None:
        cword = len(words) - 1
    quoted = " ".join(shlex.quote(word) for word in words)
    snippet = f"""
set +e
source {shlex.quote(str(script))}
COMP_WORDS=({quoted})
COMP_CWORD={cword}
COMP_LINE={shlex.quote(" ".join(words))}
COMP_POINT=${{#COMP_LINE}}
_sase
printf '%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", snippet],  # type: ignore[list-item]
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def test_bash_syntax_accepts_generated_script(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    result = subprocess.run(
        [bash, "-n", "--", str(script)],  # type: ignore[list-item]
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_tab_completes_bead_plus_to_plus_one(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    replies = _complete(script, ["sase", "bead", "+"])
    assert "+1" in replies, replies


def test_root_offers_commands_but_not_alias(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    replies = _complete(script, ["sase", ""])
    assert "bead" in replies
    assert "patch" in replies
    assert "changespec" not in replies  # legacy command alias


def test_alias_walks_to_patch_node(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    replies = _complete(script, ["sase", "changespec", "-"])  # legacy command alias
    assert "--help" in replies or "-h" in replies


def test_format_choices_are_offered(tmp_path: Path) -> None:
    script = _write_script(tmp_path)
    replies = _complete(script, ["sase", "bead", "--format", ""])
    assert "json" in replies
    assert "text" in replies


def test_dynamic_slot_fetches_fixture_candidates_and_caches(tmp_path: Path) -> None:
    """A kinded positional calls the fast path once per shell, then serves
    the in-shell cache. Two ``_sase`` invocations for the same word inside
    a single bash process -- as repeated TAB presses would produce, since
    the cache lives in a ``declare -gA`` array scoped to the shell -- must
    fork the fixture ``sase`` only once.
    """
    script = _write_script(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_count = tmp_path / "call_count"
    call_count.write_text("0", encoding="utf-8")
    fixture = bin_dir / "sase"
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        "count=0\n"
        f"[[ -f {shlex.quote(str(call_count))} ]] && "
        f"count=$(cat {shlex.quote(str(call_count))})\n"
        f"echo $((count + 1)) > {shlex.quote(str(call_count))}\n"
        'if [[ "$1" == completion && "$2" == candidates ]]; then\n'
        "  printf 'zzz-fixture-bead\\tA fixture bead\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)

    snippet = f"""
set +e
export PATH={shlex.quote(str(bin_dir))}:$PATH
source {shlex.quote(str(script))}
COMP_WORDS=(sase bead +1 "")
COMP_CWORD=3
COMP_LINE="sase bead +1 "
COMP_POINT=${{#COMP_LINE}}
_sase
printf '%s\\n' "${{COMPREPLY[@]}}"
printf '===\\n'
_sase
printf '%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", snippet],  # type: ignore[list-item]
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    first, _, second = result.stdout.partition("===\n")
    assert "zzz-fixture-bead" in first, result.stdout
    assert "zzz-fixture-bead" in second, result.stdout
    assert call_count.read_text().strip() == "1"
