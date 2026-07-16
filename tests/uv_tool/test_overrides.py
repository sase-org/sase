from __future__ import annotations

from pathlib import Path

from sase.uv_tool.overrides import (
    editable_override_lines,
    write_editable_overrides,
)
from sase.uv_tool.receipt import Requirement


def test_editable_override_lines_filters_dedupes_and_preserves_order() -> None:
    assert editable_override_lines(
        (
            Requirement(name="sase-telegram"),
            Requirement(name="Sase_GitHub", editable="/src/github-a"),
            Requirement(name="sase", editable="/src/sase"),
            Requirement(name="sase-github", editable="/src/github-b"),
        )
    ) == ("-e /src/github-a", "-e /src/sase", "sase-core-rs")


def test_editable_override_lines_lift_core_window_only_for_editable_host() -> None:
    plugins_only = editable_override_lines(
        (
            Requirement(name="sase"),
            Requirement(name="sase-github", editable="/src/github"),
        )
    )
    dev_host = editable_override_lines(
        (Requirement(name="sase", editable="/src/sase"),)
    )

    assert plugins_only == ("-e /src/github",)
    assert dev_host == ("-e /src/sase", "sase-core-rs")


def test_write_editable_overrides_returns_none_for_no_editables(
    tmp_path: Path,
) -> None:
    path = tmp_path / "overrides.txt"

    assert write_editable_overrides((Requirement(name="sase"),), path=path) is None
    assert not path.exists()


def test_write_editable_overrides_writes_and_rewrites_file(tmp_path: Path) -> None:
    path = tmp_path / "overrides.txt"

    first = write_editable_overrides(
        (Requirement(name="sase", editable="/src/sase"),),
        path=path,
    )
    second = write_editable_overrides(
        (Requirement(name="sase", editable="/other/sase"),),
        path=path,
    )

    assert first == path
    assert second == path
    assert path.read_text(encoding="utf-8") == "-e /other/sase\nsase-core-rs\n"


def test_write_editable_overrides_uses_stable_default_path() -> None:
    path = write_editable_overrides((Requirement(name="sase", editable="/src/sase"),))

    assert path is not None
    assert path.name == "editable-overrides.txt"
    assert path.parent.name == "uv"
    assert path.read_text(encoding="utf-8") == "-e /src/sase\nsase-core-rs\n"


def test_write_editable_overrides_degrades_on_oserror(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")

    assert (
        write_editable_overrides(
            (Requirement(name="sase", editable="/src/sase"),),
            path=blocked_parent / "overrides.txt",
        )
        is None
    )
