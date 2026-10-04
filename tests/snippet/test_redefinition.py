"""Provenance-accurate snippet redefinition analysis."""

from __future__ import annotations

from pathlib import Path

from sase.macro.snippet_bridge import MacroSnippetEntry
from sase.macro.snippet_targets import SnippetConfigLocation
from sase.macro.write_targets import MacroWriteTarget
from sase.snippet.catalog import _build_snippet_catalog
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetSourceContribution,
    is_macro_derived_kind,
)
from sase.snippet.redefinition import (
    snippet_create_verdict,
    snippet_definition_sites,
    snippet_edit_in_place_verdict,
    snippet_redefinition,
    snippet_redefinition_warning,
)


def _contribution(
    trigger: str,
    template: str,
    *,
    kind: str,
    path: str | None,
    layer: str | None,
    writable: bool = True,
    macro_name: str | None = None,
) -> SnippetSourceContribution:
    return SnippetSourceContribution(
        trigger=trigger,
        template=template,
        kind=kind,  # type: ignore[arg-type]
        path=path,
        display_path=path,
        writable=writable,
        macro_name=macro_name,
        layer=layer,
    )


def _catalog(
    contributions: list[SnippetSourceContribution],
    *,
    layer_names: tuple[str, ...] = (),
    layer_paths: tuple[str | None, ...] = (),
    macros: tuple[MacroSnippetEntry, ...] = (),
) -> SnippetCatalog:
    return _build_snippet_catalog(
        SnippetCatalogContext(key=None, name="demo", aliases=(), workspace_dir=None),
        macro_entries=macros,
        config_contributions=contributions,
        layer_paths=layer_paths,
        layer_names=layer_names,
    )


def _location(path: str, *, disabled: str | None = None) -> SnippetConfigLocation:
    return SnippetConfigLocation(
        label=Path(path).name,
        path=path,
        display_path=path,
        disabled_reason=disabled,
    )


def test_project_beats_user(tmp_path: Path) -> None:
    user = str(tmp_path / "user.yml")
    project = str(tmp_path / "sase" / "sase.yml")
    catalog = _catalog(
        [
            _contribution("todo", "user $0", kind="user", path=user, layer="user"),
            _contribution(
                "todo", "project $0", kind="project", path=project, layer="local"
            ),
        ],
        layer_names=("user", "local"),
        layer_paths=(user, project),
    )

    user_redef = snippet_redefinition(catalog, "todo", user)
    project_redef = snippet_redefinition(catalog, "todo", project)
    user_only = _catalog(
        [_contribution("todo", "user $0", kind="user", path=user, layer="user")],
        layer_names=("user", "local"),
        layer_paths=(user, project),
    )
    override = snippet_redefinition(user_only, "todo", project)

    assert user_redef.active is not None
    assert user_redef.active.path == project
    assert user_redef.destination_site is not None
    assert user_redef.destination_site.active is False
    warning = snippet_redefinition_warning(user_redef, "user.yml")
    assert warning is not None
    assert "is shadowed by" in warning
    assert "won't take effect" in warning
    assert project_redef.destination_site is not None
    assert project_redef.destination_site.active is True
    assert snippet_redefinition_warning(project_redef, "project.yml") is None
    assert override.winner_after_save is None
    assert snippet_redefinition_warning(override, "project.yml") == (
        "⚠ ⇥ todo already exists in "
        f"{override.active.display} — saving to project.yml will override it"
    )


def test_overlay_beats_user(tmp_path: Path) -> None:
    user = str(tmp_path / "sase.yml")
    overlay = str(tmp_path / "sase_work.yml")
    catalog = _catalog(
        [
            _contribution("todo", "user", kind="user", path=user, layer="user"),
            _contribution(
                "todo",
                "overlay",
                kind="overlay",
                path=overlay,
                layer="overlay:sase_work.yml",
            ),
        ],
        layer_names=("user", "overlay:sase_work.yml"),
        layer_paths=(user, overlay),
    )

    user_redef = snippet_redefinition(catalog, "todo", user)
    overlay_redef = snippet_redefinition(catalog, "todo", overlay)

    assert user_redef.winner_after_save is not None
    assert user_redef.winner_after_save.path == overlay
    assert overlay_redef.winner_after_save is None


