"""Tests for runtime completion grammar caching."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.completion.install_models import ExpectedCompletion
from sase.completion.install_scripts import zwc_path
from sase.completion.runtime_cache import ensure_cached_grammar


def _expected_factory(calls: list[tuple[str, ...]], *, text: str = "# generated\n"):
    def _expected(shells: Sequence[str]):
        calls.append(tuple(shells))
        return {
            shell: ExpectedCompletion(f"{text}# {shell}\n", f"digest-{shell}")
            for shell in shells
        }

    return _expected


def _manifest(path: Path) -> dict[str, object]:
    return json.loads(path.with_name("manifest.json").read_text(encoding="utf-8"))


def test_ensure_generates_then_reuses_bash_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    again = ensure_cached_grammar(
        "bash",
        expected_fn=lambda _shells: pytest.fail("warm cache built parser"),
    )

    assert again == grammar
    assert calls == [("bash",)]
    assert grammar.is_absolute()
    assert grammar.read_text(encoding="utf-8") == "# generated\n# bash\n"
    manifest = _manifest(grammar)
    assert manifest["shell"] == "bash"
    assert manifest["structural_digest"] == "digest-bash"
    assert manifest["content_checksum"]


def test_ensure_records_loader_metadata_from_target_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    grammar = ensure_cached_grammar(
        "fish",
        owner="chezmoi",
        target=tmp_path / "fish-completions",
        expected_fn=_expected_factory(calls),
    )

    loader = _manifest(grammar)["loader"]
    assert isinstance(loader, dict)
    assert loader["owner"] == "chezmoi"
    assert loader["target"] == str(tmp_path / "fish-completions" / "sase.fish")


def test_corrupt_cache_file_regenerates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []
    grammar = ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    grammar.write_text("# corrupt\n", encoding="utf-8")

    ensure_cached_grammar(
        "bash",
        expected_fn=_expected_factory(calls, text="# regenerated\n"),
    )

    assert calls == [("bash",), ("bash",)]
    assert grammar.read_text(encoding="utf-8") == "# regenerated\n# bash\n"


def test_source_fingerprint_change_regenerates_same_version_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []
    ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))
    monkeypatch.setattr(
        "sase.completion.runtime_cache._source_fingerprint",
        lambda: "changed-source-fingerprint",
    )

    ensure_cached_grammar("bash", expected_fn=_expected_factory(calls))

    assert calls == [("bash",), ("bash",)]


def test_zsh_cache_requires_fresh_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, ...]] = []

    def _zcompile(path: Path) -> None:
        zwc_path(path).write_text("bytecode\n", encoding="utf-8")

    grammar = ensure_cached_grammar(
        "zsh",
        expected_fn=_expected_factory(calls),
        zcompile_fn=_zcompile,
    )
    zwc_path(grammar).unlink()
    ensure_cached_grammar(
        "zsh",
        expected_fn=_expected_factory(calls, text="# regenerated\n"),
        zcompile_fn=_zcompile,
    )

    assert calls == [("zsh",), ("zsh",)]
    assert zwc_path(grammar).is_file()
    assert grammar.read_text(encoding="utf-8") == "# regenerated\n# zsh\n"
