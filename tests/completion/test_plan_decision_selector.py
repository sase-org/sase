"""Scoped ``plan_decision`` completion: helpers pass the named proposal as ``-S``.

Covers the shell pass-through (emitted helper text for zsh, bash, and fish,
plus executable proposal extraction for bash and zsh) and the Python scoping
rules (exact match wins over prefix ambiguity, merged fallback otherwise).
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from sase.completion.build import build_spec
from sase.completion.emit_bash import emit_bash
from sase.completion.emit_fish import emit_fish
from sase.completion.emit_zsh import emit_zsh
from sase.completion.emit_zsh_preamble import zsh_preamble

bash = shutil.which("bash")
zsh = shutil.which("zsh")


def test_zsh_helper_scopes_plan_decisions_to_named_proposal() -> None:
    text = zsh_preamble()
    assert "__sase_plan_proposal()" in text
    assert "__sase_plan_decision_candidates()" in text
    # The proposal named on the command line reaches the fast path as -S.
    assert 'completion candidates $kind -S "$selector"' in text
    # Scoped fetches are keyed by kind plus selector...
    assert 'key+="-${selector//[^A-Za-z0-9_]/_}"' in text
    # ...and the merged fetch stays on the bare kind key.
    assert (
        'reply=( ${(f)"$(__sase_run completion candidates $kind 2>/dev/null)"} )'
        in text
    )
    assert '__sase_candidates plan_decision "$selector"' in text


def test_zsh_emits_scoped_action_for_plan_decision_slots() -> None:
    text = emit_zsh(build_spec())
    assert "{__sase_plan_decision_candidates}" in text
    assert "{__sase_candidates plan_decision}" not in text


def test_bash_helper_scopes_plan_decisions_to_named_proposal() -> None:
    text = emit_bash(build_spec())
    assert "__sase_plan_proposal()" in text
    assert "__sase_plan_decision_candidates()" in text
    assert 'completion candidates "${kind}" -S "${selector}"' in text
    # Scoped fetches are keyed by kind plus selector, never the merged key.
    assert 'key+="::${selector}"' in text
    assert '"${__sase_candidates_cache[${key}]}"' in text


def test_bash_routes_plan_decision_slots_to_scoped_helper() -> None:
    text = emit_bash(build_spec())
    assert "kind:plan_decision)" in text
    assert '__sase_plan_decision_candidates "${value_cur}" "${prefix}"' in text


def test_fish_helper_scopes_plan_decisions_to_named_proposal() -> None:
    text = emit_fish(build_spec())
    assert "function __sase_plan_proposal" in text
    assert "function __sase_plan_decision_candidates" in text
    assert "completion candidates plan_decision -S" in text
    assert "-xa '(__sase_plan_decision_candidates)'" in text


@pytest.mark.skipif(bash is None, reason="bash is not on PATH")
def test_bash_passes_named_proposal_as_selector(tmp_path: Path) -> None:
    """Completing ``-D`` with a proposal on the line calls ``-S <proposal>``."""
    script = tmp_path / "sase.bash"
    script.write_text(emit_bash(build_spec()), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    fixture = bin_dir / "sase"
    fixture.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {shlex.quote(str(calls))}\n'
        "printf 'grouping=\\tHow should it group?\\n'\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)

    snippet = f"""
set +e
export PATH={shlex.quote(str(bin_dir))}:$PATH
source {shlex.quote(str(script))}
COMP_WORDS=(sase plan approve myplan -D "")
COMP_CWORD=5
COMP_LINE="sase plan approve myplan -D "
COMP_POINT=${{#COMP_LINE}}
_sase
printf '%s\\n' "${{COMPREPLY[@]}}"
printf '===\\n'
COMP_WORDS=(sase plan approve -D "")
COMP_CWORD=4
COMP_LINE="sase plan approve -D "
COMP_POINT=${{#COMP_LINE}}
_sase
printf '%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    first, _, second = result.stdout.partition("===\n")
    assert "grouping=" in first, result.stdout
    assert "grouping=" in second, result.stdout
    lines = [line for line in calls.read_text().splitlines() if line]
    assert len(lines) == 2, lines
    assert "-S myplan" in lines[0], lines
    assert "-S" not in lines[1], lines


@pytest.mark.skipif(zsh is None, reason="zsh is not on PATH")
def test_zsh_extracts_named_proposal_from_words(tmp_path: Path) -> None:
    """``__sase_plan_proposal`` finds PLAN and skips option values."""
    preamble = tmp_path / "preamble.zsh"
    preamble.write_text(zsh_preamble(), encoding="utf-8")
    snippet = f"""
setopt noerrexit
source {shlex.quote(str(preamble))}
probe() {{
  print -r -- "got:$1"
}}
words=(sase plan approve myplan -D ''); CURRENT=5
probe "$(__sase_plan_proposal)"
words=(sase plan approve -D grouping=mode myplan -D ''); CURRENT=7
probe "$(__sase_plan_proposal)"
words=(sase plan approve -m opus myplan -D ''); CURRENT=7
probe "$(__sase_plan_proposal)"
words=(sase plan approve -D ''); CURRENT=4
__sase_plan_proposal
print -r -- "rc:$?"
"""
    result = subprocess.run(
        [zsh, "--no-rcs", "-c", snippet],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    assert "got:myplan" in out, out
    assert out.count("got:myplan") == 3, out
    assert "rc:1" in out, out


def _rows() -> list[dict[str, object]]:
    return [
        {"id": "aaa-plan", "archive": "plans/myplan.md"},
        {"id": "bbb-plan", "archive": "plans/myplan2.md"},
    ]


@pytest.fixture
def _scoped_rows(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    import sase.completion.candidates.catalog_plans as catalog
    import sase.plan_names as plan_names

    rows = _rows()
    archives = {str(row["archive"]) for row in rows}
    assert len(archives) == 2
    by_id = {id(row): str(row["archive"]) for row in rows}
    monkeypatch.setattr(catalog, "_archive_path_for_row", lambda row: by_id[id(row)])
    monkeypatch.setattr(
        plan_names, "plan_display_names", lambda paths: {path: path for path in paths}
    )
    return rows


def test_exact_match_wins_over_prefix_ambiguity(
    _scoped_rows: list[dict[str, object]],
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    # "myplan" exactly matches the first row's stem while prefix-matching the
    # second row's stem; the exact hit scopes on its own.
    scoped = catalog._scope_rows_to_selector(_scoped_rows, "myplan")
    assert scoped is not None
    assert [row["id"] for row in scoped] == ["aaa-plan"]


def test_ambiguous_selector_keeps_merged_fallback(
    _scoped_rows: list[dict[str, object]],
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    assert catalog._scope_rows_to_selector(_scoped_rows, "plans") is None


def test_unmatched_selector_keeps_merged_fallback(
    _scoped_rows: list[dict[str, object]],
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    assert catalog._scope_rows_to_selector(_scoped_rows, "no-such-plan") is None


def test_unique_prefix_still_scopes(
    _scoped_rows: list[dict[str, object]],
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    scoped = catalog._scope_rows_to_selector(_scoped_rows, "myplan2")
    assert scoped is not None
    assert [row["id"] for row in scoped] == ["bbb-plan"]
