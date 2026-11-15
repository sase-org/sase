"""Canonical artifact keys retain realpath semantics with shared parent work."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import _artifact_state as artifact_state


@pytest.fixture(autouse=True)
def _clear_path_caches() -> Iterator[None]:
    artifact_state.artifact_dir_key.cache_clear()
    artifact_state._resolved_parent_dir.cache_clear()
    yield
    artifact_state.artifact_dir_key.cache_clear()
    artifact_state._resolved_parent_dir.cache_clear()


@pytest.mark.parametrize(
    "shape",
    [
        "plain",
        "missing",
        "symlink_leaf",
        "symlink_parent",
        "relative",
        "home",
        "trailing_slash",
        "parent_segment",
        "double_slash_prefix",
        "double_separator",
        "dot_segment",
        "root",
    ],
)
def test_artifact_key_matches_path_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    leaf = parent / "leaf"
    leaf.mkdir()
    (tmp_path / "leaf_link").symlink_to(leaf, target_is_directory=True)
    (tmp_path / "parent_link").symlink_to(parent, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    value = {
        "plain": str(leaf),
        "missing": str(parent / "missing"),
        "symlink_leaf": str(tmp_path / "leaf_link"),
        "symlink_parent": str(tmp_path / "parent_link" / "leaf"),
        "relative": "parent/leaf",
        "home": "~/parent/leaf",
        "trailing_slash": f"{leaf}/",
        "parent_segment": f"{leaf}/../leaf",
        "double_slash_prefix": f"/{leaf}",
        "double_separator": f"{parent}//leaf",
        "dot_segment": f"{parent}/./leaf",
        "root": "/",
    }[shape]

    assert artifact_state.artifact_dir_key(value) == str(
        Path(value).expanduser().resolve(strict=False)
    )


def test_distinct_leaves_resolve_one_parent(tmp_path: Path) -> None:
    for index in range(20):
        leaf = tmp_path / f"leaf-{index}"
        if index % 2:
            leaf.mkdir()
        assert artifact_state.artifact_dir_key(str(leaf)) == str(
            leaf.resolve(strict=False)
        )

    assert artifact_state._resolved_parent_dir.cache_info().misses == 1
    assert artifact_state.artifact_dir_key.cache_info().misses == 20
