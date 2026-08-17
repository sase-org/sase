"""Tests for the hand-written zsh preamble helpers."""

from __future__ import annotations

from sase.completion.emit_zsh_preamble import zsh_preamble


def test_preamble_defines_sase_run_and_skips_workspace_venvs() -> None:
    text = zsh_preamble()
    assert "_sase_run()" in text
    assert "whence -p -a sase" in text
    assert r"/sase_[0-9]+/\.venv/bin/sase" in text
    assert 'command "$cmd" "$@"' in text
    assert "command sase" in text
    assert "_sase_candidates" not in text
