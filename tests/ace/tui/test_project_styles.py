"""Determinism, distinctness, and degrade behavior of project accent colors."""

from __future__ import annotations

from sase.ace.tui.project_styles import (
    PROJECT_ACCENTS,
    _hash_index,
    _project_accent_map,
    project_accent,
    project_chip_plate,
)

_CORPUS: tuple[str, ...] = tuple(f"project-{i}" for i in range(200))

# The reference surfaces the chip plate must read well against: the pinned
# flexoki background/surface plus the stock Textual dark/light theme pairs
# (see ``tests/ace/tui/test_artifacts_provider_palette.py`` for the same
# WCAG helper shape used against the provider accent palette).
_REFERENCE_SURFACES: tuple[str, ...] = (
    "#100F0F",
    "#121212",
    "#1E1E1E",
    "#E0E0E0",
    "#D8D8D8",
)

_MIN_PLATE_STEP = 1.05
_MAX_PLATE_STEP = 1.25
_MIN_LEGIBILITY_RETENTION = 0.85
_MIN_DARK_FLOOR = 3.3
_DARK_FLOOR_SURFACES = ("#100F0F", "#121212", "#1E1E1E")


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    stripped = value.lstrip("#")
    return tuple(int(stripped[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a) + 0.05
    lb = _relative_luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


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


def test_project_chip_plate_is_deterministic() -> None:
    for accent in PROJECT_ACCENTS:
        for background in _REFERENCE_SURFACES:
            assert project_chip_plate(
                accent, background=background
            ) == project_chip_plate(accent, background=background)


def test_project_chip_plate_is_distinct_per_accent() -> None:
    for background in _REFERENCE_SURFACES:
        plates = {
            project_chip_plate(accent, background=background)
            for accent in PROJECT_ACCENTS
        }
        assert len(plates) == len(PROJECT_ACCENTS)


def test_project_chip_plate_never_returns_the_background_unchanged() -> None:
    for accent in PROJECT_ACCENTS:
        for background in _REFERENCE_SURFACES:
            assert project_chip_plate(accent, background=background) != background


def test_project_chip_plate_is_one_surface_step_above_background() -> None:
    for accent in PROJECT_ACCENTS:
        for background in _REFERENCE_SURFACES:
            plate = project_chip_plate(accent, background=background)
            step = _contrast_ratio(plate, background)
            assert _MIN_PLATE_STEP <= step <= _MAX_PLATE_STEP, (
                accent,
                background,
                step,
            )


def test_project_chip_plate_retains_most_of_the_accents_legibility() -> None:
    for accent in PROJECT_ACCENTS:
        for background in _REFERENCE_SURFACES:
            plate = project_chip_plate(accent, background=background)
            baseline = _contrast_ratio(accent, background)
            retained = _contrast_ratio(accent, plate)
            assert retained >= _MIN_LEGIBILITY_RETENTION * baseline, (
                accent,
                background,
                retained,
                baseline,
            )


def test_project_chip_plate_clears_the_dark_floor() -> None:
    for accent in PROJECT_ACCENTS:
        for background in _DARK_FLOOR_SURFACES:
            plate = project_chip_plate(accent, background=background)
            assert _contrast_ratio(accent, plate) >= _MIN_DARK_FLOOR, (
                accent,
                background,
            )
