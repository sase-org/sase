from __future__ import annotations

from sase.xprompt.catalog import _compute_stats, _format_inputs, _truncate_content
from sase.xprompt.models import UNSET, InputArg, InputType

from tests._xprompt_catalog_helpers import seed_entries


def test_compute_stats_basic() -> None:
    entries = seed_entries()
    stats = _compute_stats(entries)

    assert stats.total == 3
    assert stats.by_source["built-in"] == 1
    assert stats.by_source["project"] == 1
    assert stats.by_source["config"] == 1
    assert stats.by_project == {"alpha": 1}
    assert stats.by_tag == {"vcs": 2, "commit": 1}
    assert stats.with_description == 1
    assert stats.with_inputs == 1
    assert stats.skills == 1
    assert stats.memory == 1


def test_truncate_content_short() -> None:
    result = _truncate_content("a\nb\nc")
    assert result["text"] == "a\nb\nc"
    assert result["elided"] is None


def test_truncate_content_long() -> None:
    body = "\n".join(f"line{i}" for i in range(100))
    result = _truncate_content(body, source_path="/foo.md")
    assert result["text"].count("\n") == 39
    assert "more lines" in result["elided"]
    assert "/foo.md" in result["elided"]


def test_format_inputs_required_optional() -> None:
    inputs = [
        InputArg(name="p", type=InputType.PATH, default=UNSET),
        InputArg(name="n", type=InputType.LINE, default="hi"),
    ]
    assert _format_inputs(inputs) == "(p: path, n?: line)"


def test_format_inputs_empty() -> None:
    assert _format_inputs([]) == ""
