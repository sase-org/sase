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
        "# Old Reference\n", encoding="utf-8"
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
    assert '<a id="old-heading"></a>' in stub
    assert "reference/new.md#new-heading" in stub
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
    assert "beta.md#beta" in alpha
    assert "../other.md#thing" in alpha
    links = (tmp_path / "docs/links.md").read_text(encoding="utf-8")
    assert "reference/alpha.md#alpha" in links
    assert "reference/beta.md#beta" in links

    moves = yaml.safe_load(
        (tmp_path / "docs/_meta/moves.yml").read_text(encoding="utf-8")
    )
    split_move = next(item for item in moves["moves"] if item["from"] == "source.md")
    assert split_move["anchors"] == {
        "alpha": "reference/alpha.md#alpha",
        "beta": "reference/beta.md#beta",
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
        ("reference/alpha", {"alpha"}),
        ("reference/beta", {"beta"}),
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
