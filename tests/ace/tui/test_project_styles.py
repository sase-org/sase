"""Determinism, distinctness, and degrade behavior of project accent colors."""

from __future__ import annotations

from sase.ace.tui.project_styles import (
    PROJECT_ACCENTS,
    _hash_index,
    _project_accent_map,
    project_accent,
)

_CORPUS: tuple[str, ...] = tuple(f"project-{i}" for i in range(200))


def _find_n_with_natural_collision() -> int:
    """First corpus prefix length whose keys collide before probing."""

    for n in range(2, len(_CORPUS) + 1):
        keys = sorted(_CORPUS[:n])
        indices = [_hash_index(key, len(PROJECT_ACCENTS)) for key in keys]
        if len(set(indices)) != len(indices) and n <= len(PROJECT_ACCENTS):
            return n
    raise AssertionError("corpus never produces a natural hash collision")


def test_assignment_is_deterministic_across_calls() -> None:
    keys = _CORPUS[:5]
    assert _project_accent_map(keys) == _project_accent_map(keys)


def test_assignment_is_independent_of_input_order() -> None:
    keys = list(_CORPUS[:6])
    forward = _project_accent_map(keys)
    backward = _project_accent_map(list(reversed(keys)))
    assert forward == backward


def test_all_distinct_up_to_palette_length_including_a_natural_collision() -> None:
    collision_n = _find_n_with_natural_collision()
    for n in (1, 2, len(PROJECT_ACCENTS) // 2, collision_n, len(PROJECT_ACCENTS)):
        keys = _CORPUS[:n]
        mapping = _project_accent_map(keys)
        assert len(set(mapping.values())) == n


def test_adding_a_later_sorting_key_never_moves_an_earlier_ones_color() -> None:
    keys = sorted(_CORPUS[:8])
    before = _project_accent_map(keys[:-1])
    after = _project_accent_map(keys)
    for key in keys[:-1]:
        assert before[key] == after[key]


def test_more_keys_than_palette_degrades_to_repeats_not_an_error() -> None:
    keys = _CORPUS[: len(PROJECT_ACCENTS) + 5]
    mapping = _project_accent_map(keys)
    assert len(mapping) == len(keys)
    assert len(set(mapping.values())) < len(keys)


def test_project_accent_without_among_matches_hash_only_lookup() -> None:
    key = "gh_sase-org__sase"
    assert (
        project_accent(key) == PROJECT_ACCENTS[_hash_index(key, len(PROJECT_ACCENTS))]
    )


def test_project_accent_with_among_matches_the_map() -> None:
    keys = _CORPUS[:5]
    mapping = _project_accent_map(keys)
    for key in keys:
        assert project_accent(key, among=keys) == mapping[key]
