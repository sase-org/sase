"""Tests for ChangeSpecSnapshotCache."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec import cache as cache_mod
from sase.ace.changespec.cache import ChangeSpecSnapshotCache


_GP_HEADER = """\
NAME: alpha
DESCRIPTION:
  alpha desc
STATUS: Ready
"""

_GP_TWO_SPECS = """\
NAME: alpha
DESCRIPTION:
  alpha desc
STATUS: Ready

NAME: beta
DESCRIPTION:
  beta desc
PARENT: alpha
STATUS: Draft
"""


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_cached_get_file_specs_returns_same_specs(tmp_path: Path) -> None:
    f = tmp_path / "p.gp"
    _write(f, _GP_HEADER)

    cache = ChangeSpecSnapshotCache()
    a = cache.get_file_specs(f)
    b = cache.get_file_specs(f)

    assert len(a) == 1 == len(b)
    assert a[0].name == "alpha"
    assert b[0].name == "alpha"


def test_warm_cache_makes_zero_parse_calls(tmp_path: Path) -> None:
    f = tmp_path / "p.gp"
    _write(f, _GP_TWO_SPECS)

    cache = ChangeSpecSnapshotCache()
    cache.get_file_specs(f)  # Cold

    real = cache_mod.parse_project_file
    with patch.object(cache_mod, "parse_project_file", side_effect=real) as spy:
        cache.get_file_specs(f)
        cache.get_file_specs(f)
        cache.get_file_specs(f)
    assert spy.call_count == 0


def test_editing_one_file_reparses_only_that_file(tmp_path: Path) -> None:
    a = tmp_path / "a.gp"
    b = tmp_path / "b.gp"
    _write(a, _GP_HEADER)
    _write(b, _GP_HEADER.replace("alpha", "beta"))

    cache = ChangeSpecSnapshotCache()
    cache.get_file_specs(a)
    cache.get_file_specs(b)

    # Touch only file `a` so its (mtime_ns, size) signature changes.
    time.sleep(0.01)
    new_text = _GP_HEADER.replace("Ready", "Draft")
    a.write_text(new_text)
    new_mtime = time.time_ns()
    os.utime(a, ns=(new_mtime, new_mtime))

    real = cache_mod.parse_project_file
    with patch.object(cache_mod, "parse_project_file", side_effect=real) as spy:
        cache.get_file_specs(a)
        cache.get_file_specs(b)
    assert spy.call_count == 1
    assert spy.call_args.args[0] == os.fspath(a)


def test_find_all_changespecs_cached_uses_projects_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)

    proj = home / ".sase" / "projects" / "demo"
    _write(proj / "demo.gp", _GP_TWO_SPECS)

    cache = ChangeSpecSnapshotCache()
    first = cache.find_all_changespecs_cached()
    assert {cs.name for cs in first} == {"alpha", "beta"}

    real = cache_mod.parse_project_file
    with patch.object(cache_mod, "parse_project_file", side_effect=real) as spy:
        second = cache.find_all_changespecs_cached()
    assert spy.call_count == 0
    assert {cs.name for cs in second} == {"alpha", "beta"}
