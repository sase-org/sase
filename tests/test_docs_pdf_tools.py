from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "postprocess_docs_pdf"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("postprocess_docs_pdf_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "postprocess_docs_pdf_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _image(*, reference: int, image_format: str, mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        indirect_reference=SimpleNamespace(idnum=reference),
        image=SimpleNamespace(format=image_format, mode=mode),
        replace=Mock(),
    )


def test_pdf_image_optimization_reencodes_each_shared_rgb_png_once() -> None:
    tool = _load_tool()
    first = _image(reference=7, image_format="PNG", mode="RGB")
    duplicate = _image(reference=7, image_format="PNG", mode="RGB")
    jpeg = _image(reference=8, image_format="JPEG", mode="RGB")
    transparent = _image(reference=9, image_format="PNG", mode="RGBA")
    writer = SimpleNamespace(
        pages=[
            SimpleNamespace(images=[first, jpeg]),
            SimpleNamespace(images=[duplicate, transparent]),
        ]
    )

    assert tool._optimize_images(writer) == 1
    first.replace.assert_called_once_with(
        first.image,
        quality=tool.IMAGE_JPEG_QUALITY,
        optimize=True,
    )
    duplicate.replace.assert_not_called()
    jpeg.replace.assert_not_called()
    transparent.replace.assert_not_called()
