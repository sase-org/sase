"""Tests for the built-site URL and anchor compatibility checker."""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_docs_urls"


def _load_checker() -> ModuleType:
    name = "check_docs_urls_test"
    loader = SourceFileLoader(name, str(TOOL_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def test_url_contract_follows_redirect_and_checks_anchor(tmp_path: Path) -> None:
    checker = _load_checker()
    page = tmp_path / "new" / "index.html"
    page.parent.mkdir()
    page.write_text('<html><h1 id="kept-anchor"></h1></html>', encoding="utf-8")

    errors = checker.validate_urls(
        tmp_path,
        [("https://sase.sh/old/#kept-anchor", "fixture")],
        {"/old/": "/new/"},
    )

    assert errors == []


def test_url_contract_reports_missing_page_and_anchor(tmp_path: Path) -> None:
    checker = _load_checker()
    page = tmp_path / "existing" / "index.html"
    page.parent.mkdir()
    page.write_text('<html><h1 id="present"></h1></html>', encoding="utf-8")

    errors = checker.validate_urls(
        tmp_path,
        [
            ("https://sase.sh/missing/", "missing page fixture"),
            ("https://sase.sh/existing/#absent", "missing anchor fixture"),
        ],
        {},
    )

    assert len(errors) == 2
    assert "missing page" in errors[0]
    assert "missing anchor #absent" in errors[1]


def test_url_extraction_keeps_fragments_and_drops_sentence_punctuation() -> None:
    checker = _load_checker()

    urls = checker.extract_sase_urls(
        "Read https://sase.sh/ace/#prompt-history-modal, then https://sase.sh."
    )

    assert urls == {"https://sase.sh/ace/#prompt-history-modal", "https://sase.sh"}
