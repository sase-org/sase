"""Unit coverage for the save-location choice builders."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals import save_location_choices as choices_mod
from sase.ace.tui.modals.save_location_choices import (
    snippet_location_choices,
    xprompt_location_choices,
)
from sase.ace.tui.modals.unified_xprompt_save_support import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget


def _xrow(
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
        location=XPromptLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
        builtin=builtin,
    )


def _standard_xrows(tmp_path: Path) -> list[UnifiedSaveLocation]:
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    personal = tmp_path / "personal"
    personal.mkdir()
    return [
        _xrow(proj, "Project sase/xprompts/", namespace="sase"),
        _xrow(
            tmp_path / "sase.yml",
            "Project sase/sase.yml",
            location_type="config",
            group="Config files",
        ),
        _xrow(personal, "Project home (sase)"),
        _xrow(home, "Home ~/sase/xprompts/"),
        _xrow(
            tmp_path / "u.yml",
            "User sase.yml",
            location_type="config",
            group="Config files",
        ),
        _xrow(
            tmp_path / "w.yml",
            "User sase_work.yml",
            location_type="config",
            group="Config files",
        ),
    ]


def _by_label(choices):  # type: ignore[no-untyped-def]
    return {choice.label: choice for choice in choices}


def test_canonical_letters_shift_variants_and_digit_order(tmp_path: Path) -> None:
    choices, default = xprompt_location_choices(
        _standard_xrows(tmp_path), project="sase"
    )

    by_label = _by_label(choices)
    assert by_label["Project xprompts"].hotkey == "p"
    assert by_label["Project config"].hotkey == "P"
    assert by_label["Home xprompts"].hotkey == "h"
    assert by_label["User config"].hotkey == "H"
    assert by_label["Project, personal"].hotkey == "1"
    assert by_label["sase_work.yml"].hotkey == "2"
    assert [choice.section for choice in choices].index("Home") > 0
    assert default == by_label["Project xprompts"].choice_id
    assert by_label["Project xprompts"].badges == ("★ default",)


def test_digits_stop_after_nine(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    for index in range(11):
        overlay = tmp_path / f"extra_{index}.yml"
        rows.append(
            _xrow(
                overlay,
                f"User sase_extra_{index}.yml",
                location_type="config",
                group="Config files",
            )
        )
    choices, _default = xprompt_location_choices(rows, project="sase")

    digits = [c.hotkey for c in choices if c.hotkey and c.hotkey.isdigit()]
    assert digits == [str(n) for n in range(1, 10)]
    extras = [c for c in choices if c.label.startswith("sase_extra_")]
    assert [c.hotkey for c in extras[:7]] == [str(n) for n in range(3, 10)]
    assert all(c.hotkey is None for c in extras[7:])


def test_disabled_canonical_keeps_letter_but_renders_without_key(
    tmp_path: Path,
) -> None:
    rows = _standard_xrows(tmp_path)
    rows[1] = _xrow(
        tmp_path / "sase.yml",
        "Project sase/sase.yml",
        location_type="config",
        group="Config files",
        disabled_reason="migrate legacy project config first",
    )
    choices, _default = xprompt_location_choices(rows, project="sase")

    by_label = _by_label(choices)
    project_config = by_label["Project config"]
    assert project_config.disabled_reason == "migrate legacy project config first"
    # The canonical letter is retained so the modal can report *why* the
    # usual key is unavailable; it renders as · with no hint entry.
    assert project_config.hotkey == "P"
    assert not project_config.is_default


def test_hidden_non_canonical_disabled_rows(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    rows.append(
        _xrow(
            tmp_path / "broken.yml",
            "User sase_broken.yml",
            location_type="config",
            group="Config files",
            disabled_reason="read-only",
        )
    )
    choices, _default = xprompt_location_choices(rows, project="sase")

    assert "sase_broken.yml" not in _by_label(choices)


def test_plugin_rows_collapsed_without_hotkeys(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    rows.append(
        _xrow(
            plugin,
            "Plugin (demo) xprompts/",
            group="Plugin directories",
        )
    )
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    rows.append(
        _xrow(
            builtin,
            "Built-in xprompts/",
            group="Built-in (dev)",
            builtin=True,
        )
    )
    choices, _default = xprompt_location_choices(rows, project="sase")

    plugin_choices = [c for c in choices if c.collapsed_group]
    assert len(plugin_choices) == 2
    assert all(c.hotkey is None for c in plugin_choices)
    assert all(c.section == "Plugins & built-in" for c in plugin_choices)
    assert choices[-2].section == "Plugins & built-in"


def test_xprompt_default_ladder_current_then_last_used(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    project_dir = str(rows[0].location.path)
    home_dir = str(rows[3].location.path)

    choices, default = xprompt_location_choices(
        rows, project="sase", last_used_path=home_dir
    )
    assert default == home_dir
    assert _by_label(choices)["Home xprompts"].badges == ("★ last used",)

    choices, default = xprompt_location_choices(
        rows, project="sase", last_used_path=home_dir, current_path=project_dir
    )
    assert default == project_dir
    assert _by_label(choices)["Project xprompts"].badges == ("★ current",)


def test_xprompt_home_mode_skips_project_default(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    choices, default = xprompt_location_choices(rows, project="sase", home_mode=True)

    assert default == str(rows[3].location.path)
    assert _by_label(choices)["Home xprompts"].badges == ("★ default",)


def test_xprompt_stale_last_used_falls_through(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    choices, default = xprompt_location_choices(
        rows, project="sase", last_used_path="/nonexistent/path"
    )

    assert default == str(rows[0].location.path)


def test_xprompt_current_matches_resolved_write_path(
    tmp_path: Path, monkeypatch
) -> None:
    rows = _standard_xrows(tmp_path)
    project_dir = str(rows[0].location.path)
    monkeypatch.setattr(
        choices_mod,
        "resolve_xprompt_write_target",
        lambda path: type(
            "_Target", (), {"write_path": "SOURCE", "via_chezmoi": False}
        )(),
    )
    choices, default = xprompt_location_choices(
        rows, project="sase", current_path="SOURCE"
    )

    assert default == project_dir
    assert _by_label(choices)["Project xprompts"].badges == ("★ current",)


def test_xprompt_has_name_badges_and_previews(tmp_path: Path) -> None:
    rows = _standard_xrows(tmp_path)
    rows[0] = _xrow(
        tmp_path / "proj",
        "Project sase/xprompts/",
        names=frozenset({"review"}),
        namespace="sase",
    )
    choices, _default = xprompt_location_choices(rows, project="sase", name="review")

    by_label = _by_label(choices)
    assert "has #review" in by_label["Project xprompts"].badges
    assert "called as #sase/review" in by_label["Project xprompts"].preview
    assert "1 xprompts here" in by_label["Project xprompts"].preview
    assert "xprompts.review" in by_label["Project config"].preview

    choices, _default = xprompt_location_choices(rows, project="sase")
    assert "called as #sase/<name>" in _by_label(choices)["Project xprompts"].preview
    assert "xprompts.<name>" in _by_label(choices)["Project config"].preview


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
