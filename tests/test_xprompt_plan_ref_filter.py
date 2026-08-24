"""Tests for the ``plan_ref_path`` prompt filter and its Python helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd import plan_refs
from sase.sdd.plan_refs import plan_reference_display_path
from sase.xprompt._jinja import get_jinja_env
from sase.xprompt.jinja_filters import _plan_ref_path
from sase.xprompt.jinja_inspect import jinja_filter_names


def test_canonical_plan_reference_returns_bare_path() -> None:
    assert plan_reference_display_path("plan:202608/foo.md") == "202608/foo.md"


def test_nested_canonical_reference_is_not_truncated_further() -> None:
    assert plan_reference_display_path("plan:202608/sub/foo.md") == "202608/sub/foo.md"


def test_absolute_path_under_store_root_strips_to_display_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    plan = root / "202608" / "foo.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    assert plan_reference_display_path(str(plan), roots=(root,)) == "202608/foo.md"


def test_home_relative_path_under_local_root_strips_to_display_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".sase" / "plans"
    root.mkdir(parents=True)

    assert (
        plan_reference_display_path("~/.sase/plans/202608/foo.md", roots=(root,))
        == "202608/foo.md"
    )


def test_sidecar_store_relative_path_strips_to_display_path(tmp_path: Path) -> None:
    root = tmp_path / "sase" / "repos" / "plans"
    root.mkdir(parents=True)
    plan = root / "202608" / "foo.md"

    assert plan_reference_display_path(str(plan), roots=(root,)) == "202608/foo.md"


def test_month_relative_path_not_under_any_root_passes_through(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    assert (
        plan_reference_display_path("202608/foo.md", roots=(root,)) == "202608/foo.md"
    )


def test_unrelated_absolute_path_passes_through_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "store"
    assert (
        plan_reference_display_path("/tmp/scratch.md", roots=(root,))
        == "/tmp/scratch.md"
    )


def test_empty_string_passes_through_unchanged() -> None:
    assert plan_reference_display_path("") == ""


def test_whitespace_only_passes_through_unchanged() -> None:
    assert plan_reference_display_path("   ") == "   "


def test_surrounding_whitespace_is_stripped_before_matching() -> None:
    assert plan_reference_display_path("  plan:202608/foo.md  ") == "202608/foo.md"


def test_filter_is_registered_for_ace_completion() -> None:
    assert "plan_ref_path" in jinja_filter_names()


def test_filter_renders_through_the_real_prompt_environment() -> None:
    env = get_jinja_env()
    template = env.from_string("{{ plan_file | plan_ref_path }}")
    assert template.render(plan_file="plan:202608/foo.md") == "202608/foo.md"


def test_filter_passes_non_string_values_through_untouched() -> None:
    assert _plan_ref_path(None) is None


def test_filter_returns_input_when_root_resolution_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_: object) -> tuple[Path, ...]:
        raise RuntimeError("boom")

    monkeypatch.setattr(plan_refs, "resolve_plan_roots", _boom)

    assert plan_reference_display_path("/tmp/scratch.md") == "/tmp/scratch.md"
