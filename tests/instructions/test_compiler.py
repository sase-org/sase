"""Compiler composition, overlays, facts, and manifest tests (E2 compiler)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sase.core.instruction_manifest import _InstructionManifestError
from sase.instructions.compile import (
    COMPILER_NAME,
    COMPILER_VERSION,
    CompiledBundle,
    InstructionCompileError,
    compile_bundle,
)
from sase.instructions.sections import section_slug, tokens_estimate
from sase.instructions.directives import provider_directive
from sase.instructions.facts import InstructionFactsError, parse_facts
from sase.instructions.manifest import build_manifest, preview_delivery
from tests.instructions.fixture_compiler import make_facts, make_roots, write

pytestmark = pytest.mark.usefixtures("isolated_instructions_home")


@pytest.fixture()
def isolated_instructions_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bundle store and render cache at a tmp dir."""
    home = tmp_path / "ihome"
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(home))
    return home


def _by_id(compiled: CompiledBundle, section_id: str) -> dict:
    for section in compiled.sections:
        if section["id"] == section_id:
            return section
    raise AssertionError(f"missing section {section_id!r}")


def test_root_render_carries_final_declaration_once(tmp_path: Path) -> None:
    """Only the root render contains the final declaration heading."""
    project_root, home_root = make_roots(tmp_path)
    compiled = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    assert compiled.text.count("SASE Final Declaration") == 1
    assert "# SASE Helper Instructions" not in compiled.text
    assert _by_id(compiled, "pkg.root.final_declaration")["status"] == "included"
    helper_excluded = _by_id(compiled, "pkg.helper.contract")
    assert helper_excluded["status"] == "excluded"
    assert helper_excluded["reason"] == "overlay"


def test_helper_interactive_export_overlays(tmp_path: Path) -> None:
    """Helper/interactive/export renders meet decision 7."""
    project_root, home_root = make_roots(tmp_path)
    helper = compile_bundle(
        make_facts(actor="native_helper"),
        project_root=project_root,
        home_root=home_root,
    )
    assert "# SASE Helper Instructions" in helper.text
    assert "SASE Final Declaration" not in helper.text
    assert _by_id(helper, "pkg.helper.contract")["status"] == "included"
    assert _by_id(helper, "pkg.provider.codex")["reason"] == "overlay"

    interactive = compile_bundle(
        make_facts(actor="interactive", mode="interactive", project="fixture"),
        project_root=project_root,
        home_root=home_root,
    )
    assert "SASE Final Declaration" not in interactive.text
    assert "# SASE Helper Instructions" not in interactive.text

    export = compile_bundle(
        make_facts(actor="interactive", mode="export", project="fixture"),
        project_root=project_root,
        home_root=home_root,
    )
    assert "SASE Final Declaration" not in export.text
    assert "# SASE Helper Instructions" not in export.text
    assert all(
        not section["id"].startswith("home.")
        for section in export.sections
        if section["status"] == "included"
    )


def test_project_note_shadows_home_note(tmp_path: Path) -> None:
    """A same-path home note is excluded as shadowed with its counterpart."""
    project_root, home_root = make_roots(tmp_path)
    compiled = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    shadowed = _by_id(compiled, "home.core.gotchas")
    assert shadowed["status"] == "excluded"
    assert shadowed["reason"] == "shadowed"
    assert shadowed["shadowed_by"] == "proj.core.gotchas"
    assert _by_id(compiled, "proj.core.gotchas")["status"] == "included"
    assert _by_id(compiled, "proj.core.sase")["reason"] == "superseded_input"
    assert _by_id(compiled, "home.core.sase")["reason"] == "superseded_input"
    assert _by_id(compiled, "home.core.home_only")["status"] == "included"


