from __future__ import annotations

from pathlib import Path

from sase.xprompt.config_yaml import insert_xprompt_into_config


_PACKED_SORTED_CONFIG = (
    "xprompts:\n"
    "  # keep-sorted start\n"
    "\n"
    "  prompt/review: |\n"
    "    Prompt review\n"
    "  research/image: |\n"
    "    Image\n"
    "  research/more: |\n"
    "    More\n"
    "  research/prompt:\n"
    "    input:\n"
    "      prompt: text\n"
    "    content: |\n"
    "      Prompt\n"
    "\n"
    "      {{ prompt }}\n"
    "  research: |\n"
    "    Research\n"
    "  review: |\n"
    "    Review\n"
    "  # keep-sorted end\n"
)


def _insert(
    tmp_path: Path,
    initial_text: str,
    name: str,
    content: str,
) -> str:
    config = tmp_path / "sase.yml"
    config.write_text(initial_text, encoding="utf-8")
    assert insert_xprompt_into_config(str(config), name, [], content) is True
    return config.read_text(encoding="utf-8")


def test_packed_sorted_insert_preserves_comments_and_adds_no_blank_lines(
    tmp_path: Path,
) -> None:
    text = _insert(tmp_path, _PACKED_SORTED_CONFIG, "research/zzz", "Zzz")

    expected = _PACKED_SORTED_CONFIG.replace(
        "  research: |\n",
        "  research/zzz: |\n    Zzz\n  research: |\n",
    )
    assert text == expected
    assert text.count("\n\n") == _PACKED_SORTED_CONFIG.count("\n\n")
    assert "  # keep-sorted start\n\n  prompt/review:" in text
    assert "  review: |\n    Review\n  # keep-sorted end\n" in text


def test_sorted_insert_uses_colon_tiebreak_for_bare_name(tmp_path: Path) -> None:
    text = _insert(tmp_path, _PACKED_SORTED_CONFIG, "researchz", "Research z")

    expected = _PACKED_SORTED_CONFIG.replace(
        "  review: |\n",
        "  researchz: |\n    Research z\n  review: |\n",
    )
    assert text == expected


def test_unsorted_section_appends_new_entry_without_reordering(tmp_path: Path) -> None:
    initial = "xprompts:\n  charlie: |\n    C\n\n  alpha: |\n    A\n"

    text = _insert(tmp_path, initial, "bravo", "B")

    assert text == (
        "xprompts:\n  charlie: |\n    C\n\n  alpha: |\n    A\n\n  bravo: |\n    B\n"
    )


def test_overwrite_replaces_only_matching_block(tmp_path: Path) -> None:
    text = _insert(tmp_path, _PACKED_SORTED_CONFIG, "research/more", "Updated")

    expected = _PACKED_SORTED_CONFIG.replace(
        "  research/more: |\n    More\n",
        "  research/more: |\n    Updated\n",
    )
    assert text == expected


def test_one_blank_spacing_is_mirrored_for_first_middle_and_last_inserts(
    tmp_path: Path,
) -> None:
    initial = "xprompts:\n  alpha: |\n    A\n\n  charlie: |\n    C\n"

    first = _insert(tmp_path, initial, "aardvark", "AA")
    assert first == (
        "xprompts:\n  aardvark: |\n    AA\n\n  alpha: |\n    A\n\n  charlie: |\n    C\n"
    )

    middle = _insert(tmp_path, initial, "bravo", "B")
    assert middle == (
        "xprompts:\n  alpha: |\n    A\n\n  bravo: |\n    B\n\n  charlie: |\n    C\n"
    )

    last = _insert(tmp_path, initial, "zulu", "Z")
    assert last == (
        "xprompts:\n  alpha: |\n    A\n\n  charlie: |\n    C\n\n  zulu: |\n    Z\n"
    )


def test_empty_and_missing_section_fallbacks_insert_without_stray_blanks(
    tmp_path: Path,
) -> None:
    cases = [
        ("xprompts: {}\n", "xprompts:\n  foo: |\n    Foo\n"),
        ("xprompts:\n", "xprompts:\n  foo: |\n    Foo\n"),
        ("", "xprompts:\n  foo: |\n    Foo\n"),
        ("other_key: value\n", "other_key: value\n\nxprompts:\n  foo: |\n    Foo\n"),
    ]

    for index, (initial, expected) in enumerate(cases):
        config = tmp_path / f"sase-{index}.yml"
        config.write_text(initial, encoding="utf-8")

        assert insert_xprompt_into_config(str(config), "foo", [], "Foo") is True

        assert config.read_text(encoding="utf-8") == expected
