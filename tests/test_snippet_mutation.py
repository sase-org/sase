"""Tests for shared snippet add/update/delete mutations."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.content_layout import resolve_project_config_write_path
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.snippet.catalog import load_snippet_catalog
from sase.snippet.mutation import (
    SnippetConflictError,
    SnippetMutationError,
    SnippetReadOnlyError,
    add_snippet,
    delete_snippet,
    update_snippet,
    upsert_snippet_at_path,
)
from sase.xprompt import glossary_catalog as catalog_mod
from sase.xprompt.models import XPrompt
from sase.xprompt.snippet_config_yaml import snippet_config_digest


def _record(
    project_name: str, workspace: Path, *, display_name: str
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )


def _install_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str | None,
    *,
    display_name: str = "demo",
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    config_path = resolve_project_config_write_path(workspace)
    if body is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(
        catalog_mod,
        "list_project_records",
        lambda *_a, **_k: [
            _record("gh_demo__app", workspace, display_name=display_name)
        ],
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    return config_path


def test_add_creates_snippet_and_preserves_unrelated_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        "# keep\ntimezone: UTC\n",
    )

    outcome = add_snippet(
        "demo",
        "todo",
        "TODO($1)$0",
        target=str(config_path),
    )

    assert outcome.action == "created"
    assert outcome.created is True
    assert outcome.write_path == str(config_path)
    assert "sase snippet add" in outcome.restore_command
    text = config_path.read_text(encoding="utf-8")
    assert "# keep" in text
    assert "timezone: UTC" in text
    loaded = yaml.safe_load(text)
    assert loaded["ace"]["snippets"]["todo"] == "TODO($1)$0"


def test_add_refuses_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        "ace:\n  snippets:\n    todo: |\n      OLD$0\n",
    )

    with pytest.raises(SnippetMutationError, match="already exists"):
        add_snippet("demo", "todo", "NEW$0", target=str(config_path))

    outcome = add_snippet("demo", "todo", "NEW$0", target=str(config_path), force=True)
    assert outcome.action == "replaced"
    assert (
        yaml.safe_load(config_path.read_text(encoding="utf-8"))["ace"]["snippets"][
            "todo"
        ]
        == "NEW$0"
    )


def test_add_refuses_xprompt_shadow_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, "timezone: UTC\n")
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {
            "todo": XPrompt(name="todo", content="from xprompt", snippet=True)
        },
    )

    with pytest.raises(SnippetMutationError, match="already exists"):
        add_snippet("demo", "todo", "from config$0", target=str(config_path))

    outcome = add_snippet(
        "demo",
        "todo",
        "from config$0",
        target=str(config_path),
        force=True,
    )
    assert outcome.action == "shadowed"
    assert "-F" in outcome.restore_command


def test_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, "timezone: UTC\n")
    original = config_path.read_text(encoding="utf-8")

    outcome = add_snippet(
        "demo",
        "todo",
        "TODO$0",
        target=str(config_path),
        dry_run=True,
    )

    assert outcome.dry_run is True
    assert config_path.read_text(encoding="utf-8") == original


def test_stale_digest_raises_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, "ace:\n  snippets: {}\n")
    stale = snippet_config_digest(b"not-the-file")

    with pytest.raises(SnippetConflictError, match="reload and retry"):
        add_snippet(
            "demo",
            "todo",
            "TODO$0",
            target=str(config_path),
            expected_digest=stale,
        )


def test_delete_reveals_shadowed_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        "ace:\n  snippets:\n    todo: |\n      from config$0\n",
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {
            "todo": XPrompt(
                name="todo",
                content="from xprompt",
                snippet=True,
                source_path="xprompts/todo.md",
            )
        },
    )

    outcome = delete_snippet("demo", "todo")

    assert outcome.action == "deleted"
    assert outcome.revealed is not None
    assert outcome.revealed.origin.kind == "xprompt"
    assert outcome.removed_paths == (str(config_path),)
    assert "-F" in outcome.restore_command
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))["ace"]
    snippets = loaded.get("snippets") or {}
    assert "todo" not in snippets
    catalog = load_snippet_catalog("demo")
    assert catalog.entry_for("todo") is not None
    assert catalog.entry_for("todo").origin.kind == "xprompt"


def test_delete_refuses_xprompt_only_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_project(tmp_path, monkeypatch, "timezone: UTC\n")
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {
            "todo": XPrompt(name="todo", content="from xprompt", snippet=True)
        },
    )

    with pytest.raises(SnippetReadOnlyError, match="cannot delete"):
        delete_snippet("demo", "todo")


def test_delete_maps_alias_to_explicit_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(
        tmp_path,
        monkeypatch,
        "ace:\n  snippets:\n    helper: |\n      help$0\n",
    )

    outcome = delete_snippet("demo", "Helper")

    assert outcome.trigger == "helper"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))["ace"]
    assert not (loaded.get("snippets") or {})


def test_update_requires_existing_destination_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, "timezone: UTC\n")

    with pytest.raises(Exception, match="unknown snippet trigger"):
        update_snippet("demo", "todo", "NEW$0", target=str(config_path))


def test_upsert_at_path_rewires_prompt_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "custom.yml"
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.snippet.catalog._config_layer_contributions",
        lambda *_a, **_k: ((), ()),
    )

    outcome = upsert_snippet_at_path(config_path, "saved", "body$0")

    assert outcome.created is True
    assert config_path.is_file()
    assert (
        yaml.safe_load(config_path.read_text(encoding="utf-8"))["ace"]["snippets"][
            "saved"
        ]
        == "body$0"
    )


def test_invalid_trigger_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _install_project(tmp_path, monkeypatch, "timezone: UTC\n")

    with pytest.raises(SnippetMutationError, match="invalid"):
        add_snippet("demo", "bad-name!", "body$0", target=str(config_path))