def test_missing_home_root_is_absence_not_error(tmp_path: Path) -> None:
    """A missing home memory dir compiles with no home sections."""
    project_root, _home_root = make_roots(tmp_path)
    compiled = compile_bundle(
        make_facts(),
        project_root=project_root,
        home_root=tmp_path / "no-such-home",
    )
    assert not any(line.startswith("Home:") for line in compiled.text.splitlines())
    assert not [
        section["id"]
        for section in compiled.sections
        if section["id"].startswith("home.")
    ]


def test_no_directive_provider_records_reason(tmp_path: Path) -> None:
    """Providers without a directive exclude their section as no_directive."""
    project_root, home_root = make_roots(tmp_path)
    compiled = compile_bundle(
        make_facts(provider="qwen"), project_root=project_root, home_root=home_root
    )
    section = _by_id(compiled, "pkg.provider.qwen")
    assert section["status"] == "excluded"
    assert section["reason"] == "no_directive"
    assert section["provider_specific"] is True
    assert section["required"] is False
    assert provider_directive("qwen") is None


def test_provider_directive_texts_are_adapter_owned() -> None:
    """Directive texts match the adapter constants (not copies)."""
    from sase.llm_provider.claude import _SINGLE_TURN_DIRECTIVE as claude
    from sase.llm_provider.grok import _GROK_SINGLE_TURN_DIRECTIVE as grok

    assert provider_directive("claude") == claude
    assert provider_directive("grok") == grok
    assert provider_directive("muse", synchronous=True) is not None
    with pytest.raises(ValueError, match="unknown provider"):
        provider_directive("no_such_provider")


def test_codex_grok_differ_only_in_provider_section(tmp_path: Path) -> None:
    """Codex/Grok bundles differ only in pkg.provider.* (equal common_digest)."""
    project_root, home_root = make_roots(tmp_path)
    codex = compile_bundle(
        make_facts(provider="codex"), project_root=project_root, home_root=home_root
    )
    grok = compile_bundle(
        make_facts(provider="grok"), project_root=project_root, home_root=home_root
    )
    assert codex.text != grok.text
    codex_manifest = build_manifest(
        codex, make_facts(provider="codex"), preview_delivery()
    )
    grok_manifest = build_manifest(
        grok, make_facts(provider="grok"), preview_delivery()
    )
    assert (
        codex_manifest["bundle"]["common_digest"]
        == grok_manifest["bundle"]["common_digest"]
    )
    codex_ids = {section["id"] for section in codex_manifest["sections"]}
    assert "pkg.provider.codex" in codex_ids


