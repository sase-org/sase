from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.referenced_by_index import (
    REFERENCED_BY_LINKS_DIR,
    document_has_referenced_by_block,
    referenced_by_index_path,
    referenced_by_index_relpath,
)

_REAL_BLOCK = """# Example

Body

<!-- sase:referenced-by:start -->

## Referenced By

| Agent | Project | Reference | Published | Uses |
| ----- | ------- | --------- | --------- | ---: |
| alice | sase    | plan:x.md | 2026-08-13 |    1 |

<!-- sase:referenced-by:end -->
"""

_FENCED_EXAMPLE = """# Design

Example:

```markdown
<!-- sase:referenced-by:start -->

## Referenced By

| Agent | Project | Reference | Published | Uses |
| ----- | ------- | --------- | --------- | ---: |
| alice | sase    | plan:x.md | 2026-08-13 |    1 |

<!-- sase:referenced-by:end -->
```
"""


def test_referenced_by_index_path_preserves_extension_under_links() -> None:
    root = Path("/tmp/plans")
    path = referenced_by_index_path(root, "plan:202608/example.md")

    assert path == root / REFERENCED_BY_LINKS_DIR / "202608" / "example.md.json"
    assert referenced_by_index_relpath("202608/example.md") == (
        "links/202608/example.md.json"
    )


def test_referenced_by_index_path_drops_provider_prefix() -> None:
    root = Path("/tmp/repo")
    path = referenced_by_index_path(root, "research:202608/report/report.md")
    relative = path.relative_to(root)

    assert path == root / "links" / "202608" / "report" / "report.md.json"
    assert ".sase" not in relative.parts
    assert "referenced-by" not in relative.parts
    assert "research" not in relative.parts


@pytest.mark.parametrize(
    "artifact_id",
    ("", "plan", "plan:", ":foo.md", "plan:/abs.md", "plan:../x.md"),
)
def test_referenced_by_index_path_rejects_invalid_ids(artifact_id: str) -> None:
    with pytest.raises(ValueError):
        referenced_by_index_path(Path("/tmp"), artifact_id)


def test_document_has_referenced_by_block_ignores_fenced_examples() -> None:
    assert document_has_referenced_by_block(_REAL_BLOCK)
    assert not document_has_referenced_by_block(_FENCED_EXAMPLE)
    assert not document_has_referenced_by_block("# No block\n")