def test_user_beats_plugin_and_default(tmp_path: Path) -> None:
    user = str(tmp_path / "sase.yml")
    catalog = _catalog(
        [
            _contribution(
                "todo",
                "built-in",
                kind="default",
                path=None,
                layer="default",
                writable=False,
            ),
            _contribution(
                "todo",
                "plugin",
                kind="plugin",
                path=None,
                layer="plugin:sase_github",
                writable=False,
            ),
            _contribution("todo", "user", kind="user", path=user, layer="user"),
        ],
        layer_names=("default", "plugin:sase_github", "user"),
        layer_paths=(None, None, user),
    )

    user_redef = snippet_redefinition(catalog, "todo", user)
    builtin_sites = snippet_definition_sites(catalog)

    assert user_redef.active is not None
    assert user_redef.active.path == user
    assert user_redef.winner_after_save is None
    displays = {site.display for site in builtin_sites if site.trigger == "todo"}
    assert "built-in default_config.yml" in displays
    assert "plugin sase_github" in displays


def test_macro_derived_is_lowest(tmp_path: Path) -> None:
    user = str(tmp_path / "sase.yml")
    catalog = _catalog(
        [],
        layer_names=("user",),
        layer_paths=(user,),
        macros=(
            MacroSnippetEntry(
                trigger="todo",
                template="from macro$0",
                macro_name="project/todo",
                source_path_display="macros/todo.md",
            ),
        ),
    )

    redef = snippet_redefinition(catalog, "todo", user)

    assert redef.active is not None
    assert is_macro_derived_kind(redef.active.kind)
    assert redef.winner_after_save is None
    assert snippet_redefinition_warning(redef, "user.yml") == (
        "⚠ ⇥ todo already exists in #project/todo (macro snippet) — "
        "saving to user.yml will override it"
    )


def test_built_in_and_plugin_origin_copy() -> None:
    catalog = _catalog(
        [
            _contribution(
                "todo",
                "built-in",
                kind="default",
                path=None,
                layer="default",
                writable=False,
            )
        ],
        layer_names=("default", "user"),
        layer_paths=(None, "/tmp/user.yml"),
    )
    redef = snippet_redefinition(catalog, "todo", "/tmp/user.yml")

    assert redef.active is not None
    assert redef.active.display == "built-in default_config.yml"
    assert snippet_redefinition_warning(redef, "~/.config/sase/sase.yml") == (
        "⚠ ⇥ todo already exists in built-in default_config.yml — "
        "saving to ~/.config/sase/sase.yml will override it"
    )


def test_chezmoi_path_mapping_matches_destination(tmp_path: Path, monkeypatch) -> None:
    deployed = str(tmp_path / "home" / ".config" / "sase" / "sase.yml")
    source = str(tmp_path / "chezmoi" / "dot_config" / "sase" / "sase.yml")
    catalog = _catalog(
        [_contribution("todo", "user", kind="user", path=deployed, layer="user")],
        layer_names=("user",),
        layer_paths=(deployed,),
    )

    def fake_resolve(path: str | Path) -> MacroWriteTarget:
        candidate = str(path)
        if candidate in {deployed, source}:
            return MacroWriteTarget(
                read_path=Path(deployed),
                write_path=Path(source),
                apply_target=Path(deployed),
                via_chezmoi=True,
            )
        resolved = Path(path).expanduser()
        return MacroWriteTarget(
            read_path=resolved,
            write_path=resolved,
            apply_target=None,
            via_chezmoi=False,
        )

    monkeypatch.setattr(
        "sase.snippet.redefinition.resolve_macro_write_target",
        fake_resolve,
    )

    redef = snippet_redefinition(catalog, "todo", source)

    assert redef.destination_site is not None
    assert redef.destination_site.active is True
    assert snippet_redefinition_warning(redef, source) is None


def test_out_of_discovery_destination_ranks_highest(tmp_path: Path) -> None:
    user = str(tmp_path / "sase.yml")
    custom = str(tmp_path / "custom.yml")
    catalog = _catalog(
        [_contribution("todo", "user", kind="user", path=user, layer="user")],
        layer_names=("user",),
        layer_paths=(user,),
    )

    redef = snippet_redefinition(catalog, "todo", custom)

    assert redef.destination_site is None
    assert redef.winner_after_save is None
    assert "will override it" in (
        snippet_redefinition_warning(redef, "custom.yml") or ""
    )


