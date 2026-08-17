"""Tests for the hand-written zsh preamble helpers."""

from __future__ import annotations

import re

from sase.completion.emit_zsh_preamble import zsh_preamble


def test_preamble_defines_sase_run_and_skips_workspace_venvs() -> None:
    text = zsh_preamble()
    assert "__sase_run()" in text
    assert "whence -p -a sase" in text
    assert r"/sase_[0-9]+/\.venv/bin/sase" in text
    assert 'command "$cmd" "$@"' in text
    assert "command sase" in text
    # Single-underscore `_sase_run` would collide with the generated
    # completer for the real `sase run` command and be silently redefined.
    assert re.search(r"(?<!_)_sase_run\(", text) is None


def test_preamble_defines_sase_candidates_with_in_shell_cache() -> None:
    text = zsh_preamble()
    assert "__sase_candidates()" in text
    assert "__sase_cache_policy()" in text
    assert "SASE_COMPLETION_CACHE_TTL" in text
    assert "_retrieve_cache" in text
    assert "_store_cache" in text
    assert '_describe -t "sase-$kind" "$kind" entries' in text
    # The prefix is never passed to the fast path: the full kind is fetched
    # once and cached, and `_describe` filters locally.
    assert "__sase_run completion candidates $kind" in text
