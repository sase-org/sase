"""Tests for the documentation-contract lint tool (``tools/check_docs``)."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_docs"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_docs_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "check_docs_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_docs_tool"] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


GOOD_FM = "---\ntitle: T\ndescription: Short line.\n---\n\n"


def _fixture(root: Path) -> dict[str, Path]:
    docs = root / "docs"
    tests = root / "tests"
    tests.mkdir(parents=True)
    budgets = docs / "_meta" / "budgets.yml"
    _write(budgets, "ceilings:\n  legacy.md: 100\n")
    _write(docs / "legacy.md", "# Legacy\n\nSmall page.\n")
    _write(docs / "index.md", GOOD_FM + "# Home\n")
    mkdocs = root / "mkdocs.yml"
    _write(mkdocs, "plugins:\n  - search\n  - redirects\n")
    mkdocs_pdf = root / "mkdocs-pdf.yml"
    _write(mkdocs_pdf, "plugins:\n  - search\n  - exporter\n")
    return {
        "docs": docs,
        "budgets": budgets,
        "mkdocs": (mkdocs, mkdocs_pdf),
        "tests": tests,
    }


def _check(tool: ModuleType, fix: dict[str, Path]) -> list:
    ctx = tool.build_context(fix["docs"], fix["budgets"], fix["mkdocs"], fix["tests"])
    return tool.check_tree(ctx)


def _errors(findings: list) -> list[str]:
    return [f.message for f in findings if f.severity == "error"]


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_exclude_docs_multiline_string_is_split(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    with fix["mkdocs"][0].open("a", encoding="utf-8") as handle:
        handle.write("exclude_docs: |\n  scratch/*\n")
    _write(fix["docs"] / "scratch" / "notes.md", "# no FM, no type\n")
    assert tool.load_exclude_globs(fix["mkdocs"][0]) == ("scratch/*",)
    assert _errors(_check(tool, fix)) == []


def test_clean_fixture_passes(tmp_path: Path) -> None:
    tool = _load_tool()
    assert _errors(_check(tool, _fixture(tmp_path))) == []


def test_new_root_page_fails_typing(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "brand-new.md", GOOD_FM + "# New\n")
    (errors := _errors(_check(tool, fix)))
    assert any("brand-new.md" in e and "untyped" in e for e in errors)


def test_generated_root_stub_passes_typing(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "old-page.md",
        "---\ntitle: Old page\ndescription: Moved.\nsearch:\n  exclude: true\n---\n"
        "<!-- generated, do not edit; source: docs/_meta/moves.yml -->\n"
        "# Old page\n\nThis page moved.\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_homepage_requires_frontmatter_and_has_400_word_cap(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "index.md", "# Home\n")
    errors = _errors(_check(tool, fix))
    assert any(
        "index.md" in e and "missing frontmatter key 'title'" in e for e in errors
    )
    assert any(
        "index.md" in e and "missing frontmatter key 'description'" in e for e in errors
    )

    _write(fix["docs"] / "index.md", GOOD_FM + "# Home\n\n" + "word " * 410)
    errors = _errors(_check(tool, fix))
    assert any("index.md" in e and "400-word cap" in e for e in errors)


def test_stale_budget_entries_are_reported_and_removed(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["budgets"],
        "ceilings:\n  legacy.md: 100\n  missing.md: 100\n  moved.md: 100\n",
    )
    _write(
        fix["docs"] / "moved.md",
        "---\ntitle: Moved\ndescription: Moved.\n---\n"
        "<!-- generated, do not edit; source: docs/_meta/moves.yml -->\n# Moved\n",
    )
    errors = _errors(_check(tool, fix))
    assert any("stale entry for missing page missing.md" in error for error in errors)
    assert any("stale entry for generated stub moved.md" in error for error in errors)

    ctx = tool.build_context(fix["docs"], fix["budgets"], fix["mkdocs"], fix["tests"])
    assert tool.ratchet_ceilings(ctx) == [
        "legacy.md: 5",
        "removed stale ceiling: missing.md",
        "removed stale ceiling: moved.md",
    ]
    assert tool.load_budgets(fix["budgets"]) == {"legacy.md": 5}


def test_typed_page_passes_typing(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "guides" / "doing.md", GOOD_FM + "# Doing\n")
    assert _errors(_check(tool, fix)) == []


def test_missing_frontmatter_keys_fail(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "guides" / "doing.md", "# No frontmatter\n")
    errors = _errors(_check(tool, fix))
    assert any("missing frontmatter key 'title'" in e for e in errors)
    assert any("missing frontmatter key 'description'" in e for e in errors)


def test_long_description_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        "---\ntitle: T\ndescription: " + "x" * 161 + "\n---\n\n# D\n",
    )
    errors = _errors(_check(tool, fix))
    assert any("'description' must be one line" in e for e in errors)


def test_unknown_frontmatter_key_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        "---\ntitle: T\ndescription: Short.\nnope: 1\n---\n\n# D\n",
    )
    errors = _errors(_check(tool, fix))
    assert any("unknown frontmatter key 'nope'" in e for e in errors)


def test_covers_allowed_only_under_reference(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    page = "---\ntitle: T\ndescription: Short.\ncovers: x\n---\n\n# D\n"
    _write(fix["docs"] / "reference" / "thing.md", page)
    assert _errors(_check(tool, fix)) == []
    _write(fix["docs"] / "guides" / "doing.md", page)
    errors = _errors(_check(tool, fix))
    assert any("unknown frontmatter key 'covers'" in e for e in errors)


def test_over_ceiling_legacy_page_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "legacy.md", "# Legacy\n\n" + "word " * 200 + "\n")
    errors = _errors(_check(tool, fix))
    assert any("legacy.md" in e and "over budget" in e for e in errors)


def test_generated_blocks_do_not_count(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "legacy.md",
        "# Legacy\n\nSmall.\n\n<!-- BEGIN GENERATED -->\n"
        + "word " * 500
        + "\n<!-- END GENERATED -->\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_whole_file_generated_page_is_exempt(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "gen.md",
        "<!-- Generated, do not edit. -->\n\n# Big\n\n" + "word " * 9000 + "\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_over_cap_typed_page_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "guides" / "doing.md", GOOD_FM + "# D\n\n" + "word " * 2600)
    errors = _errors(_check(tool, fix))
    assert any("doing.md" in e and "over budget" in e for e in errors)


def test_contribute_over_cap_warns_only(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "contribute" / "long.md",
        GOOD_FM + "# D\n\n" + "word " * 8100 + "\n",
    )
    findings = _check(tool, fix)
    assert _errors(findings) == []
    assert any(f.severity == "warning" and "long.md" in f.message for f in findings)


def test_hygiene_patterns_fail_in_guides(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        GOOD_FM + "# D\n\nSee sase-1le.5 and src/sase/x.py. "
        "Formerly in phase sase-1le.6 (E3).\n",
    )
    errors = _errors(_check(tool, fix))
    joined = "\n".join(errors)
    assert "bead IDs" in joined
    assert "src/ paths" in joined
    assert "phase labels" in joined
    assert "history phrases" in joined


def test_hygiene_ignores_link_destinations(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        GOOD_FM
        + "# D\n\n"
        + "See the [diagram](../images/sase-concepts-model.svg) and "
        + '![alt](sase-1le.png "sase-1le title").\n\n'
        + "[ref]: ./sase-1le-diagram.svg\n\n"
        + '<img src="sase-1le.svg" href="sase-1le.html" poster="sase-1le.mp4">\n',
    )
    assert _errors(_check(tool, fix)) == []


def test_hygiene_flags_bead_id_in_visible_and_link_text(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        GOOD_FM + "# D\n\nSee sase-1le and [sase-1le](./ok.svg).\n",
    )
    errors = _errors(_check(tool, fix))
    joined = "\n".join(errors)
    assert "bead IDs" in joined
    assert "sase-1le" in joined


def test_hygiene_ignores_fenced_code(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "guides" / "doing.md",
        GOOD_FM + "# D\n\n```bash\ncat src/sase/x.py  # sase-1le.5\n```\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_hygiene_does_not_apply_to_reference(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "thing.md",
        GOOD_FM + "# D\n\nSee src/sase/x.py.\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_reference_hygiene_rejects_bead_and_epic_phase_labels(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "thing.md",
        GOOD_FM + "# D\n\nSee sase-1le.2.3 and phase sase-1le.4 (E5).\n",
    )
    errors = _errors(_check(tool, fix))
    assert any("bead IDs" in error for error in errors)
    assert any("epic or phase labels" in error for error in errors)


def test_reference_hygiene_ignores_link_destinations(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "thing.md",
        GOOD_FM
        + "# D\n\n"
        + "See the [diagram](../images/sase-1le-model.svg) and "
        + "![alt](sase-1le.png).\n\n"
        + "[ref]: ./sase-1le-diagram.svg\n\n"
        + '<img src="sase-1le.svg" href="sase-1le.html" poster="sase-1le.mp4">\n',
    )
    assert _errors(_check(tool, fix)) == []


def test_reference_hygiene_flags_bead_id_in_visible_and_link_text(
    tmp_path: Path,
) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "thing.md",
        GOOD_FM + "# D\n\nSee sase-1le and [sase-1le](./ok.svg).\n",
    )
    errors = _errors(_check(tool, fix))
    joined = "\n".join(errors)
    assert "bead IDs" in joined
    assert "sase-1le" in joined


def test_reference_hygiene_ignores_generated_blocks(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["docs"] / "reference" / "thing.md",
        GOOD_FM
        + "# D\n\n"
        + "<!-- BEGIN GENERATED -->\nsase-1le.2; phase sase-1le.4 (E5).\n"
        + "<!-- END GENERATED -->\n",
    )
    assert _errors(_check(tool, fix)) == []


def test_test_pin_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["tests"] / "test_thing.py", 'P = open("docs/guides/doing.md")\n')
    errors = _errors(_check(tool, fix))
    assert any("must not read docs Guide prose" in e for e in errors)


def test_tutorial_test_file_is_exempt(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(
        fix["tests"] / "test_docs_tutorial_runner.py",
        'P = open("docs/guides/doing.md")\n',
    )
    assert _errors(_check(tool, fix)) == []


def test_hooks_key_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    with fix["mkdocs"][0].open("a", encoding="utf-8") as handle:
        handle.write("hooks:\n  - tools/hook.py\n")
    errors = _errors(_check(tool, fix))
    assert any("'hooks:' is forbidden" in e for e in errors)


def test_unknown_plugin_fails(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    with fix["mkdocs"][0].open("a", encoding="utf-8") as handle:
        handle.write("  - gen-files\n")
    errors = _errors(_check(tool, fix))
    assert any("plugin 'gen-files'" in e for e in errors)


def test_exporter_allowed_only_in_pdf_config(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    assert _errors(_check(tool, fix)) == []
    with fix["mkdocs"][0].open("a", encoding="utf-8") as handle:
        handle.write("  - exporter\n")
    errors = _errors(_check(tool, fix))
    assert any("plugin 'exporter'" in e for e in errors)


def test_ratchet_lowers_but_never_raises(tmp_path: Path) -> None:
    tool = _load_tool()
    fix = _fixture(tmp_path)
    _write(fix["docs"] / "legacy.md", "# L\n\nTiny.\n")
    ctx = tool.build_context(fix["docs"], fix["budgets"], fix["mkdocs"], fix["tests"])
    changed = tool.ratchet_ceilings(ctx)
    assert changed == ["legacy.md: 4"]
    assert tool.load_budgets(fix["budgets"])["legacy.md"] == 4
    _write(fix["docs"] / "legacy.md", "# L\n\n" + "word " * 50 + "\n")
    ctx = tool.build_context(fix["docs"], fix["budgets"], fix["mkdocs"], fix["tests"])
    assert tool.ratchet_ceilings(ctx) == []
    assert tool.load_budgets(fix["budgets"])["legacy.md"] == 4
