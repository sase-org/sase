"""Docs must restate the values shipped in ``model_alias_defaults.yml``.

The YAML file is the single edit point for shipped model-alias defaults,
but ``docs/llms.md`` and ``docs/configuration.md`` restate the same target
strings for human readers. A changed YAML target without a matching doc
update fails here, naming the exact file and value to fix.
"""

from __future__ import annotations

from pathlib import Path

from sase.llm_provider.model_alias_policy import implicit_alias_targets

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATHS = (
    _REPO_ROOT / "docs" / "llms.md",
    _REPO_ROOT / "docs" / "configuration.md",
)


def test_every_shipped_target_is_quoted_in_both_docs() -> None:
    """Each target must appear verbatim or markdown-table-escaped in each doc.

    Docs quote defaults both inside plain YAML code blocks (unescaped) and
    inside markdown table cells, where a literal ``|`` must be escaped to
    ``\\|`` so it does not break the table.
    """
    for doc_path in _DOC_PATHS:
        text = doc_path.read_text(encoding="utf-8")
        for name, target in implicit_alias_targets().items():
            escaped = target.replace("|", "\\|")
            assert target in text or escaped in text, (
                f"{doc_path.relative_to(_REPO_ROOT)} is missing the current "
                f"'{name}' default ({target!r}); update it to match "
                "src/sase/llm_provider/model_alias_defaults.yml"
            )
