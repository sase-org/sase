"""The task-type registry must rebuild across a bare ``chdir``.

``get_task_type_registry()`` is keyed on ``current_config_token()``, which
folds the current working directory's project config into its payload. A
stale token (see ``test_config_cache_token.py``) serves the wrong project's
registry after a ``chdir`` with no other cache reset in between.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.task_types.registry import (
    get_task_type_registry,
    reset_task_type_registry_cache,
)


def _write_project(root: Path, slug: str) -> None:
    root.mkdir()
    sase_dir = root / "sase"
    sase_dir.mkdir()
    (sase_dir / "sase.yml").write_text(
        f"""
bead:
  task_types:
    - schema_version: 1
      task_type: {slug}
      label: {slug.title()}
      summary: A project-local task type declared only in {slug}'s root.
      when_to_use: File one when exercising {slug}'s registry.
      triage:
        min_plus_ones: 1
""",
        encoding="utf-8",
    )


def test_registry_rebuilds_across_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    _write_project(root_a, "widget_a")
    _write_project(root_b, "widget_b")

    reset_task_type_registry_cache()
    monkeypatch.chdir(root_a)
    registry_a = get_task_type_registry()
    assert "widget_a" in registry_a.by_slug
    assert "widget_b" not in registry_a.by_slug

    monkeypatch.chdir(root_b)
    registry_b = get_task_type_registry()
    assert "widget_b" in registry_b.by_slug
    assert "widget_a" not in registry_b.by_slug
