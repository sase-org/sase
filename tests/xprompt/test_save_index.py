"""Names-only indexing and lazy save-preview loading."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.save_index import (
    load_definition,
    names_for_location,
)


def test_directory_index_reads_names_only_and_invalidates_on_mtime(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    (directory / "alpha.md").write_text("alpha body", encoding="utf-8")
    assert names_for_location("directory", str(directory)) == {"alpha"}

    (directory / "beta.md").write_text("beta body", encoding="utf-8")
    os.utime(directory, None)
    assert names_for_location("directory", str(directory)) == {"alpha", "beta"}


def test_directory_index_never_reads_definition_bodies(tmp_path: Path) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    (directory / "large.md").write_text("full body", encoding="utf-8")
    with patch.object(
        Path,
        "read_text",
        side_effect=AssertionError("definition content must stay lazy"),
    ):
        assert names_for_location("directory", str(directory)) == {"large"}


def test_config_index_loads_keys_without_reconstructing_definitions(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "xprompts:\n  alpha: one\n  beta: two\nace:\n  snippets:\n    trig: body\n",
        encoding="utf-8",
    )
    with patch(
        "sase.xprompt.save_index.load_config_xprompt_markdown",
        side_effect=AssertionError("definition reconstruction must stay lazy"),
    ):
        assert names_for_location("xprompt_config", str(config)) == {"alpha", "beta"}
        assert names_for_location("snippet_config", str(config)) == {"trig"}


def test_definition_text_is_loaded_lazily_and_invalidated(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    path.write_text("old", encoding="utf-8")
    assert load_definition("markdown", str(path), "review") == "old"
    path.write_text("new content", encoding="utf-8")
    assert load_definition("markdown", str(path), "review") == "new content"
