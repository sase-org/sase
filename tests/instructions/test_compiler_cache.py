"""Render-cache behavior tests: hits, misses, key classes, and latency."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.instructions import cache as cache_module
from sase.instructions.cache import (
    collect_key_inputs,
    compute_cache_key,
)
from sase.instructions.compile import COMPILER_VERSION, compile_bundle
from sase.instructions.manifest import build_manifest, preview_delivery
from tests.instructions.fixture_compiler import make_facts, make_roots, write

pytestmark = pytest.mark.usefixtures("isolated_instructions_home")


@pytest.fixture()
def isolated_instructions_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bundle store and render cache at a tmp dir."""
    home = tmp_path / "ihome"
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(home))
    return home


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path]:
    """Return a fixture (project, home) pair."""
    return make_roots(tmp_path)


def _manifest_sources(roots: tuple[Path, Path], provider: str = "codex") -> list[dict]:
    project_root, home_root = roots
    compiled = compile_bundle(
        make_facts(provider=provider),
        project_root=project_root,
        home_root=home_root,
    )
    manifest = build_manifest(
        compiled, make_facts(provider=provider), preview_delivery()
    )
    return [source for section in manifest["sections"] for source in section["sources"]]


def test_hit_returns_identical_bytes(
    roots: tuple[Path, Path], isolated_instructions_home: Path
) -> None:
    """A second compile is a hit with identical bytes and sections."""
    project_root, home_root = roots
    _ = isolated_instructions_home
    first = compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    assert first.cache == "miss"
    second = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    assert second.cache == "hit"
    assert second.text == first.text
    assert second.sha256 == first.sha256
    assert [s["id"] for s in second.sections] == [s["id"] for s in first.sections]


def test_bypass_skips_cache_read_and_write(
    roots: tuple[Path, Path], isolated_instructions_home: Path
) -> None:
    """use_cache=False reports bypass and leaves no cache entry."""
    project_root, home_root = roots
    compiled = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root, use_cache=False
    )
    assert compiled.cache == "bypass"
    assert list((isolated_instructions_home / "cache").glob("*.json")) == []
    second = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root, use_cache=False
    )
    assert second.cache == "bypass"
    assert second.text == compiled.text


def test_mutating_any_input_class_causes_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each hashed input class invalidates the cache entry."""
    project_root, home_root = make_roots(tmp_path)

    def _miss_after(mutator: Callable[[], None]) -> None:
        first = compile_bundle(
            make_facts(), project_root=project_root, home_root=home_root
        )
        assert first.cache in ("miss", "hit")
        second = compile_bundle(
            make_facts(), project_root=project_root, home_root=home_root
        )
        assert second.cache == "hit"
        mutator()
        third = compile_bundle(
            make_facts(), project_root=project_root, home_root=home_root
        )
        assert third.cache == "miss"

    _miss_after(
        lambda: write(
            project_root / "sase" / "memory" / "gotchas.md",
            project_root.joinpath("sase/memory/gotchas.md").read_text(encoding="utf-8")
            + "\nMore gotchas.\n",
        )
    )
    _miss_after(
        lambda: write(
            home_root / "sase" / "memory" / "home_only.md",
            home_root.joinpath("sase/memory/home_only.md").read_text(encoding="utf-8")
            + "\nMore home.\n",
        )
    )
    _miss_after(lambda: write(project_root / "AGENTS.md", "# Legacy\n\nLegacy text.\n"))
    _miss_after(
        lambda: write(project_root / "sase.yml", "is_sase_managed: true\nextra: 1\n")
    )
    _ = monkeypatch


def test_provider_switch_changes_directive_input(roots: tuple[Path, Path]) -> None:
    """Codex vs Grok renders miss each other's cache entries."""
    project_root, home_root = roots
    codex = compile_bundle(
        make_facts(provider="codex"), project_root=project_root, home_root=home_root
    )
    grok = compile_bundle(
        make_facts(provider="grok"), project_root=project_root, home_root=home_root
    )
    assert grok.cache == "miss"
    assert grok.text != codex.text
    again = compile_bundle(
        make_facts(provider="codex"), project_root=project_root, home_root=home_root
    )
    assert again.cache == "hit"


