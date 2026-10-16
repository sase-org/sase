"""Tests for the generated page-move pipeline and the section splitter."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
from types import ModuleType

import yaml


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _load(name: str, path: Path) -> ModuleType:
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _move_fixture(root: Path) -> None:
    (root / "docs/_meta").mkdir(parents=True)
    (root / "docs/_meta/moves.yml").write_text(
        "moves:\n"
        "  - from: instruction_inventory.md\n"
        "    to: instruction_bundles.md\n"
        "    kind: redirect\n",
        encoding="utf-8",
    )
    (root / "docs/_redirects").write_text("/manual/ /guide/ 301\n", encoding="utf-8")
    (root / "mkdocs.yml").write_text(
        "site_name: Fixture\nnav:\n  - Home: index.md\n", encoding="utf-8"
    )
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/instruction_inventory.md").write_text(
        "# Instruction Inventory\n\nHistorical page.\n", encoding="utf-8"
    )
    (root / "docs/instruction_bundles.md").write_text(
        "# Instruction Bundles\n\nBundle page.\n", encoding="utf-8"
    )


def _docs_move_fixture(root: Path, source: str = "acknowledgements.md") -> None:
    _move_fixture(root)
    (root / "docs/contribute").mkdir(parents=True)
    (root / "docs/_meta/budgets.yml").write_text(
        f"ceilings:\n  {source}: 12\n  other.md: 20\n", encoding="utf-8"
    )
    (root / "mkdocs.yml").write_text(
        "site_name: Fixture\nnav:\n  - Home: index.md\n"
        f"  - Acknowledgements: {source}\n",
        encoding="utf-8",
    )


def test_docs_move_rewrites_links_frontmatter_nav_budgets_and_redirect(
    tmp_path: Path,
) -> None:
    mover = _load("docs_move_fixture", TOOLS / "docs_move")
    renderer = _load("render_moves_whole_move_fixture", TOOLS / "render_moves")
    _docs_move_fixture(tmp_path)
    docs = tmp_path / "docs"
    source = docs / "acknowledgements.md"
    source.write_text(
        "# Acknowledgements\n\n"
        "## Projects\n\n"
        "[Relative](other.md#thing) [Self](acknowledgements.md#projects)\n",
        encoding="utf-8",
    )
    (docs / "other.md").write_text('# Other\n\n<a id="thing"></a>\n', encoding="utf-8")
    (docs / "links.md").write_text(
        "# Links\n\n[Inline](acknowledgements.md#projects) [Reference]\n"
        "[Reference]: acknowledgements.md#projects\n"
        "<a href='acknowledgements.md#projects'>HTML</a>\n"
        '<img src="acknowledgements.md#projects">\n',
        encoding="utf-8",
    )
    (docs / "index.md").write_text(
        '# Home\n\n<a href="acknowledgements/">Thanks</a>\n'
        '<a href="guides/">Guides</a>\n',
        encoding="utf-8",
    )
    (docs / "contribute/index.md").write_text(
        "# Contribute\n\n[Thanks](../acknowledgements/)\n", encoding="utf-8"
    )
    generated = docs / "generated.md"
    generated.write_text(
        "<!-- Generated, do not edit. -->\n[Generated](acknowledgements.md#projects)\n",
        encoding="utf-8",
    )

    warnings = mover.move_page(
        "acknowledgements.md",
        "contribute/acknowledgements.md",
        title="Acknowledgements",
        description="People and projects that shaped SASE.",
        root=tmp_path,
    )

    destination = docs / "contribute/acknowledgements.md"
    moved = destination.read_text(encoding="utf-8")
    assert not source.exists()
    assert 'title: "Acknowledgements"' in moved
    assert 'description: "People and projects that shaped SASE."' in moved
    assert "[Relative](../other.md#thing)" in moved
    assert "[Self](#projects)" in moved
    links = (docs / "links.md").read_text(encoding="utf-8")
    assert "contribute/acknowledgements.md#projects" in links
    assert "<a href='contribute/acknowledgements.md#projects'>" in links
    assert 'src="contribute/acknowledgements.md#projects"' in links
    home = (docs / "index.md").read_text(encoding="utf-8")
    assert 'href="contribute/acknowledgements/"' in home
    assert 'href="guides/"' in home
    section_home = (docs / "contribute/index.md").read_text(encoding="utf-8")
    assert "[Thanks](acknowledgements/)" in section_home
    assert "acknowledgements.md#projects" in generated.read_text(encoding="utf-8")
    assert any("generated.md" in warning for warning in warnings)
    assert "Acknowledgements: contribute/acknowledgements.md" in (
        tmp_path / "mkdocs.yml"
    ).read_text(encoding="utf-8")
    budgets = (docs / "_meta/budgets.yml").read_text(encoding="utf-8")
    assert "acknowledgements.md" not in budgets
    assert "other.md: 20" in budgets
    moves = yaml.safe_load((docs / "_meta/moves.yml").read_text(encoding="utf-8"))
    move = next(
        item for item in moves["moves"] if item["from"] == "acknowledgements.md"
    )
    assert move["to"] == "contribute/acknowledgements.md"
    assert move["kind"] == "redirect"

    renderer.render(tmp_path)
    assert "/acknowledgements/ /contribute/acknowledgements/ 301" in (
        docs / "_redirects"
    ).read_text(encoding="utf-8")


def test_docs_move_nav_rewrite_ignores_hyphenated_sibling_paths(
    tmp_path: Path,
) -> None:
    mover = _load("docs_move_hyphenated_nav_fixture", TOOLS / "docs_move")
    _docs_move_fixture(tmp_path, "editor.md")
    docs = tmp_path / "docs"
    (docs / "editor.md").write_text("# Editor\n\nEditor page.\n", encoding="utf-8")
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: Fixture\nnav:\n  - Home: index.md\n"
        "  - Editor integration: editor.md\n"
        "  - Macro CLI and editor: reference/macros/cli-and-editor.md\n"
        "  - Setup: guides/setup-completion-editor.md\n"
        "  - sase editor: reference/cli/editor.md\n",
        encoding="utf-8",
    )

    mover.move_page(
        "editor.md",
        "reference/integrations/editor.md",
        title="Editor Integration",
        description="Language-server surfaces for prompt editing.",
        root=tmp_path,
    )

    nav = (tmp_path / "mkdocs.yml").read_text(encoding="utf-8")
    assert "Editor integration: reference/integrations/editor.md" in nav
    assert "Macro CLI and editor: reference/macros/cli-and-editor.md" in nav
    assert "Setup: guides/setup-completion-editor.md" in nav
    assert "sase editor: reference/cli/editor.md" in nav
    assert not (docs / "editor.md").exists()
    assert (docs / "reference/integrations/editor.md").is_file()


def test_docs_move_stub_records_all_heading_and_html_anchors(tmp_path: Path) -> None:
    mover = _load("docs_move_stub_fixture", TOOLS / "docs_move")
    renderer = _load("render_moves_stub_fixture", TOOLS / "render_moves")
    _docs_move_fixture(tmp_path, "source.md")
    docs = tmp_path / "docs"
    (docs / "source.md").write_text(
        "# Source page\n\n## Repeated\n\n### Repeated\n\n"
        '#### Named heading {#named-heading}\n\n<a id="html-anchor"></a>\n',
        encoding="utf-8",
    )

    mover.move_page(
        "source.md",
        "reference/source.md",
        title="Source page",
        description="Moved reference page.",
        stub=True,
        root=tmp_path,
    )
    moves = yaml.safe_load((docs / "_meta/moves.yml").read_text(encoding="utf-8"))
    move = next(item for item in moves["moves"] if item["from"] == "source.md")
    assert move["kind"] == "stub"
    assert move["title"] == "Source page"
    assert move["anchors"] == {
        "source-page": "reference/source.md#source-page",
        "repeated": "reference/source.md#repeated",
        "repeated-1": "reference/source.md#repeated-1",
        "named-heading": "reference/source.md#named-heading",
        "html-anchor": "reference/source.md#html-anchor",
    }

    renderer.render(tmp_path)
    stub = (docs / "source.md").read_text(encoding="utf-8")
    for anchor in move["anchors"]:
        assert f'<a id="{anchor}"></a>' in stub
    assert '<a id="repeated"></a>\n\n- [Repeated](reference/source.md#repeated)' in stub


def test_moves_renderer_preserves_manual_redirects_and_generates_stubs(
    tmp_path: Path,
) -> None:
    renderer = _load("render_moves_fixture", TOOLS / "render_moves")
    _move_fixture(tmp_path)
    moves_path = tmp_path / "docs/_meta/moves.yml"
    payload = yaml.safe_load(moves_path.read_text(encoding="utf-8"))
    payload["moves"].append(
        {
            "from": "old_reference.md",
            "to": "reference/new.md",
            "kind": "stub",
            "anchors": {"old-heading": "reference/new.md#new-heading"},
        }
    )
    moves_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    (tmp_path / "docs/old_reference.md").write_text(
        "<!-- generated, do not edit; source: docs/_meta/moves.yml -->\n"
        "# Old Reference\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/reference").mkdir()
    (tmp_path / "docs/reference/new.md").write_text(
        "# New Reference\n", encoding="utf-8"
    )

    renderer.render(tmp_path)

    redirects = (tmp_path / "docs/_redirects").read_text(encoding="utf-8")
    assert "/manual/ /guide/ 301" in redirects
    assert "/instruction_inventory/ /instruction_bundles/ 301" in redirects
    stub = (tmp_path / "docs/old_reference.md").read_text(encoding="utf-8")
    assert "This page has moved. See [New Reference](reference/new.md)." in stub
    assert '<a id="old-heading"></a>' in stub
    assert "reference/new.md#new-heading" in stub
    assert "search:" in stub and "exclude: true" in stub
    assert renderer._is_generated_stub(stub)
    nav_config = (tmp_path / "mkdocs.yml").read_text(encoding="utf-8")
    assert "not_in_nav: |" in nav_config
    assert "  old_reference.md" in nav_config
    assert renderer.check(tmp_path) == []


def test_docs_split_moves_sections_rewrites_links_and_preserves_anchor_urls(
    tmp_path: Path,
) -> None:
    splitter = _load("docs_split_fixture", TOOLS / "docs_split")
    renderer = _load("render_moves_split_fixture", TOOLS / "render_moves")
    checker = _load("check_docs_urls_split_fixture", TOOLS / "check_docs_urls")
    _move_fixture(tmp_path)
    source = tmp_path / "docs/source.md"
    source.write_text(
        "# Source\n\n"
        "Start here. [Alpha](source.md#alpha)\n\n"
        "## Alpha\n\n"
        "Alpha links to [Beta](source.md#beta) and [other](other.md#thing).\n\n"
        "## Beta\n\n"
        "Beta is here.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/other.md").write_text(
        '# Other\n\n<a id="thing"></a>\n', encoding="utf-8"
    )
    (tmp_path / "docs/links.md").write_text(
        "# Links\n\n[Alpha](source.md#alpha) [Beta](source.md#beta)\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/reference").mkdir()
    (tmp_path / "docs/reference/alpha.md").write_text(
        "---\ntitle: Alpha\ndescription: Alpha section.\n---\n\n# Alpha\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/reference/beta.md").write_text(
        "---\ntitle: Beta\ndescription: Beta section.\n---\n\n# Beta\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "split.yml"
    mapping.write_text(
        "sections:\n  Alpha: reference/alpha.md\n  Beta: reference/beta.md\n",
        encoding="utf-8",
    )

    moved = splitter.split(source, mapping, root=tmp_path)
    renderer.render(tmp_path)

    assert moved == [("Alpha", "reference/alpha.md"), ("Beta", "reference/beta.md")]
    assert "## Alpha" not in source.read_text(encoding="utf-8")
    alpha = (tmp_path / "docs/reference/alpha.md").read_text(encoding="utf-8")
    assert "## Alpha" in alpha
    assert "beta.md#beta-1" in alpha
    assert "../other.md#thing" in alpha
    links = (tmp_path / "docs/links.md").read_text(encoding="utf-8")
    assert "reference/alpha.md#alpha" in links
    assert "reference/beta.md#beta" in links

    moves = yaml.safe_load(
        (tmp_path / "docs/_meta/moves.yml").read_text(encoding="utf-8")
    )
    assert (
        (tmp_path / "docs/_meta/moves.yml")
        .read_text(encoding="utf-8")
        .startswith("moves:\n  - from:")
    )
    split_move = next(item for item in moves["moves"] if item["from"] == "source.md")
    assert split_move["anchors"] == {
        "alpha": "reference/alpha.md#alpha-1",
        "beta": "reference/beta.md#beta-1",
    }
    stub = (tmp_path / "docs/source.md").read_text(encoding="utf-8")
    assert '<a id="alpha"></a>' in stub
    assert '<a id="beta"></a>' in stub
    expected_redirects, references = checker.read_move_contract(
        tmp_path / "docs/_meta/moves.yml"
    )
    assert expected_redirects["/instruction_inventory/"] == "/instruction_bundles/"

    site = tmp_path / "site"
    for route, anchors in (
        ("source", {"alpha", "beta"}),
        ("reference/alpha", {"alpha-1"}),
        ("reference/beta", {"beta-1"}),
        ("instruction_bundles", set()),
    ):
        page = site / route / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "<html>"
            + "".join(f'<a id="{anchor}"></a>' for anchor in anchors)
            + "</html>",
            encoding="utf-8",
        )
    assert checker.validate_urls(site, references, expected_redirects) == []


def test_moves_renderer_does_not_clobber_a_partial_split_page(tmp_path: Path) -> None:
    renderer = _load("render_moves_partial_fixture", TOOLS / "render_moves")
    _move_fixture(tmp_path)
    moves_path = tmp_path / "docs/_meta/moves.yml"
    payload = yaml.safe_load(moves_path.read_text(encoding="utf-8"))
    payload["moves"].append(
        {
            "from": "source.md",
            "to": "reference/index.md",
            "kind": "stub",
            "title": "Stable source",
        }
    )
    moves_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    source = tmp_path / "docs/source.md"
    source.write_text("# Source\n\nUnmoved section.\n", encoding="utf-8")
    (tmp_path / "docs/reference").mkdir()
    (tmp_path / "docs/reference/index.md").write_text("# Reference\n", encoding="utf-8")

    renderer.render(tmp_path)

    assert source.read_text(encoding="utf-8") == "# Source\n\nUnmoved section.\n"
    assert renderer.check(tmp_path) == []


def test_docs_split_supports_h4_nested_intro_drop_and_finish(tmp_path: Path) -> None:
    splitter = _load("docs_split_nested_fixture", TOOLS / "docs_split")
    renderer = _load("render_moves_nested_fixture", TOOLS / "render_moves")
    _move_fixture(tmp_path)
    docs = tmp_path / "docs"
    source = docs / "source.md"
    source.write_text(
        "# Source\n\nAn intro sentence.\n\n"
        "## Parent\n\nParent facts.\n\n"
        "### Child\n\nChild facts.\n\n"
        "#### Deep Heading\n\n"
        '<a id="deep-html"></a>\n'
        "A deep section with [a local link](source.md#child-detail).\n\n"
        "##### Child Detail {#child-detail}\n\nDeep detail.\n\n"
        "## Keep\n\nKeep this for the next partial split.\n\n"
        "## Contents\n\n[Keep](source.md#keep)\n",
        encoding="utf-8",
    )
    (docs / "reference").mkdir()
    (docs / "reference/index.md").write_text(
        "---\ntitle: Reference\ndescription: Reference index.\n---\n\n# Reference\n",
        encoding="utf-8",
    )
    (docs / "reference/parent.md").write_text(
        "---\ntitle: Parent\ndescription: Parent facts.\n---\n\n# Parent\n",
        encoding="utf-8",
    )
    (docs / "reference/deep.md").write_text(
        "---\ntitle: Deep Heading\ndescription: Deep facts.\n---\n\n# Deep Heading\n",
        encoding="utf-8",
    )
    (docs / "reference/intro.md").write_text(
        "---\ntitle: Introduction\ndescription: Source introduction.\n---\n\n# Introduction\n",
        encoding="utf-8",
    )
    (docs / "links.md").write_text(
        "# Links\n\n"
        "[inline](source.md#child-detail) [ref]\n"
        "[ref]: source.md#deep-heading\n"
        '<a href="source.md#child-detail">local</a>\n'
        "<img src='source.md#deep-html'>\n",
        encoding="utf-8",
    )
    (docs / "generated.md").write_text(
        "<!-- Generated, do not edit. -->\n[generated](source.md#child-detail)\n",
        encoding="utf-8",
    )
    (docs / "blocks.md").write_text(
        "# Blocks\n\n<!-- BEGIN GENERATED: test -->\n"
        "[generated](source.md#child-detail)\n<!-- END GENERATED: test -->\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "split.yml"
    mapping.write_text(
        "to: reference/index.md\n"
        "sections:\n"
        "  _intro: reference/intro.md\n"
        "  Parent: reference/parent.md\n"
        "  Parent > Child > Deep Heading: reference/deep.md\n"
        "  Contents:\n"
        "    drop: true\n"
        "    anchor_target: reference/index.md#contents\n",
        encoding="utf-8",
    )

    first = splitter.plan_split(source, mapping, root=tmp_path)
    assert first.unmapped == ["Keep"]
    assert source.exists()  # Planning and dry-run never mutate files.
    splitter.split(source, mapping, root=tmp_path)

    parent = (docs / "reference/parent.md").read_text(encoding="utf-8")
    deep = (docs / "reference/deep.md").read_text(encoding="utf-8")
    assert "### Child" in parent
    assert "#### Deep Heading" not in parent
    assert '<a id="deep-heading"></a>' in parent
    assert "Moved to [Deep Heading](deep.md#deep-heading-1)." in parent
    assert "## Deep Heading" in deep
    assert "### Child Detail {#child-detail}" in deep
    assert "deep-html" in deep
    assert "Moved to [Reference](reference/index.md#contents)." in source.read_text(
        encoding="utf-8"
    )
    assert "reference/deep.md#child-detail" in (docs / "links.md").read_text(
        encoding="utf-8"
    )
    assert "source.md#child-detail" in (docs / "generated.md").read_text(
        encoding="utf-8"
    )
    assert "source.md#child-detail" in (docs / "blocks.md").read_text(encoding="utf-8")
    assert first.warnings and "update the renderer" in first.warnings[0]

    finish_mapping = tmp_path / "finish.yml"
    finish_mapping.write_text("sections:\n  Keep: {drop: true}\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    finish_plan = splitter.plan_split(
        source, finish_mapping, root=tmp_path, finish=True
    )
    assert finish_plan.unmapped == []
    assert source.read_text(encoding="utf-8") == before
    splitter.split(source, finish_mapping, root=tmp_path, finish=True)
    assert not source.exists()
    renderer.render(tmp_path)
    stub = source.read_text(encoding="utf-8")
    assert "Stable source" not in stub  # The source title was stored before deletion.
    assert "# Source" in stub
    assert "See [Reference](reference/index.md)." in stub
    assert "search:" in stub and "exclude: true" in stub
    moves = yaml.safe_load((docs / "_meta/moves.yml").read_text(encoding="utf-8"))
    source_move = next(item for item in moves["moves"] if item["from"] == "source.md")
    assert source_move["to"] == "reference/index.md"
    assert source_move["anchors"]["deep-heading"] == "reference/deep.md#deep-heading-1"
    assert source_move["anchors"]["deep-html"] == "reference/deep.md#deep-html"
    assert source_move["anchors"]["child-detail"] == "reference/deep.md#child-detail"
    assert source_move["anchors"]["contents"] == "reference/index.md#contents"


def test_docs_split_handles_nested_first_selection(tmp_path: Path) -> None:
    splitter = _load("docs_split_first_nested_fixture", TOOLS / "docs_split")
    _move_fixture(tmp_path)
    docs = tmp_path / "docs"
    source = docs / "source.md"
    source.write_text(
        "# Source\n\n## Parent\n\nParent facts.\n\n### Child\n\nChild facts.\n",
        encoding="utf-8",
    )
    (docs / "reference").mkdir()
    for title in ("Parent", "Child"):
        (docs / "reference" / f"{title.lower()}.md").write_text(
            f"---\ntitle: {title}\ndescription: {title} facts.\n---\n\n# {title}\n",
            encoding="utf-8",
        )
    mapping = tmp_path / "split.yml"
    mapping.write_text(
        "sections:\n  Parent: reference/parent.md\n"
        "  Parent > Child: reference/child.md\n",
        encoding="utf-8",
    )

    splitter.split(source, mapping, root=tmp_path)

    parent = (docs / "reference/parent.md").read_text(encoding="utf-8")
    child = (docs / "reference/child.md").read_text(encoding="utf-8")
    assert "Parent facts." in parent
    assert "Child facts." not in parent
    assert "Moved to [Child](child.md#child-1)." in parent
    assert "Child facts." in child


def test_docs_split_rewrites_inbound_links_but_skips_generated_sources(
    tmp_path: Path,
) -> None:
    splitter = _load("docs_split_links_fixture", TOOLS / "docs_split")
    _move_fixture(tmp_path)
    docs = tmp_path / "docs"
    source = docs / "source.md"
    source.write_text('# Source\n\n## Alpha\n\n<a id="html"></a>\n', encoding="utf-8")
    (docs / "reference").mkdir()
    (docs / "reference/alpha.md").write_text(
        "---\ntitle: Alpha\ndescription: Alpha.\n---\n\n# Alpha\n", encoding="utf-8"
    )
    (docs / "reference/index.md").write_text("# Reference\n", encoding="utf-8")
    (docs / "links.md").write_text(
        "# Links\n[inline](source.md#alpha) [ref]\n"
        "[ref]: source.md#html\n<a href='source.md#html'>link</a>\n"
        '<img src="source.md#alpha">\n',
        encoding="utf-8",
    )
    mapping = tmp_path / "split.yml"
    mapping.write_text("sections:\n  Alpha: reference/alpha.md\n", encoding="utf-8")

    splitter.split(source, mapping, root=tmp_path)

    links = (docs / "links.md").read_text(encoding="utf-8")
    assert "reference/alpha.md#alpha" in links
    assert "reference/alpha.md#html" in links


def test_docs_split_dry_run_reports_budget_and_unmapped_headings(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    splitter = _load("docs_split_dry_run_fixture", TOOLS / "docs_split")
    _move_fixture(tmp_path)
    monkeypatch.setattr(splitter, "ROOT", tmp_path)
    docs = tmp_path / "docs"
    (docs / "source.md").write_text(
        "# Source\n\n## Alpha\n\n" + "word " * 6050 + "\n\n## Beta\n\nStill here.\n",
        encoding="utf-8",
    )
    (docs / "reference").mkdir()
    (docs / "reference/index.md").write_text("# Reference\n", encoding="utf-8")
    (docs / "reference/alpha.md").write_text(
        "---\ntitle: Alpha\ndescription: Alpha.\n---\n\n# Alpha\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "split.yml"
    mapping.write_text("sections:\n  Alpha: reference/alpha.md\n", encoding="utf-8")

    code = splitter.main(["source.md", "split.yml", "--dry-run"])

    output = capsys.readouterr().out
    assert code == 1
    assert "OVER BUDGET" in output
    assert "Unmapped: Beta" in output
    assert (docs / "source.md").exists()
    assert "## Alpha" not in (docs / "reference/alpha.md").read_text(encoding="utf-8")


def test_docs_map_lists_pages_by_nav_tab_and_canonical_move(
    tmp_path: Path,
) -> None:
    renderer = _load("render_docs_map_fixture", TOOLS / "render_docs_map")
    _move_fixture(tmp_path)
    (tmp_path / "docs/index.md").write_text(
        "---\ntitle: Home\n---\n\n# Home\n\nA home page.\n", encoding="utf-8"
    )
    (tmp_path / "docs/reference").mkdir()
    (tmp_path / "docs/reference/api.md").write_text(
        "---\ntitle: API\ndescription: API facts.\n---\n\n# API\n", encoding="utf-8"
    )
    (tmp_path / "docs/images").mkdir()
    (tmp_path / "docs/images/ignored.prompt.md").write_text(
        "# Internal prompt\n", encoding="utf-8"
    )
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: Fixture\nsite_url: https://example.test/\n"
        "exclude_docs: |\n  images/**/*.prompt.md\n"
        "nav:\n  - Home: index.md\n  - Reference:\n      - API: reference/api.md\n",
        encoding="utf-8",
    )

    readme, llms = renderer.render_docs_map(tmp_path)

    assert "## Reference" in readme
    assert "[API](reference/api.md) — API facts." in readme
    assert "https://example.test/reference/api/" in llms
    assert "`/instruction_inventory/`" in readme
    assert "https://example.test/instruction_inventory/" in llms
    assert "ignored.prompt.md" not in readme
    assert "ignored.prompt.md" not in llms
