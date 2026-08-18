"""Tests for repo preview card render helpers."""

from __future__ import annotations

import io

from rich.console import Console

from sase.ace.tui.modals.repo_preview_render import (
    _repo_declaration_display,
    build_repo_chips,
    build_repo_property_grid,
    build_repo_title,
    repo_checkout_display,
    repo_checkout_path,
    repo_clones_display,
    repo_not_cloned_hint,
)
from sase.repo_inventory import RepoCloneRecord, RepoRecord
from sase.xprompt.repo_mention_catalog import RepoMention


def _render_text(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(renderable)
    return console.export_text()


def _record(
    *,
    kind: str = "linked",
    name: str = "sase-core",
    path: str = "/repos/sase-core",
    exists: bool = True,
    auto_clone: bool = False,
    auto_sync: bool = False,
    env_name: str | None = None,
    remote_url: str | None = None,
    clones: tuple[RepoCloneRecord, ...] = (),
    description: str | None = "Shared Rust core backend.",
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="sase",
        project_key="sase",
        path=path,
        exists=exists,
        auto_clone=auto_clone,
        auto_sync=auto_sync,
        description=description,
        source="test",
        env_name=env_name,
        remote_url=remote_url,
        clones=clones,
    )


def _mention(
    record: RepoRecord,
    *,
    identifier: str = "sase-core",
    config_path: str | None = "/workspace/sase/sase.yml",
    config_line: int | None = 16,
    config_col: int | None = 7,
) -> RepoMention:
    return RepoMention(
        identifier=identifier,
        kind=record.kind,
        record=record,
        index=0,
        config_path=config_path,
        config_line=config_line,
        config_col=config_col,
    )


def test_title_omits_matched_line_when_match_equals_identifier() -> None:
    mention = _mention(_record())

    text = _render_text(
        build_repo_title(mention, matched_text="sase-core", accent="#C3ABD8")
    )

    assert "sase-core" in text
    assert "matched" not in text


def test_title_discloses_matched_text_on_case_difference() -> None:
    mention = _mention(_record())

    text = _render_text(
        build_repo_title(mention, matched_text="Sase-Core", accent="#C3ABD8")
    )

    assert 'matched "Sase-Core"' in text


def test_chips_include_kind_auto_clone_auto_sync_and_env() -> None:
    record = _record(auto_clone=True, auto_sync=True, env_name="SASE_CORE")
    mention = _mention(record)

    text = _render_text(build_repo_chips(mention, accent="#C3ABD8"))

    assert "LINKED" in text
    assert "AUTO-CLONE" in text
    assert "AUTO-SYNC" in text
    assert "ENV SASE_CORE" in text


def test_chips_omit_unset_flags() -> None:
    record = _record(auto_clone=False, auto_sync=False, env_name=None)
    mention = _mention(record)

    text = _render_text(build_repo_chips(mention, accent="#C3ABD8"))

    assert "LINKED" in text
    assert "AUTO-CLONE" not in text
    assert "AUTO-SYNC" not in text
    assert "ENV" not in text


def test_checkout_path_prefers_workspace_clone() -> None:
    record = _record(
        path="/repos/sase-core",
        exists=False,
        clones=(
            RepoCloneRecord(workspace_num=3, path="/ws3/sase-core", exists=True),
            RepoCloneRecord(workspace_num=7, path="/ws7/sase-core", exists=False),
        ),
    )
    mention = _mention(record)

    assert repo_checkout_path(mention, workspace_num=3) == ("/ws3/sase-core", True)
    assert repo_checkout_path(mention, workspace_num=None) == (
        "/repos/sase-core",
        False,
    )


def test_checkout_display_appends_not_cloned_suffix() -> None:
    assert repo_checkout_display("/repos/sase-core", exists=True) == "/repos/sase-core"
    assert (
        repo_checkout_display("/repos/sase-core", exists=False)
        == "/repos/sase-core (not cloned)"
    )


def test_not_cloned_hint_prints_exact_open_command() -> None:
    mention = _mention(_record())

    assert repo_not_cloned_hint(mention, exists=True) is None
    assert repo_not_cloned_hint(mention, exists=False) == (
        "Run `sase repo open sase-core` to materialize this checkout."
    )


def test_clones_display_counts_existing_of_registered() -> None:
    record = _record(
        clones=(
            RepoCloneRecord(workspace_num=1, path="/ws1", exists=True),
            RepoCloneRecord(workspace_num=2, path="/ws2", exists=False),
            RepoCloneRecord(workspace_num=3, path="/ws3", exists=True),
        )
    )
    mention = _mention(record)

    assert repo_clones_display(mention) == "2 of 3 workspaces"


def test_clones_display_omitted_without_clone_records() -> None:
    mention = _mention(_record(clones=()))

    assert repo_clones_display(mention) is None


def test_declaration_display_includes_line_and_col() -> None:
    mention = _mention(
        _record(),
        config_path="/workspace/sase/sase.yml",
        config_line=16,
        config_col=7,
    )

    assert _repo_declaration_display(mention) == "/workspace/sase/sase.yml:16:7"


def test_declaration_display_none_for_external_repo() -> None:
    mention = _mention(
        _record(kind="external"),
        config_path=None,
        config_line=None,
        config_col=None,
    )

    assert _repo_declaration_display(mention) is None


def test_property_grid_omits_remote_and_declared_when_unknown() -> None:
    mention = _mention(
        _record(remote_url=None),
        config_path=None,
        config_line=None,
        config_col=None,
    )

    text = _render_text(
        build_repo_property_grid(
            mention,
            checkout_display="/repos/sase-core",
            clones_display=None,
        )
    )

    assert "Project" in text
    assert "Kind" in text
    assert "Checkout" in text
    assert "Clones" not in text
    assert "Remote" not in text
    assert "Declared" not in text


def test_property_grid_includes_remote_and_declared_when_known() -> None:
    mention = _mention(_record(remote_url="git@github.com:bbugyi200/sase-core.git"))

    text = _render_text(
        build_repo_property_grid(
            mention,
            checkout_display="/repos/sase-core",
            clones_display="18 of 24 workspaces",
        )
    )

    assert "git@github.com:bbugyi200/sase-core.git" in text
    assert "18 of 24 workspaces" in text
    assert "/workspace/sase/sase.yml:16:7" in text
