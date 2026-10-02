"""Fast smoke test for the pager benchmark harness (phase ``pager-bench``).

Deliberately non-slow: it runs the smallest case end to end in-process so
``sase tool run check`` catches harness rot without paying subprocess or
large-corpus costs.
"""

from __future__ import annotations

from pathlib import Path

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

from tests.perf._pager_bench_corpus import build_code_sparse, write_corpus


def test_bench_pager_smoke(tmp_path: Path) -> None:
    descriptors = write_corpus(tmp_path, cases=("code-sparse",), ladder=(30,))
    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor["name"] == "code-sparse"
    assert descriptor["lines"] == 30
    assert Path(str(descriptor["path"])).exists()

    # Deterministic corpus: same bytes on rebuild.
    assert build_code_sparse(30) == build_code_sparse(30)

    text = Path(str(descriptor["path"])).read_text(encoding="utf-8")
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="bench:smoke",
                title="smoke",
                kind="file",
                body=text,
            ),
        ),
        title="smoke",
        origin=PagerOrigin.FILE,
    )
    assert len(document.sections) == 1


async def test_bench_pager_smoke_mount() -> None:
    """Mount the smallest corpus headless and scroll once."""
    body = build_code_sparse(30)
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="bench:smoke",
                title="smoke",
                kind="file",
                body=body,
            ),
        ),
        title="smoke",
        origin=PagerOrigin.FILE,
    )
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
