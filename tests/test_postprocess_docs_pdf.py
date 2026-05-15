from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_postprocess_docs_pdf() -> ModuleType:
    pypdf_stub = types.ModuleType("pypdf")
    pypdf_stub.__dict__.update({"PdfReader": object, "PdfWriter": object})
    sys.modules.setdefault("pypdf", pypdf_stub)
    loader = SourceFileLoader(
        "postprocess_docs_pdf_tool", str(ROOT / "tools" / "postprocess_docs_pdf")
    )
    spec = importlib.util.spec_from_file_location(
        "postprocess_docs_pdf_tool",
        ROOT / "tools" / "postprocess_docs_pdf",
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def test_chapter_start_page_ignores_in_body_title_mentions() -> None:
    tool = _load_postprocess_docs_pdf()

    page = tool._find_chapter_start_page(
        [
            "sase handbook preface",
            "body text with 13 notifications in a footer url",
            "sase handbook 13 notifications notification rules",
        ],
        "Notifications",
        start=1,
    )

    assert page == 2


def test_chapter_pages_advance_past_previous_match() -> None:
    tool = _load_postprocess_docs_pdf()
    chapters = [
        tool.Chapter(
            number=1,
            nav_title="Intro",
            source_path="index.md",
            html_path=Path("site/index.html"),
            pdf_path=Path("site/index.pdf"),
            headings=(tool.Heading(1, "Intro"),),
        ),
        tool.Chapter(
            number=2,
            nav_title="Notifications",
            source_path="notifications.md",
            html_path=Path("site/notifications/index.html"),
            pdf_path=Path("site/notifications/index.pdf"),
            headings=(tool.Heading(1, "Notifications"),),
        ),
    ]

    pages = tool._chapter_pages(
        chapters,
        [
            "cover",
            "toc",
            "sase handbook 1 intro intro body mentions notifications",
            "sase handbook 2 notifications notification rules",
        ],
    )

    assert pages == {1: 2, 2: 3}