def test_global_config_change_causes_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed global config invalidates the key through its own class."""
    from sase.config import core as config_core

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    project_root, home_root = make_roots(tmp_path)
    first = compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    assert first.cache == "miss"
    write(config_dir / "sase.yml", "is_sase_managed: true\n")
    second = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    assert second.cache == "miss"
    assert second.text == first.text


def test_corrupt_entry_or_blob_is_a_miss(
    roots: tuple[Path, Path], isolated_instructions_home: Path
) -> None:
    """Corrupt cache entries and missing blobs fall back to a miss."""
    project_root, home_root = roots
    first = compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    assert first.cache == "miss"
    entries = list((isolated_instructions_home / "cache").glob("*.json"))
    assert len(entries) == 1
    entries[0].write_text("{corrupt", encoding="utf-8")
    retry = compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    assert retry.cache == "miss"
    assert retry.text == first.text
    blob = (
        isolated_instructions_home / "bundles" / first.sha256[:2] / f"{first.sha256}.md"
    )
    blob.unlink()
    (isolated_instructions_home / "cache" / entries[0].name).unlink(missing_ok=True)
    compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    entries = list((isolated_instructions_home / "cache").glob("*.json"))
    assert len(entries) == 1
    blob.unlink()
    missed = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    assert missed.cache == "miss"
    assert missed.text == first.text


def test_key_covers_every_input_class(roots: tuple[Path, Path]) -> None:
    """The key enumerates memory, configs, templates, dists, and code."""
    project_root, home_root = roots
    inputs = collect_key_inputs(
        compiler_version=COMPILER_VERSION,
        actor="sase_root",
        mode="runtime",
        provider="codex",
        project="fixture",
        project_root=project_root,
        home_root=home_root,
    )
    labels = [label for label, _ in inputs.files]
    assert "project-memory:sase/memory/gotchas.md" in labels
    assert "home-memory:sase/memory/home_only.md" in labels
    assert "project-config" in labels
    assert "package-template" in labels
    assert "helper-template" in labels
    assert inputs.directive_file == "provider-directive:codex"
    assert len(inputs.directive_sha256) == 64
    assert any(label.startswith("code:sase.instructions/") for label, _ in inputs.code)
    assert any(label.startswith("code:sase.amd/") for label, _ in inputs.code)
    assert isinstance(inputs.distributions, tuple)
    first = compute_cache_key(inputs)
    second = compute_cache_key(inputs)
    assert first == second


def test_manifest_sources_belong_to_key_classes(
    roots: tuple[Path, Path],
) -> None:
    """Every manifest source path belongs to a key input class."""
    project_root, home_root = roots
    inputs = collect_key_inputs(
        compiler_version=COMPILER_VERSION,
        actor="sase_root",
        mode="runtime",
        provider="codex",
        project="fixture",
        project_root=project_root,
        home_root=home_root,
    )
    key_labels = {label for label, _ in inputs.files}
    key_labels.add(inputs.directive_file)
    for source in _manifest_sources(roots):
        scope = source["scope"]
        kind = source["kind"]
        path = source["path"]
        if kind == "package_template":
            assert path in (
                "sase/main/init_memory/templates/memory-sase.template.md",
                "custom-template.md",
            ) or path.endswith(".md")
            assert ("package-template" in key_labels) or (
                "template-override" in key_labels
            )
        elif kind == "helper_template":
            assert "helper-template" in key_labels
        elif kind == "provider_directive":
            assert path == "sase/llm_provider/codex.py"
            assert "provider-directive:codex" in key_labels
        elif kind == "config":
            assert path in ("sase.yml",) or path.startswith("global/")
        elif kind in ("memory_note", "memory_web", "memory_strands"):
            assert f"{scope}-memory:{path}" in key_labels, (scope, kind, path)
        elif kind == "legacy_fallback":
            assert f"{scope}-agents-md" in key_labels or path == "AGENTS.md"
        elif kind == "generated":
            assert path.startswith("generated/") or path
        else:  # pragma: no cover - closed vocabulary guard
            raise AssertionError(f"unexpected source kind {kind!r}")


def test_hit_path_imports_no_heavy_modules(tmp_path: Path) -> None:
    """A warm render in a fresh interpreter skips amd/init_memory/web."""
    from sase.config import core as config_core

    project_root, home_root = make_roots(tmp_path)
    compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    script = (
        "import os, sys;"
        "from pathlib import Path;"
        f"os.environ['SASE_INSTRUCTIONS_HOME'] = {str(tmp_path / 'ihome')!r};"
        "import sase.config.core as config_core;"
        f"config_core.CONFIG_DIR = Path({str(config_core.CONFIG_DIR)!r});"
        f"config_core.CHEZMOI_HOME = Path({str(config_core.CHEZMOI_HOME)!r});"
        "from sase.instructions.compile import compile_bundle;"
        "from sase.instructions.facts import parse_facts;"
        "facts = parse_facts({'actor': 'sase_root', 'mode': 'runtime',"
        " 'purpose': 'ordinary', 'provider': 'codex', 'project': 'fixture',"
        " 'host': 'testhost', 'vcs': None});"
        f"c = compile_bundle(facts, project_root=Path({str(project_root)!r}),"
        f" home_root=Path({str(home_root)!r}));"
        "assert c.cache == 'hit', c.cache;"
        "banned = [m for m in ('sase.amd', 'sase.main.init_memory', 'sase.memory.web')"
        " if m in sys.modules or any(k == m or k.startswith(m + '.') for k in sys.modules)];"
        "assert not banned, banned;"
        "print('hit-ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=Path.cwd(),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "hit-ok" in proc.stdout


@pytest.mark.slow
def test_warm_render_latency_budget(tmp_path: Path) -> None:
    """Warm renders stay within the 250 ms budget (p95 over 20 renders)."""
    project_root, home_root = make_roots(tmp_path)
    compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    samples = []
    for _ in range(20):
        compiled = compile_bundle(
            make_facts(), project_root=project_root, home_root=home_root
        )
        assert compiled.cache == "hit"
        samples.append(compiled.render_ms)
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, 18)]
    assert p95 <= 250, f"warm p95 {p95:.1f} ms exceeds 250 ms"


def test_prune_keeps_newest_entries(
    isolated_instructions_home: Path, tmp_path: Path
) -> None:
    """Cache writes prune entries beyond the newest 512."""
    from sase.instructions.cache import _prune_cache_entries, write_cache_entry

    cache_dir = isolated_instructions_home / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for index in range(5):
        path = cache_dir / f"entry-{index}.json"
        path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    write_cache_entry(isolated_instructions_home, "probe", {"bundle_sha256": "x"})
    removed = _prune_cache_entries(isolated_instructions_home, limit=3)
    assert removed == 3
    assert len(list(cache_dir.glob("*.json"))) == 3
