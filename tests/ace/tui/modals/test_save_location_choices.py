"""Unit coverage for the save-location choice builders."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals import _save_location_choice_format as format_mod
from sase.ace.tui.modals.save_location_choices import (
    EXISTING_CHOICE_ID,
    ExistingRowSpec,
    snippet_location_choices,
    macro_location_choices,
)
from sase.ace.tui.modals.unified_macro_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import MacroLocation
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget


def _macro_row(
    path: Path,
    label: str,
    *,
    location_type: str = "directory",
    group: str = "Project",
    names: frozenset[str] = frozenset(),
    precedence: int = 0,
    disabled_reason: str | None = None,
    namespace: str | None = None,
    builtin: bool = False,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=MacroLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
        builtin=builtin,
    )


def _standard_macro_rows(tmp_path: Path) -> list[UnifiedSaveLocation]:
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    personal = tmp_path / "personal"
    personal.mkdir()
    return [
        _macro_row(proj, "Project sase/macros/", namespace="sase"),
        _macro_row(
            tmp_path / "sase.yml",
            "Project sase/sase.yml",
            location_type="config",
            group="Config files",
        ),
        _macro_row(personal, "Project home (sase)"),
        _macro_row(home, "Home ~/sase/macros/"),
        _macro_row(
            tmp_path / "u.yml",
            "User sase.yml",
            location_type="config",
            group="Config files",
        ),
        _macro_row(
            tmp_path / "w.yml",
            "User sase_work.yml",
            location_type="config",
            group="Config files",
        ),
    ]


def _by_label(choices):  # type: ignore[no-untyped-def]
    return {choice.label: choice for choice in choices}


def test_canonical_letters_shift_variants_and_digit_order(tmp_path: Path) -> None:
    choices, default = macro_location_choices(
        _standard_macro_rows(tmp_path), project="sase"
    )

    by_label = _by_label(choices)
    assert by_label["Project macros"].hotkey == "p"
    assert by_label["Project config"].hotkey == "P"
    assert by_label["Home macros"].hotkey == "h"
    assert by_label["User config"].hotkey == "H"
    assert by_label["Project, personal"].hotkey == "1"
    assert by_label["sase_work.yml"].hotkey == "2"
    assert [choice.section for choice in choices].index("Home") > 0
    assert default == by_label["Project macros"].choice_id
    assert by_label["Project macros"].badges == ("★ default",)


def test_digits_stop_after_nine(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    for index in range(11):
        overlay = tmp_path / f"extra_{index}.yml"
        rows.append(
            _macro_row(
                overlay,
                f"User sase_extra_{index}.yml",
                location_type="config",
                group="Config files",
            )
        )
    choices, _default = macro_location_choices(rows, project="sase")

    digits = [c.hotkey for c in choices if c.hotkey and c.hotkey.isdigit()]
    assert digits == [str(n) for n in range(1, 10)]
    extras = [c for c in choices if c.label.startswith("sase_extra_")]
    assert [c.hotkey for c in extras[:7]] == [str(n) for n in range(3, 10)]
    assert all(c.hotkey is None for c in extras[7:])


def test_disabled_canonical_keeps_letter_but_renders_without_key(
    tmp_path: Path,
) -> None:
    rows = _standard_macro_rows(tmp_path)
    rows[1] = _macro_row(
        tmp_path / "sase.yml",
        "Project sase/sase.yml",
        location_type="config",
        group="Config files",
        disabled_reason="migrate legacy project config first",
    )
    choices, _default = macro_location_choices(rows, project="sase")

    by_label = _by_label(choices)
    project_config = by_label["Project config"]
    assert project_config.disabled_reason == "migrate legacy project config first"
    # The canonical letter is retained so the modal can report *why* the
    # usual key is unavailable; it renders as · with no hint entry.
    assert project_config.hotkey == "P"
    assert not project_config.is_default


def test_hidden_non_canonical_disabled_rows(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    rows.append(
        _macro_row(
            tmp_path / "broken.yml",
            "User sase_broken.yml",
            location_type="config",
            group="Config files",
            disabled_reason="read-only",
        )
    )
    choices, _default = macro_location_choices(rows, project="sase")

    assert "sase_broken.yml" not in _by_label(choices)


def test_plugin_rows_collapsed_without_hotkeys(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    rows.append(
        _macro_row(
            plugin,
            "Plugin (demo) macros/",
            group="Plugin directories",
        )
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    rows.append(
        _macro_row(
            builtin,
            "Built-in macros/",
            group="Built-in (dev)",
            builtin=True,
        )
    )
    choices, _default = macro_location_choices(rows, project="sase")

    plugin_choices = [c for c in choices if c.collapsed_group]
    assert len(plugin_choices) == 2
    assert all(c.hotkey is None for c in plugin_choices)
    assert all(c.section == "Plugins & built-in" for c in plugin_choices)
    assert choices[-2].section == "Plugins & built-in"


def test_macro_default_ladder_current_then_last_used(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    project_dir = str(rows[0].location.path)
    home_dir = str(rows[3].location.path)

    choices, default = macro_location_choices(
        rows, project="sase", last_used_path=home_dir
    )
    assert default == home_dir
    assert _by_label(choices)["Home macros"].badges == ("★ last used",)

    choices, default = macro_location_choices(
        rows, project="sase", last_used_path=home_dir, current_path=project_dir
    )
    assert default == project_dir
    assert _by_label(choices)["Project macros"].badges == ("★ current",)


def test_macro_home_mode_skips_project_default(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    choices, default = macro_location_choices(rows, project="sase", home_mode=True)

    assert default == str(rows[3].location.path)
    assert _by_label(choices)["Home macros"].badges == ("★ default",)


def test_macro_stale_last_used_falls_through(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    choices, default = macro_location_choices(
        rows, project="sase", last_used_path="/nonexistent/path"
    )

    assert default == str(rows[0].location.path)


def test_macro_current_matches_resolved_write_path(tmp_path: Path, monkeypatch) -> None:
    rows = _standard_macro_rows(tmp_path)
    project_dir = str(rows[0].location.path)
    monkeypatch.setattr(
        format_mod,
        "resolve_macro_write_target",
        lambda path: type(
            "_Target", (), {"write_path": "SOURCE", "via_chezmoi": False}
        )(),
    )
    choices, default = macro_location_choices(
        rows, project="sase", current_path="SOURCE"
    )

    assert default == project_dir
    assert _by_label(choices)["Project macros"].badges == ("★ current",)


def test_macro_has_name_badges_and_previews(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    rows[0] = _macro_row(
        tmp_path / "proj",
        "Project sase/macros/",
        names=frozenset({"review"}),
        namespace="sase",
    )
    choices, _default = macro_location_choices(rows, project="sase", name="review")

    by_label = _by_label(choices)
    assert "has #review" in by_label["Project macros"].badges
    assert "called as #sase/review" in by_label["Project macros"].preview
    assert "1 macro here" in by_label["Project macros"].preview
    assert "macros.review" in by_label["Project config"].preview

    choices, _default = macro_location_choices(rows, project="sase")
    assert "called as #sase/<name>" in _by_label(choices)["Project macros"].preview
    assert "macros.<name>" in _by_label(choices)["Project config"].preview


def _sloc(
    path: Path, label: str, *, reason: str | None = None
) -> SnippetConfigLocation:
    return SnippetConfigLocation(label, str(path), str(path), reason)


def _starget(path: Path, *, source: str = "default") -> SnippetSaveTarget:  # type: ignore[no-untyped-def]
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=str(path),
        source=source,  # type: ignore[arg-type]
        fallback_reason=None,
    )


def _standard_slocs(tmp_path: Path) -> list[SnippetConfigLocation]:
    user = tmp_path / "sase.yml"
    user.write_text("{}")
    work = tmp_path / "sase_work.yml"
    work.write_text("{}")
    return [
        _sloc(user, "User sase.yml"),
        _sloc(work, "User sase_work.yml"),
        _sloc(tmp_path / "project.yml", "Project sase/sase.yml"),
    ]


def test_snippet_canonical_keys_and_default(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    target = _starget(tmp_path / "sase.yml")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
    )

    by_label = _by_label(choices)
    assert by_label["Project config"].hotkey == "p"
    assert by_label["User config"].hotkey == "h"
    assert by_label["sase_work.yml"].hotkey == "1"
    assert [c.section for c in choices] == [
        "Project · sase",
        "Home",
        "Home",
    ]
    assert default == str(tmp_path / "sase.yml")
    assert by_label["User config"].badges[0] == "★ default"


def test_snippet_configured_outside_discovery_gets_c(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    custom = tmp_path / "custom.yml"
    custom.write_text("{}")
    target = _starget(custom, source="configured")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
    )

    by_label = _by_label(choices)
    configured = by_label["Configured snippet config"]
    assert configured.hotkey == "c"
    assert configured.section == "Configured"
    assert choices[0] == configured
    assert default == str(custom)
    assert configured.badges[0] == "★ configured"


def test_snippet_default_ladder_current_then_configured(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    user = str(tmp_path / "sase.yml")
    project_cfg = str(tmp_path / "project.yml")
    custom = tmp_path / "custom.yml"
    custom.write_text("{}")

    target = _starget(custom, source="configured")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
        last_used_path=user,
    )
    assert default == str(custom)

    target = _starget(tmp_path / "sase.yml")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
        last_used_path=user,
        current_path=project_cfg,
    )
    assert default == project_cfg
    assert _by_label(choices)["Project config"].badges[0] == "★ current"


def test_snippet_has_trigger_badges_and_previews(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    target = _starget(tmp_path / "sase.yml")
    choices, _default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={str(tmp_path / "sase.yml"): frozenset({"todo"})},
        project="sase",
        trigger="todo",
    )

    by_label = _by_label(choices)
    assert "has ⇥ todo" in by_label["User config"].badges
    assert "ace.snippets.todo" in by_label["User config"].preview
    assert "1 snippets here" in by_label["User config"].preview

    choices, _default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
    )
    assert "ace.snippets.<trigger>" in _by_label(choices)["User config"].preview


def test_unified_save_has_single_canonical_project_and_home_dirs(
    tmp_path: Path,
) -> None:
    """Canonical macro dirs appear exactly once with unique hotkeys."""
    from sase.ace.tui.modals.unified_macro_save_support import (
        _with_missing_standard_directories,
    )
    from sase.ace.tui.modals.macro_location_modal import (
        MACRO_HOME_DIR_LABEL,
        MACRO_PROJECT_DIR_LABEL,
    )

    project_dir = tmp_path / "proj-macros"
    project_dir.mkdir()
    home_dir = tmp_path / "home-macros"
    home_dir.mkdir()
    locations: list[tuple[str, MacroLocation]] = [
        (
            "Directories",
            MacroLocation(MACRO_PROJECT_DIR_LABEL, str(project_dir), "directory"),
        ),
        (
            "Directories",
            MacroLocation(MACRO_HOME_DIR_LABEL, str(home_dir), "directory"),
        ),
    ]

    import sase.ace.tui.modals.unified_macro_save_support as support_mod

    def _fake_project_layout(root: object) -> object:
        class _Paths:
            write_path = project_dir

        class _Layout:
            macros = _Paths()

        return _Layout()  # type: ignore[return-value]

    def _fake_home_layout(*args: object, **kwargs: object) -> object:
        class _Paths:
            write_path = home_dir

        class _Layout:
            macros = _Paths()

        return _Layout()  # type: ignore[return-value]

    def _fake_chezmoi_layout(*args: object, **kwargs: object) -> object:
        class _Paths:
            write_path = home_dir

        class _Layout:
            macros = _Paths()

        return _Layout()  # type: ignore[return-value]

    original_project = support_mod.resolve_project_layout
    original_home = support_mod.resolve_home_layout
    original_chezmoi = support_mod.resolve_chezmoi_layout
    original_chezmoi_flag = support_mod.get_use_chezmoi
    support_mod.resolve_project_layout = _fake_project_layout  # type: ignore[assignment]
    support_mod.resolve_home_layout = _fake_home_layout  # type: ignore[assignment]
    support_mod.resolve_chezmoi_layout = _fake_chezmoi_layout  # type: ignore[assignment]
    support_mod.get_use_chezmoi = lambda: False  # type: ignore[assignment]
    try:
        completed = _with_missing_standard_directories(locations)
    finally:
        support_mod.resolve_project_layout = original_project  # type: ignore[assignment]
        support_mod.resolve_home_layout = original_home  # type: ignore[assignment]
        support_mod.resolve_chezmoi_layout = original_chezmoi  # type: ignore[assignment]
        support_mod.get_use_chezmoi = original_chezmoi_flag  # type: ignore[assignment]

    project_rows = [
        location
        for _, location in completed
        if location.label == MACRO_PROJECT_DIR_LABEL
    ]
    home_rows = [
        location for _, location in completed if location.label == MACRO_HOME_DIR_LABEL
    ]
    assert len(project_rows) == 1
    assert len(home_rows) == 1

    rows = [
        _macro_row(project_dir, MACRO_PROJECT_DIR_LABEL, namespace="sase"),
        _macro_row(home_dir, MACRO_HOME_DIR_LABEL, group="Home directories"),
    ]
    choices, _default = macro_location_choices(rows, project="sase")
    by_label = _by_label(choices)
    assert by_label["Project macros"].hotkey == "p"
    assert by_label["Home macros"].hotkey == "h"
    assert by_label["Project macros"].hotkey != by_label["Home macros"].hotkey


def test_existing_row_prepended_with_count_and_preview(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    choices, default = macro_location_choices(
        rows, project="sase", existing=ExistingRowSpec(count=148)
    )

    existing = choices[0]
    assert existing.choice_id == EXISTING_CHOICE_ID
    assert existing.hotkey == "e"
    assert existing.kind == "existing"
    assert existing.section == "Existing"
    assert existing.label == "Edit existing macro…"
    assert existing.badges == ("148 macros",)
    assert existing.disabled_reason is None
    assert not existing.is_default
    assert "fuzzy-find 148 macros across 6 files" in existing.preview
    assert default == str(rows[0].location.path)
    assert default != EXISTING_CHOICE_ID
    assert _by_label(choices)["Project, personal"].hotkey == "1"


def test_existing_row_switching_label(tmp_path: Path) -> None:
    choices, _default = macro_location_choices(
        _standard_macro_rows(tmp_path),
        project="sase",
        existing=ExistingRowSpec(count=3, switching=True),
    )
    assert choices[0].label == "Switch to existing macro…"


def test_existing_row_disabled_when_empty(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    choices, default = macro_location_choices(
        rows,
        project="sase",
        existing=ExistingRowSpec(count=0),
    )
    assert choices[0].disabled_reason == "no macros yet"
    assert not choices[0].is_selectable
    assert not choices[0].is_default
    assert default == str(rows[0].location.path)


def test_existing_row_never_default_on_empty_destinations() -> None:
    choices, default = macro_location_choices([], existing=ExistingRowSpec(count=5))
    assert [c.choice_id for c in choices] == [EXISTING_CHOICE_ID]
    assert default is None
    assert not choices[0].is_default


def test_override_omits_existing_and_filters_namespace(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    project_dir = str(rows[0].location.path)
    project_cfg = str(rows[1].location.path)
    home_dir = str(rows[3].location.path)
    choices, default = macro_location_choices(
        rows,
        project="sase",
        existing=ExistingRowSpec(count=12),
        override_name="review",
        shadowed_by={project_cfg: "~/sase/macros/review.md"},
    )

    assert all(c.choice_id != EXISTING_CHOICE_ID for c in choices)
    by_label = _by_label(choices)
    project_macros = by_label["Project macros"]
    assert project_macros.disabled_reason == (
        "saves as #sase/review — can't override #review"
    )
    assert "⚠ shadowed by ~/sase/macros/review.md" in by_label["Project config"].badges
    assert by_label["Project config"].is_selectable
    assert default != project_dir
    default_choice = next(c for c in choices if c.choice_id == default)
    assert "★ override" in default_choice.badges
    assert default_choice.choice_id != project_cfg
    assert by_label["Home macros"].disabled_reason is None
    assert home_dir in {c.choice_id for c in choices}


def test_override_default_prefers_current_then_unshadowed(tmp_path: Path) -> None:
    rows = _standard_macro_rows(tmp_path)
    home_dir = str(rows[3].location.path)
    project_cfg = str(rows[1].location.path)
    choices, default = macro_location_choices(
        rows,
        project="sase",
        override_name="review",
        current_path=home_dir,
        shadowed_by={home_dir: "plugin copy"},
    )
    assert default == home_dir
    assert _by_label(choices)["Home macros"].badges[0] == "★ override"
    assert "⚠ shadowed by plugin copy" in _by_label(choices)["Home macros"].badges

    choices, default = macro_location_choices(
        rows,
        project="sase",
        override_name="review",
        last_used_path=project_cfg,
        shadowed_by={project_cfg: "winner"},
    )
    assert default == project_cfg
    assert "★ override" in _by_label(choices)["Project config"].badges


def test_snippet_existing_row_and_override(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    target = _starget(tmp_path / "sase.yml")
    user = str(tmp_path / "sase.yml")
    project_cfg = str(tmp_path / "project.yml")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
        existing=ExistingRowSpec(count=9),
    )
    existing = choices[0]
    assert existing.choice_id == EXISTING_CHOICE_ID
    assert existing.label == "Edit existing snippet…"
    assert existing.badges == ("9 snippets",)
    assert "fuzzy-find 9 snippets across 3 files" in existing.preview
    assert default == user
    assert default != EXISTING_CHOICE_ID
    assert _by_label(choices)["sase_work.yml"].hotkey == "1"

    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
        existing=ExistingRowSpec(count=0, switching=True),
        override_name="todo",
        shadowed_by={user: "./sase/sase.yml"},
    )
    assert all(c.choice_id != EXISTING_CHOICE_ID for c in choices)
    by_label = _by_label(choices)
    assert "⚠ shadowed by ./sase/sase.yml" in by_label["User config"].badges
    assert default == project_cfg
    assert by_label["Project config"].badges[0] == "★ override"


def test_snippet_override_keeps_configured_after_current(tmp_path: Path) -> None:
    locations = _standard_slocs(tmp_path)
    custom = tmp_path / "custom.yml"
    custom.write_text("{}")
    target = _starget(custom, source="configured")
    user = str(tmp_path / "sase.yml")
    choices, default = snippet_location_choices(
        locations,
        resolved_target=target,
        names_by_path={},
        project="sase",
        last_used_path=user,
        override_name="todo",
    )
    assert default == str(custom)
    assert _by_label(choices)["Configured snippet config"].badges[0] == "★ override"
