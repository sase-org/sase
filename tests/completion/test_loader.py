"""Tests for portable completion loader rendering."""

from __future__ import annotations

from pathlib import Path

from sase.completion.loader import emit_loader


def test_bash_loader_resolves_runtime_and_sources_cached_grammar() -> None:
    script = emit_loader("bash")

    assert "completion ensure bash" in script
    assert '--loader-path "${loader}"' in script
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


def test_zsh_loader_is_compdef_and_prefers_cached_bytecode() -> None:
    script = emit_loader("zsh", owner="local")

    assert script.startswith("#compdef sase\n")
    assert "completion ensure zsh" in script
    assert "--owner 'local'" in script
    assert 'source "$grammar.zwc"' in script
    assert 'source "$grammar"' in script
    assert '_sase() { _sase_root "$@"; }' in script
    assert str(Path.home()) not in script