def test_identical_inputs_are_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same content in two cwds and two paths gives identical bundles."""
    first = tmp_path / "first" / "proj"
    first.mkdir(parents=True)
    project_root, home_root = make_roots(tmp_path / "first")
    assert project_root == first
    second_parent = tmp_path / "second"
    second_parent.mkdir()
    shutil.copytree(project_root, second_parent / "proj")
    facts = make_facts()
    monkeypatch.chdir(tmp_path)
    left = compile_bundle(facts, project_root=project_root, home_root=home_root)
    monkeypatch.chdir(second_parent)
    right = compile_bundle(
        facts, project_root=second_parent / "proj", home_root=home_root
    )
    assert left.text == right.text
    assert left.sha256 == right.sha256
    left_manifest = build_manifest(left, facts, preview_delivery())
    right_manifest = build_manifest(right, facts, preview_delivery())
    left_manifest["delivery"] = right_manifest["delivery"] = {}
    assert left_manifest == right_manifest


def test_compiling_writes_nothing_under_project_root(tmp_path: Path) -> None:
    """Compiling in a git repo leaves `git status --porcelain` clean."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is unavailable")
    project_root, home_root = make_roots(tmp_path)
    import subprocess

    subprocess.run([git, "init", "-q"], cwd=project_root, check=True)
    subprocess.run(
        [git, "add", "-A"], cwd=project_root, check=True, capture_output=True
    )
    before = subprocess.run(
        [git, "status", "--porcelain"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    compile_bundle(make_facts(), project_root=project_root, home_root=home_root)
    after = subprocess.run(
        [git, "status", "--porcelain"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert before == after


def test_facts_reject_unknown_keys_values_and_combos(tmp_path: Path) -> None:
    """Fact parsing names the valid choices and rejects wrong-actor sections."""
    with pytest.raises(InstructionFactsError, match="unknown fact"):
        parse_facts({"actor": "sase_root", "mode": "runtime", "bogus": 1})
    with pytest.raises(InstructionFactsError, match="codx"):
        parse_facts(
            {
                "actor": "sase_root",
                "mode": "runtime",
                "purpose": "ordinary",
                "provider": "codx",
                "project": "fixture",
                "host": "testhost",
                "vcs": None,
            }
        )
    with pytest.raises(InstructionFactsError, match="invalid fact combination"):
        parse_facts(
            {
                "actor": "native_helper",
                "mode": "export",
                "purpose": "ordinary",
                "provider": "codex",
                "project": "fixture",
                "host": "testhost",
                "vcs": None,
            }
        )
    with pytest.raises(_InstructionManifestError):
        from sase.core.instruction_manifest import normalize_instruction_manifest

        parent = tmp_path / "instr-rust-combo"
        project_root, _ = make_roots(parent)
        compiled = compile_bundle(
            make_facts(), project_root=project_root, home_root=parent / "no-home"
        )
        manifest = build_manifest(compiled, make_facts(), preview_delivery())
        manifest["facts"]["actor"] = "native_helper"
        manifest["facts"]["mode"] = "export"
        normalize_instruction_manifest(manifest)


def test_manifest_shape_and_common_digest(tmp_path: Path) -> None:
    """The assembled manifest carries compiler identity and filled digests."""
    project_root, home_root = make_roots(tmp_path)
    facts = make_facts()
    compiled = compile_bundle(facts, project_root=project_root, home_root=home_root)
    manifest = build_manifest(compiled, facts, preview_delivery())
    assert manifest["schema_version"] == 1
    assert manifest["compiler"]["name"] == COMPILER_NAME
    assert manifest["compiler"]["version"] == COMPILER_VERSION
    assert manifest["facts"] == facts.to_dict()
    assert manifest["bundle"]["sha256"] == compiled.sha256
    assert len(manifest["bundle"]["common_digest"]) == 64
    assert manifest["observation"] == {"status": "unobserved"}
    included = [s for s in manifest["sections"] if s["status"] == "included"]
    cursor = 0
    for section in included:
        assert section["offset"] == cursor
        cursor += section["length"]
    assert cursor == manifest["bundle"]["bytes"]


def test_section_slug_and_tokens() -> None:
    """Slug and token helpers behave deterministically."""
    assert section_slug("Gotchas") == "gotchas"
    assert section_slug("My Custom Section!") == "my_custom_section"
    assert tokens_estimate("abcd") == 1
    assert tokens_estimate("abcde") == 2


def test_compile_rejects_missing_project_root(tmp_path: Path) -> None:
    """A missing project root is an error, not an empty bundle."""
    with pytest.raises(InstructionCompileError, match="not a directory"):
        compile_bundle(
            make_facts(), project_root=tmp_path / "missing", home_root=tmp_path
        )


def test_custom_template_heading_gets_own_section(tmp_path: Path) -> None:
    """Unknown H2 headings in an override template map to pkg.sase.<slug>."""
    project_root, home_root = make_roots(tmp_path)
    write(
        project_root / "custom-template.md",
        "# Fixture {{ project_name }}\n\n## Custom Section\n\n{{ linked_repo_entries }}\n",
    )
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nmemory:\n  sase_template: custom-template.md\n",
    )
    compiled = compile_bundle(
        make_facts(), project_root=project_root, home_root=home_root
    )
    assert _by_id(compiled, "pkg.sase.custom_section")["status"] == "included"
