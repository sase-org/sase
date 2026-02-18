"""Tests for branch_names module - random adjective-noun branch name generation."""

from unittest.mock import MagicMock, patch

from sase.branch_names import (
    _ADJECTIVES,
    _NOUNS,
    _add_numeric_suffix,
    _get_existing_branch_names,
    generate_branch_name,
)


# --- Tests for _get_existing_branch_names ---


@patch("sase.branch_names.subprocess.run")
def test_get_existing_strips_remotes_origin_prefix(mock_run: MagicMock) -> None:
    """Test that remotes/origin/ prefix is stripped from remote branches."""
    mock_run.return_value = MagicMock(
        stdout="  remotes/origin/bold-fern\n  remotes/origin/calm-lake\n"
    )
    result = _get_existing_branch_names("/fake/dir")
    assert "bold-fern" in result
    assert "calm-lake" in result
    assert "remotes/origin/bold-fern" not in result


@patch("sase.branch_names.subprocess.run")
def test_get_existing_skips_head_lines(mock_run: MagicMock) -> None:
    """Test that lines containing HEAD -> are skipped."""
    mock_run.return_value = MagicMock(
        stdout="  remotes/origin/HEAD -> origin/main\n  main\n"
    )
    result = _get_existing_branch_names("/fake/dir")
    assert "main" in result
    assert len(result) == 1


@patch("sase.branch_names.subprocess.run")
def test_get_existing_strips_current_branch_marker(mock_run: MagicMock) -> None:
    """Test that leading '* ' is stripped from the current branch."""
    mock_run.return_value = MagicMock(stdout="* my-feature\n  main\n")
    result = _get_existing_branch_names("/fake/dir")
    assert "my-feature" in result
    assert "main" in result
    assert "* my-feature" not in result


@patch("sase.branch_names.subprocess.run")
def test_get_existing_handles_normal_listing(mock_run: MagicMock) -> None:
    """Test normal branch listing with mixed local and remote branches."""
    mock_run.return_value = MagicMock(
        stdout=(
            "* main\n"
            "  feature-a\n"
            "  feature-b\n"
            "  remotes/origin/main\n"
            "  remotes/origin/feature-a\n"
            "  remotes/origin/HEAD -> origin/main\n"
        )
    )
    result = _get_existing_branch_names("/fake/dir")
    assert result == {"main", "feature-a", "feature-b"}


# --- Tests for _add_numeric_suffix ---


def test_add_numeric_suffix_returns_base_2_when_base_taken() -> None:
    """Test that -2 suffix is returned when base name is taken."""
    existing = {"bold-fern"}
    result = _add_numeric_suffix("bold-fern", existing)
    assert result == "bold-fern-2"


def test_add_numeric_suffix_returns_base_3_when_base_and_2_taken() -> None:
    """Test that -3 suffix is returned when base and -2 are both taken."""
    existing = {"bold-fern", "bold-fern-2"}
    result = _add_numeric_suffix("bold-fern", existing)
    assert result == "bold-fern-3"


# --- Tests for generate_branch_name ---


@patch("sase.branch_names._get_existing_branch_names")
@patch("sase.branch_names.random.choice")
def test_generate_returns_unused_name(
    mock_choice: MagicMock, mock_existing: MagicMock
) -> None:
    """Test that generate_branch_name returns an unused adjective-noun name."""
    mock_existing.return_value = {"main", "other-branch"}
    mock_choice.side_effect = ["bold", "fern"]
    result = generate_branch_name("/fake/dir")
    assert result == "bold-fern"


@patch("sase.branch_names._get_existing_branch_names")
@patch("sase.branch_names.random.choice")
def test_generate_falls_back_to_numeric_suffix(
    mock_choice: MagicMock, mock_existing: MagicMock
) -> None:
    """Test fallback to numeric suffix after 10 collisions."""
    mock_existing.return_value = {"bold-fern"}
    # Return the same colliding pair for all 10 attempts (20 calls total)
    mock_choice.side_effect = ["bold", "fern"] * 10
    result = generate_branch_name("/fake/dir")
    assert result == "bold-fern-2"


# --- Tests for word list validation ---


def test_adjectives_count() -> None:
    """Test that there are exactly 80 adjectives."""
    assert len(_ADJECTIVES) == 80


def test_nouns_count() -> None:
    """Test that there are exactly 80 nouns."""
    assert len(_NOUNS) == 80


def test_adjectives_length_range() -> None:
    """Test that all adjectives are 3-7 characters long."""
    for word in _ADJECTIVES:
        assert 3 <= len(word) <= 7, f"Adjective {word!r} has length {len(word)}"


def test_nouns_length_range() -> None:
    """Test that all nouns are 3-7 characters long."""
    for word in _NOUNS:
        assert 3 <= len(word) <= 7, f"Noun {word!r} has length {len(word)}"


def test_adjectives_distinct() -> None:
    """Test that all adjectives are distinct."""
    assert len(set(_ADJECTIVES)) == len(_ADJECTIVES)


def test_nouns_distinct() -> None:
    """Test that all nouns are distinct."""
    assert len(set(_NOUNS)) == len(_NOUNS)


def test_adjectives_lowercase_alpha() -> None:
    """Test that all adjectives are lowercase alpha only."""
    for word in _ADJECTIVES:
        assert word.isalpha(), f"Adjective {word!r} is not alpha"
        assert word.islower(), f"Adjective {word!r} is not lowercase"


def test_nouns_lowercase_alpha() -> None:
    """Test that all nouns are lowercase alpha only."""
    for word in _NOUNS:
        assert word.isalpha(), f"Noun {word!r} is not alpha"
        assert word.islower(), f"Noun {word!r} is not lowercase"
