"""Store-level tests for sase.history.vcs_xprompt_mru.

Covers where the MRU file lives plus the raw load/record semantics that need
no project-launchability or display-name resolution.
"""

import json
from pathlib import Path

import pytest

from sase.history.vcs_xprompt_mru import (
    _MAX_ENTRIES,
    _load_vcs_xprompt_mru,
    load_launchable_vcs_xprompt_mru,
    record_vcs_xprompt_usage,
    vcs_xprompt_mru_path,
)
from tests._vcs_xprompt_mru_helpers import patched_mru_file
from tests.conftest import redirect_sase_home


def test_vcs_xprompt_mru_path_follows_sase_home() -> None:
    from sase.core.paths import sase_home

    assert vcs_xprompt_mru_path() == sase_home() / "vcs_xprompt_mru.json"


def test_vcs_xprompt_mru_path_honors_mru_file_hook(tmp_path: Path) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    with patched_mru_file(fake):
        assert vcs_xprompt_mru_path() == fake
        assert _load_vcs_xprompt_mru() == []


def test_load_empty_when_file_missing(tmp_path: Path) -> None:
    """Returns empty list when MRU file doesn't exist."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    with patched_mru_file(fake):
        assert _load_vcs_xprompt_mru() == []


def test_load_returns_entries(tmp_path: Path) -> None:
    """Loads entries from a valid JSON file."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", "#gh:other"]}))
    with patched_mru_file(fake):
        assert _load_vcs_xprompt_mru() == ["#gh:sase", "#gh:other"]


def test_load_filters_non_strings(tmp_path: Path) -> None:
    """Non-string entries are filtered out."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase", 42, None, "#gh:b"]}))
    with patched_mru_file(fake):
        assert _load_vcs_xprompt_mru() == ["#gh:sase", "#gh:b"]


def test_load_caps_at_max(tmp_path: Path) -> None:
    """Only first _MAX_ENTRIES are returned."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    entries = [f"#gh:proj{i}" for i in range(_MAX_ENTRIES + 5)]
    fake.write_text(json.dumps({"entries": entries}))
    with patched_mru_file(fake):
        result = _load_vcs_xprompt_mru()
        assert len(result) == _MAX_ENTRIES


def test_load_handles_corrupt_json(tmp_path: Path) -> None:
    """Returns empty list for corrupt JSON."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text("not json")
    with patched_mru_file(fake):
        assert _load_vcs_xprompt_mru() == []


def test_record_adds_new_prefix(tmp_path: Path) -> None:
    """New prefix is added to front of list."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:old"]}))
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:new")
        result = _load_vcs_xprompt_mru()
        assert result == ["#gh:new", "#gh:old"]


def test_record_moves_existing_to_front(tmp_path: Path) -> None:
    """Existing prefix is moved to front (not duplicated)."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:a", "#gh:b", "#gh:c"]}))
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:c")
        result = _load_vcs_xprompt_mru()
        assert result == ["#gh:c", "#gh:a", "#gh:b"]


def test_record_moves_existing_prefix_to_launchable_mru_front(tmp_path: Path) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:a", "#gh:b", "#gh:c"]}))
    projects_dir = tmp_path / "projects"

    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:c")
        result = load_launchable_vcs_xprompt_mru(projects_dir)

    assert result[0] == "#gh:c"
    assert result == ["#gh:c", "#gh:a", "#gh:b"]


def test_record_caps_at_max(tmp_path: Path) -> None:
    """List is capped at _MAX_ENTRIES after recording."""
    fake = tmp_path / "vcs_xprompt_mru.json"
    entries = [f"#gh:proj{i}" for i in range(_MAX_ENTRIES)]
    fake.write_text(json.dumps({"entries": entries}))
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:brand_new")
        result = _load_vcs_xprompt_mru()
        assert len(result) == _MAX_ENTRIES
        assert result[0] == "#gh:brand_new"
        # Last entry was evicted
        assert f"#gh:proj{_MAX_ENTRIES - 1}" not in result


def test_record_creates_file_if_missing(tmp_path: Path) -> None:
    """Creates the MRU file (and parent dirs) when it doesn't exist."""
    fake = tmp_path / "subdir" / "vcs_xprompt_mru.json"
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:first")
        assert fake.exists()
        result = _load_vcs_xprompt_mru()
        assert result == ["#gh:first"]


def test_record_uses_redirected_sase_home_without_mru_file_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default MRU writes follow the suite's ``~/.sase`` redirection."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / "sase_home")
    isolated_mru = sase_home / "vcs_xprompt_mru.json"
    real_home_mru = Path.home() / ".sase" / "vcs_xprompt_mru.json"

    record_vcs_xprompt_usage("#gh:first")

    assert isolated_mru.exists()
    assert _load_vcs_xprompt_mru() == ["#gh:first"]
    assert isolated_mru != real_home_mru


def test_record_then_record_moves_mru_head_to_most_recently_recorded(
    tmp_path: Path,
) -> None:
    """Recording ref A then ref B leaves B at the MRU head, not A.

    Regression test for the headline ``<ctrl+space>`` defect, reduced to its
    store effect: whichever ref is recorded *last* is what every reader
    (``<ctrl+p>``, ``<ctrl+g>``, ``<ctrl+space>``) sees first.
    """
    fake = tmp_path / "vcs_xprompt_mru.json"
    with patched_mru_file(fake):
        record_vcs_xprompt_usage("#gh:projA")
        record_vcs_xprompt_usage("#gh:projB")
        result = _load_vcs_xprompt_mru()

    assert result[0] == "#gh:projB"
    assert result == ["#gh:projB", "#gh:projA"]
