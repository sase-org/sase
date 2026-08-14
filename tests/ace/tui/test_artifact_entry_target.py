"""Unit coverage for the typed ``ArtifactEntryTarget`` identity."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget


def test_equal_targets_hash_and_compare_equal() -> None:
    a = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-1"))
    b = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-1"))
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_different_pane_id_never_collides_with_same_parts() -> None:
    beads = ArtifactEntryTarget(pane_id="beads", parts=("alpha", "1"))
    files = ArtifactEntryTarget(pane_id="files", parts=("alpha", "1"))
    assert beads != files
    assert hash(beads) != hash(files)


def test_to_token_round_trips_through_from_token() -> None:
    target = ArtifactEntryTarget(
        pane_id="ref:plan", parts=("alpha", "proposal", "notice-1")
    )
    token = target.to_token()
    assert ArtifactEntryTarget.from_token(token) == target


@pytest.mark.parametrize(
    "parts",
    [
        (),
        ("simple",),
        ("with spaces", "and:colons"),
        ("unicode-café", "emoji-🎯", 'quote"s'),
    ],
)
def test_to_token_round_trips_with_arbitrary_content(parts: tuple[str, ...]) -> None:
    target = ArtifactEntryTarget(pane_id="stitches", parts=parts)
    assert ArtifactEntryTarget.from_token(target.to_token()) == target


def test_to_token_output_is_deterministic() -> None:
    target = ArtifactEntryTarget(pane_id="patches", parts=("proj", "name"))
    assert target.to_token() == target.to_token()
    assert (
        ArtifactEntryTarget(pane_id="patches", parts=("proj", "name")).to_token()
        == target.to_token()
    )


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-versioned",
        "v1",
        "v1\x1f",
        "v2\x1fbeads\x1falpha",
        "\x1fbeads\x1falpha",
    ],
)
def test_from_token_rejects_malformed_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        ArtifactEntryTarget.from_token(token)


def test_construction_rejects_empty_pane_id() -> None:
    with pytest.raises(ValueError):
        ArtifactEntryTarget(pane_id="", parts=("a",))


def test_construction_rejects_non_string_parts() -> None:
    with pytest.raises(TypeError):
        ArtifactEntryTarget(pane_id="beads", parts=(1,))  # type: ignore[arg-type]


def test_construction_rejects_delimiter_in_pane_id_or_parts() -> None:
    with pytest.raises(ValueError):
        ArtifactEntryTarget(pane_id="beads\x1f", parts=())
    with pytest.raises(ValueError):
        ArtifactEntryTarget(pane_id="beads", parts=("a\x1fb",))


@pytest.mark.parametrize(
    ("legacy", "expected_pane_id", "expected_parts"),
    [
        (("commit", "sase", "a" * 40), "stitches", ("sase", "a" * 40)),
        (("bead", "alpha", "task", "alpha-1"), "beads", ("alpha", "task", "alpha-1")),
        (("file", "logical-1"), "files", ("logical-1",)),
        (("patch", "proj", "name"), "patches", ("proj", "name")),
        (("plan", "alpha", "proposal", "n1"), "ref:plan", ("alpha", "proposal", "n1")),
        (("research", "alpha", "doc"), "ref:research", ("alpha", "doc")),
    ],
)
def test_from_legacy_maps_known_and_document_kinds(
    legacy: tuple[str, ...],
    expected_pane_id: str,
    expected_parts: tuple[str, ...],
) -> None:
    target = ArtifactEntryTarget.from_legacy(legacy)
    assert target.pane_id == expected_pane_id
    assert target.parts == expected_parts


def test_from_legacy_rejects_empty_tuple() -> None:
    with pytest.raises(ValueError):
        ArtifactEntryTarget.from_legacy(())


def test_targets_are_frozen() -> None:
    target = ArtifactEntryTarget(pane_id="beads", parts=("alpha",))
    with pytest.raises(AttributeError):
        target.pane_id = "files"  # type: ignore[misc]
