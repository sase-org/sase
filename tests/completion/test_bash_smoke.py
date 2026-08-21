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

from sase.completion.build import build_spec
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


def _run_prompt_spec() -> CompletionSpec:
    run = _command(
        name="run",
        path=("run",),
        summary="Launch an agent",
        options=(_option(),),
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


def test_bash_syntax_accepts_the_full_live_script(tmp_path: Path) -> None:
    script = tmp_path / "sase.bash"
    script.write_text(emit_bash(build_spec()), encoding="utf-8")
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


def test_run_prompt_offers_files_and_xprompts(tmp_path: Path) -> None:
    """`sase run`'s PROMPT positional completes filenames in cwd plus stored
    xprompt names -- the combination the `#`/`%`/`@`-in-prompt polish item
    leaves out of scope, but files-or-xprompt is in scope for this phase."""
    script = tmp_path / "sase.bash"
    script.write_text(emit_bash(_run_prompt_spec()), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fixture = bin_dir / "sase"
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == completion && "$2" == candidates ]]; then\n'
        "  printf 'zzz-fixture-xprompt\\tA fixture xprompt\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "zzz-fixture-notes.md").write_text("notes", encoding="utf-8")

    snippet = f"""
set +e
cd {shlex.quote(str(workdir))}
export PATH={shlex.quote(str(bin_dir))}:$PATH
source {shlex.quote(str(script))}
COMP_WORDS=(sase run "zzz-fixture-")
COMP_CWORD=2
COMP_LINE="sase run zzz-fixture-"
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
    replies = [line for line in result.stdout.splitlines() if line]
    assert "zzz-fixture-xprompt" in replies, replies
    assert "zzz-fixture-notes.md" in replies, replies


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("ask #zz", "ask #zzz-fixture-xprompt"),
        ("ask %mo", "ask %model"),
        ("ask @file:e", "ask @file:explicit:abc123"),
    ],
)
def test_run_prompt_completes_embedded_markers_in_spaced_prompt(
    tmp_path: Path,
    typed: str,
    expected: str,
) -> None:
    script = tmp_path / "sase.bash"
    script.write_text(emit_bash(_run_prompt_spec()), encoding="utf-8")
    bin_dir = _write_marker_fixture_sase(tmp_path)

    quoted_words = " ".join(shlex.quote(word) for word in ("sase", "run", typed))
    comp_line = f'sase run "{typed}'
    snippet = f"""
set +e
export PATH={shlex.quote(str(bin_dir))}:$PATH
source {shlex.quote(str(script))}
COMP_WORDS=({quoted_words})
COMP_CWORD=2
COMP_LINE={shlex.quote(comp_line)}
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
    replies = [line for line in result.stdout.splitlines() if line]
    assert expected in replies, replies


def test_run_prompt_embedded_marker_uses_bash_cache(tmp_path: Path) -> None:
    script = tmp_path / "sase.bash"
    script.write_text(emit_bash(_run_prompt_spec()), encoding="utf-8")
    bin_dir = _write_marker_fixture_sase(tmp_path)
    call_count = tmp_path / "call_count"
    call_count.write_text("0", encoding="utf-8")

    comp_line = 'sase run "ask %mo'
    snippet = f"""
set +e
export PATH={shlex.quote(str(bin_dir))}:$PATH
export SASE_MARKER_CALL_COUNT={shlex.quote(str(call_count))}
source {shlex.quote(str(script))}
COMP_WORDS=(sase run "ask %mo")
COMP_CWORD=2
COMP_LINE={shlex.quote(comp_line)}
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
    assert "ask %model" in result.stdout
    assert call_count.read_text().strip() == "1"


def _write_marker_fixture_sase(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "marker-bin"
    bin_dir.mkdir()
    fixture = bin_dir / "sase"
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ -n "${SASE_MARKER_CALL_COUNT:-}" ]]; then\n'
        "  count=0\n"
        '  [[ -f "${SASE_MARKER_CALL_COUNT}" ]] && count=$(cat "${SASE_MARKER_CALL_COUNT}")\n'
        '  echo $((count + 1)) > "${SASE_MARKER_CALL_COUNT}"\n'
        "fi\n"
        'if [[ "$1" == completion && "$2" == candidates ]]; then\n'
        '  case "$3" in\n'
        "    xprompt) printf 'zzz-fixture-xprompt\\tA fixture xprompt\\n' ;;\n"
        "    directive) printf 'model\\tOverride the LLM model\\n' ;;\n"
        "    artifact_ref) printf 'file:explicit:abc123\\tScreenshot\\n' ;;\n"
        "  esac\n"
        "fi\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)
    return bin_dir
