"""Tests for loading and resolving the project alias map."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import effective_project_name
from sase.project_aliases import (
    canonicalize_project_aliases_in_prompt,
    load_project_alias_map,
    resolve_project_alias_ref,
)
from tests._project_alias_services_helpers import _record
from tests.main.project_handler_helpers import (
    _write_project,
    projects_root,
)

__all__ = ["projects_root"]


def test_load_project_alias_map_ignores_spec_less_project_name_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_cli_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: b\n",
    )
    stray_project_file = projects_root / "bob" / "bob.sase"
    stray_project_file.parent.mkdir()

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "bob",
                launchable=False,
                project_file=stray_project_file,
                aliases=[],
            ),
            _record("bob-cli", aliases=["bob"], project_file=bob_cli_file),
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    assert load_project_alias_map(projects_root) == {"bob": "bob-cli"}
    assert canonicalize_project_aliases_in_prompt("#gh:bob fix") == "#gh:bob-cli fix"


def test_load_project_alias_map_drops_alias_shadowed_by_real_project(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_file = _write_project(
        projects_root,
        "bob",
        "WORKSPACE_DIR: /tmp/bob\nNAME: b\n",
    )
    bob_cli_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: c\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob", project_file=bob_file),
            _record("bob-cli", aliases=["bob"], project_file=bob_cli_file),
        ],
    )

    # A ref shadowed by a real project name self-resolves instead of
    # crashing read paths (e.g. `sase tui` startup).
    assert load_project_alias_map(projects_root) == {}
    assert resolve_project_alias_ref("bob", projects_root) == "bob"


def test_load_project_alias_map_drops_duplicate_alias(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_file = _write_project(
        projects_root,
        "bob-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/bob-cli\nNAME: b\n",
    )
    docs_file = _write_project(
        projects_root,
        "docs-cli",
        "PROJECT_ALIASES: bob\nWORKSPACE_DIR: /tmp/docs-cli\nNAME: d\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("bob-cli", aliases=["bob"], project_file=bob_file),
            _record("docs-cli", aliases=["bob"], project_file=docs_file),
        ],
    )

    # An ambiguous ref maps to neither claimant so it self-resolves.
    assert load_project_alias_map(projects_root) == {}
    assert resolve_project_alias_ref("bob", projects_root) == "bob"


def test_load_project_alias_map_includes_display_name(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets_file = _write_project(
        projects_root,
        "gh_acme__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/widgets\nNAME: c\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__widgets",
                project_file=widgets_file,
                display_name="widgets",
            ),
        ],
    )
    monkeypatch.setattr("sase.project_aliases._vcs_workflow_names", lambda: {"gh"})

    assert (
        effective_project_name(_record("gh_acme__widgets", display_name="widgets"))
        == "widgets"
    )
    assert load_project_alias_map(projects_root) == {"widgets": "gh_acme__widgets"}
    assert canonicalize_project_aliases_in_prompt("#gh:widgets fix") == (
        "#gh:gh_acme__widgets fix"
    )
    assert canonicalize_project_aliases_in_prompt("#gh:widgets_fix_1 fix") == (
        "#gh:gh_acme__widgets_fix_1 fix"
    )


def test_load_project_alias_map_drops_display_name_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_file = _write_project(
        projects_root,
        "gh_acme__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/a\nNAME: a\n",
    )
    second_file = _write_project(
        projects_root,
        "gh_globex__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/b\nNAME: b\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__widgets",
                project_file=first_file,
                display_name="widgets",
            ),
            _record(
                "gh_globex__widgets",
                project_file=second_file,
                display_name="widgets",
            ),
        ],
    )

    assert load_project_alias_map(projects_root) == {}
    assert resolve_project_alias_ref("widgets", projects_root) == "widgets"


def test_load_project_alias_map_keeps_valid_refs_next_to_dropped_ones(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The crash scenario: PROJECT_NAME shadowed by a phantom real project.

    The shadowed ref is dropped but every other ref still resolves, so
    ``sase tui`` keeps working instead of crashing at startup.
    """
    sase_file = _write_project(
        projects_root,
        "sase",
        "WORKSPACE_DIR: /tmp/sase\nNAME: s\n",
    )
    gh_file = _write_project(
        projects_root,
        "gh_acme__sase",
        "PROJECT_NAME: sase\nPROJECT_ALIASES: widgets\n"
        "WORKSPACE_DIR: /tmp/gh\nNAME: g\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record("sase", project_file=sase_file),
            _record(
                "gh_acme__sase",
                project_file=gh_file,
                display_name="sase",
                aliases=["widgets"],
            ),
        ],
    )

    assert load_project_alias_map(projects_root) == {"widgets": "gh_acme__sase"}
    assert resolve_project_alias_ref("sase", projects_root) == "sase"


def test_load_project_alias_map_dropped_ref_stays_dropped(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ref dropped for ambiguity is not re-adopted by a later claimant."""
    files = {
        name: _write_project(
            projects_root,
            name,
            f"PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/{name}\nNAME: n\n",
        )
        for name in ("gh_acme__widgets", "gh_globex__widgets", "gh_initech__widgets")
    }

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(name, project_file=file, display_name="widgets")
            for name, file in files.items()
        ],
    )

    assert load_project_alias_map(projects_root) == {}


def test_load_project_alias_map_drops_case_variant_collision(
    projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_file = _write_project(
        projects_root,
        "gh_acme__widgets",
        "PROJECT_NAME: Widgets\nWORKSPACE_DIR: /tmp/a\nNAME: a\n",
    )
    second_file = _write_project(
        projects_root,
        "gh_globex__widgets",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/b\nNAME: b\n",
    )

    monkeypatch.setattr(
        "sase.project_aliases.list_project_records",
        lambda *_args, **_kwargs: [
            _record(
                "gh_acme__widgets",
                project_file=first_file,
                display_name="Widgets",
            ),
            _record(
                "gh_globex__widgets",
                project_file=second_file,
                display_name="widgets",
            ),
        ],
    )

    assert load_project_alias_map(projects_root) == {}