def test_alias_warning() -> None:
    catalog = _catalog(
        [
            _contribution(
                "todo", "TODO$0", kind="user", path="/tmp/sase.yml", layer="user"
            )
        ],
        layer_names=("user",),
        layer_paths=("/tmp/sase.yml",),
    )
    assert catalog.alias_provenance.get("Todo") == "todo"

    redef = snippet_redefinition(catalog, "Todo", "/tmp/sase.yml")

    assert redef.alias_of == "todo"
    assert snippet_redefinition_warning(redef, "/tmp/sase.yml") == (
        "⚠ ⇥ Todo is an alias of ⇥ todo — saving defines ⇥ Todo directly"
    )


def test_copy_table_fresh_name_and_edit_in_place(tmp_path: Path) -> None:
    dest = str(tmp_path / "sase.yml")
    catalog = _catalog(
        [_contribution("todo", "TODO$0", kind="user", path=dest, layer="user")],
        layer_names=("user",),
        layer_paths=(dest,),
    )
    fresh = snippet_redefinition(catalog, "later", dest)
    edit = snippet_redefinition(catalog, "todo", dest)

    assert snippet_redefinition_warning(fresh, dest) is None
    assert snippet_create_verdict("later", dest) == f"✓ Create ⇥ later at {dest}"
    assert snippet_redefinition_warning(edit, dest) is None
    assert snippet_edit_in_place_verdict("todo", dest) == (
        f"✓ Edit ⇥ todo in place · {dest}"
    )


def test_shadowed_in_place_edit_warning(tmp_path: Path) -> None:
    user = str(tmp_path / "user.yml")
    project = str(tmp_path / "project.yml")
    catalog = _catalog(
        [
            _contribution("todo", "user", kind="user", path=user, layer="user"),
            _contribution(
                "todo", "project", kind="project", path=project, layer="local"
            ),
        ],
        layer_names=("user", "local"),
        layer_paths=(user, project),
    )
    redef = snippet_redefinition(catalog, "todo", user)

    assert redef.destination_site is not None
    assert redef.destination_site.active is False
    warning = snippet_redefinition_warning(redef, "user.yml")
    assert warning is not None
    assert "is shadowed by" in warning
    assert "edits here won't take effect" in warning


def test_plus_n_more_count(tmp_path: Path) -> None:
    user = str(tmp_path / "user.yml")
    overlay = str(tmp_path / "overlay.yml")
    custom = str(tmp_path / "custom.yml")
    catalog = _catalog(
        [
            _contribution("todo", "user", kind="user", path=user, layer="user"),
            _contribution(
                "todo", "overlay", kind="overlay", path=overlay, layer="overlay:x"
            ),
        ],
        layer_names=("user", "overlay:x"),
        layer_paths=(user, overlay),
    )
    redef = snippet_redefinition(catalog, "todo", custom)
    warning = snippet_redefinition_warning(redef, "custom.yml")

    assert redef.winner_after_save is None
    assert warning is not None
    assert "(+1 more)" in warning
    assert "will override it" in warning


def test_site_display_prefers_display_path() -> None:
    catalog = _catalog(
        [
            SnippetSourceContribution(
                trigger="todo",
                template="from elsewhere",
                kind="project",
                path="/var/tmp/long/other.yml",
                display_path="~/sase/macros/todo_helpers.md",
                writable=True,
                layer="local",
            )
        ],
        layer_names=("user", "local"),
        layer_paths=("/tmp/dest.yml", "/var/tmp/long/other.yml"),
    )
    sites = snippet_definition_sites(catalog)
    dest = "/tmp/dest.yml"
    redef = snippet_redefinition(catalog, "todo", dest)

    assert sites[0].display == "~/sase/macros/todo_helpers.md"
    warning = snippet_redefinition_warning(redef, "~/.config/sase/sase.yml")
    assert warning is not None
    assert "~/sase/macros/todo_helpers.md" in warning
    assert "won't take effect" in warning
    assert "/var/tmp/long/other.yml" not in warning


def test_writable_requires_selectable_location(tmp_path: Path) -> None:
    user = str(tmp_path / "user.yml")
    catalog = _catalog(
        [_contribution("todo", "user", kind="user", path=user, layer="user")],
        layer_names=("user",),
        layer_paths=(user,),
    )
    readonly = snippet_definition_sites(
        catalog, [_location(user, disabled="read-only")]
    )
    writable = snippet_definition_sites(catalog, [_location(user)])

    assert readonly[0].writable is False
    assert writable[0].writable is True
