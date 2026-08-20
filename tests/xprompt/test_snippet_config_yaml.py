from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

import pytest

from sase.xprompt.snippet_config_yaml import (
    SnippetConfigConflictError,
    apply_snippet_config_text,
    insert_snippet_into_config,
    parse_ace_snippets,
    preview_snippet_delete,
    preview_snippet_upsert,
    snippet_config_digest,
)


def _insert(
    tmp_path: Path,
    initial_text: str,
    name: str,
    template: str,
    *,
    file_exists: bool = True,
) -> str:
    config = tmp_path / "sase.yml"
    if file_exists:
        config.write_text(initial_text, encoding="utf-8")
    assert insert_snippet_into_config(str(config), name, template) is True
    return config.read_text(encoding="utf-8")


def _snippets(text: str) -> dict[str, str]:
    data = yaml.safe_load(text)
    return data["ace"]["snippets"]


def test_creates_ace_snippets_in_empty_file(tmp_path: Path) -> None:
    text = _insert(tmp_path, "", "foo", "hello $1 world$0")

    assert text == ("ace:\n  snippets:\n    foo: |-\n      hello $1 world$0\n")
    # ``|-`` strips the trailing newline, so the stripped template round-trips
    # exactly rather than gaining an implicit final newline.
    assert _snippets(text) == {"foo": "hello $1 world$0"}


def test_creates_ace_snippets_when_file_missing(tmp_path: Path) -> None:
    text = _insert(tmp_path, "", "foo", "body", file_exists=False)

    assert _snippets(text) == {"foo": "body"}


def test_multiline_template_round_trips_as_block_scalar(tmp_path: Path) -> None:
    template = "first line\n\nthird line$0"
    text = _insert(tmp_path, "", "multi", template)

    assert "    multi: |-\n      first line\n\n      third line$0\n" in text
    assert _snippets(text)["multi"] == "first line\n\nthird line$0"


def test_inserts_under_existing_ace_without_disturbing_siblings(
    tmp_path: Path,
) -> None:
    initial = 'ace:\n  # keep this comment\n  repro_output_dir: ""\n\nother_top: 1\n'

    text = _insert(tmp_path, initial, "foo", "body$0")

    assert text == (
        "ace:\n"
        "  # keep this comment\n"
        '  repro_output_dir: ""\n'
        "  snippets:\n"
        "    foo: |-\n"
        "      body$0\n"
        "\n"
        "other_top: 1\n"
    )


def test_inserts_into_existing_ace_snippets(tmp_path: Path) -> None:
    # The pre-existing ``alpha`` entry keeps its plain ``|`` header; only the
    # newly written ``bravo`` entry uses ``|-``.
    initial = "ace:\n  snippets:\n    alpha: |\n      A$0\n"

    text = _insert(tmp_path, initial, "bravo", "B$0")

    # Sorted section keeps sorted order.
    assert text == (
        "ace:\n  snippets:\n    alpha: |\n      A$0\n    bravo: |-\n      B$0\n"
    )


def test_creates_snippets_under_empty_ace_mapping(tmp_path: Path) -> None:
    initial = "ace: {}\n"

    text = _insert(tmp_path, initial, "foo", "body$0")

    assert text == ("ace:\n  snippets:\n    foo: |-\n      body$0\n")


def test_creates_entries_under_empty_snippets_mapping(tmp_path: Path) -> None:
    initial = "ace:\n  snippets: {}\n"

    text = _insert(tmp_path, initial, "foo", "body$0")

    assert text == ("ace:\n  snippets:\n    foo: |-\n      body$0\n")


def test_overwrite_replaces_only_matching_block(tmp_path: Path) -> None:
    initial = (
        "ace:\n"
        "  snippets:\n"
        "    # snippet comment\n"
        "    alpha: |\n"
        "      A$0\n"
        "    bravo: |\n"
        "      B$0\n"
        "    charlie: |\n"
        "      C$0\n"
    )

    text = _insert(tmp_path, initial, "bravo", "updated$0")

    # Only the overwritten ``bravo`` block is regenerated with ``|-``; the
    # untouched ``alpha`` / ``charlie`` siblings keep their ``|`` headers.
    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    # snippet comment\n"
        "    alpha: |\n"
        "      A$0\n"
        "    bravo: |-\n"
        "      updated$0\n"
        "    charlie: |\n"
        "      C$0\n"
    )


def test_unsorted_section_appends_without_reordering(tmp_path: Path) -> None:
    initial = (
        "ace:\n  snippets:\n    charlie: |\n      C$0\n\n    alpha: |\n      A$0\n"
    )

    text = _insert(tmp_path, initial, "bravo", "B$0")

    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    charlie: |\n"
        "      C$0\n"
        "\n"
        "    alpha: |\n"
        "      A$0\n"
        "\n"
        "    bravo: |-\n"
        "      B$0\n"
    )


def test_sorted_prefix_names_insert_between(tmp_path: Path) -> None:
    # ``foo`` then ``foo1`` is sorted by snippet name even though the old
    # ``name:`` sort key treated it as unsorted (``"foo1:"`` < ``"foo:"``).
    initial = "ace:\n  snippets:\n    foo: |\n      F$0\n    foo1: |\n      F1$0\n"

    text = _insert(tmp_path, initial, "foo0", "F0$0")

    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    foo: |\n"
        "      F$0\n"
        "    foo0: |-\n"
        "      F0$0\n"
        "    foo1: |\n"
        "      F1$0\n"
    )
    assert list(_snippets(text)) == ["foo", "foo0", "foo1"]


def test_sorted_mapping_inserts_before_first_entry(tmp_path: Path) -> None:
    initial = "ace:\n  snippets:\n    bravo: |\n      B$0\n\n    delta: |\n      D$0\n"

    text = _insert(tmp_path, initial, "alpha", "A$0")

    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    alpha: |-\n"
        "      A$0\n"
        "\n"
        "    bravo: |\n"
        "      B$0\n"
        "\n"
        "    delta: |\n"
        "      D$0\n"
    )


def test_sorted_mapping_appends_after_last_entry(tmp_path: Path) -> None:
    initial = "ace:\n  snippets:\n    bravo: |\n      B$0\n\n    delta: |\n      D$0\n"

    text = _insert(tmp_path, initial, "echo", "E$0")

    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    bravo: |\n"
        "      B$0\n"
        "\n"
        "    delta: |\n"
        "      D$0\n"
        "\n"
        "    echo: |-\n"
        "      E$0\n"
    )


def test_section_sorted_by_old_key_but_not_by_name_appends(
    tmp_path: Path,
) -> None:
    # ``foo1`` then ``foo`` is sorted under the retired ``name:`` key but not by
    # snippet name, so the section is treated as unsorted and the new entry is
    # appended without reordering.
    initial = "ace:\n  snippets:\n    foo1: |\n      F1$0\n    foo: |\n      F$0\n"

    text = _insert(tmp_path, initial, "foo0", "F0$0")

    assert text == (
        "ace:\n"
        "  snippets:\n"
        "    foo1: |\n"
        "      F1$0\n"
        "    foo: |\n"
        "      F$0\n"
        "    foo0: |-\n"
        "      F0$0\n"
    )


def test_preserves_unrelated_comments_blank_lines_and_ordering(
    tmp_path: Path,
) -> None:
    initial = (
        "# top comment\n"
        "use_chezmoi: false\n"
        "\n"
        "ace:\n"
        "  snippets:\n"
        "    # keep-sorted start\n"
        "    alpha: |\n"
        "      A$0\n"
        "    gamma: |\n"
        "      G$0\n"
        "    # keep-sorted end\n"
        "\n"
        "xprompts:\n"
        "  foo: bar\n"
    )

    text = _insert(tmp_path, initial, "beta", "B$0")

    assert text == (
        "# top comment\n"
        "use_chezmoi: false\n"
        "\n"
        "ace:\n"
        "  snippets:\n"
        "    # keep-sorted start\n"
        "    alpha: |\n"
        "      A$0\n"
        "    beta: |-\n"
        "      B$0\n"
        "    gamma: |\n"
        "      G$0\n"
        "    # keep-sorted end\n"
        "\n"
        "xprompts:\n"
        "  foo: bar\n"
    )


def test_existing_pipe_entry_preserved_while_new_entry_uses_strip_chomp(
    tmp_path: Path,
) -> None:
    # A pre-existing ``|`` entry keeps its plain-literal header and its
    # round-tripped trailing newline; only the freshly written entry uses
    # ``|-`` and loads without an implicit final newline.
    initial = "ace:\n  snippets:\n    legacy: |\n      L$0\n"

    text = _insert(tmp_path, initial, "fresh", "F$0")

    assert "    legacy: |\n" in text
    assert "    fresh: |-\n" in text
    snippets = _snippets(text)
    assert snippets["legacy"] == "L$0\n"
    assert snippets["fresh"] == "F$0"


def test_preview_delete_removes_only_named_entry(tmp_path: Path) -> None:
    initial = (
        "ace:\n"
        "  snippets:\n"
        "    alpha: |\n"
        "      A$0\n"
        "    bravo: |\n"
        "      B$0\n"
        "    charlie: |\n"
        "      C$0\n"
    )

    text = preview_snippet_delete(initial, "bravo")

    assert parse_ace_snippets(text) == {"alpha": "A$0\n", "charlie": "C$0\n"}
    assert "bravo" not in text
    assert "alpha: |" in text
    assert "charlie: |" in text


def test_preview_delete_unknown_trigger_raises() -> None:
    with pytest.raises(KeyError, match="missing"):
        preview_snippet_delete(
            "ace:\n  snippets:\n    alpha: |\n      A$0\n", "missing"
        )


def test_apply_raises_conflict_on_stale_digest(tmp_path: Path) -> None:
    path = tmp_path / "sase.yml"
    original = "ace:\n  snippets: {}\n"
    path.write_text(original, encoding="utf-8")
    new_text = preview_snippet_upsert(original, "foo", "body$0")
    path.write_text("changed: true\n", encoding="utf-8")

    with pytest.raises(SnippetConfigConflictError, match="reload and retry"):
        apply_snippet_config_text(
            path,
            new_text,
            expected_digest=snippet_config_digest(original.encode()),
        )

    assert path.read_text(encoding="utf-8") == "changed: true\n"


def test_apply_is_atomic_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sase.yml"
    original = "ace:\n  snippets: {}\n"
    path.write_text(original, encoding="utf-8")
    new_text = preview_snippet_upsert(original, "foo", "body$0")

    def boom(*_a, **_k):
        raise OSError("replace failed")

    monkeypatch.setattr("sase.xprompt.snippet_config_yaml.os.replace", boom)

    with pytest.raises(OSError, match="replace failed"):
        apply_snippet_config_text(path, new_text, expected_bytes=original.encode())

    assert path.read_text(encoding="utf-8") == original
    leftovers = list(tmp_path.glob(".sase.yml.*.tmp"))
    assert leftovers == []
