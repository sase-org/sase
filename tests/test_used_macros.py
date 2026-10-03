"""Tests for macro usage metadata capture."""

from __future__ import annotations

import json
from pathlib import Path

from sase.main.query_handler._embedded_workflows import (
    expand_embedded_workflows_in_query,
)
from sase.macro.models import Macro
from sase.macro.tags import MacroTag
from sase.macro.used_macros import collect_used_macros, write_used_macros
from sase.macro.workflow_models import Workflow, WorkflowStep


def _part(name: str, *, tags: frozenset[MacroTag] = frozenset()) -> Macro:
    return Macro(name=name, content=f"{name} body", tags=tags)


def _workflow(
    name: str,
    *,
    tags: frozenset[MacroTag] = frozenset(),
) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="main", prompt_part=f"{name} body")],
        tags=tags,
    )


def _patch_catalogs(
    monkeypatch,
    *,
    parts: dict[str, Macro] | None = None,
    workflows: dict[str, Workflow] | None = None,
) -> None:
    import sase.macro.used_macros as used_macros

    monkeypatch.setattr(used_macros, "get_all_macros", lambda: parts or {})
    monkeypatch.setattr(used_macros, "get_all_workflows", lambda: workflows or {})
    monkeypatch.setattr(used_macros, "resolve_macro_aliases", lambda prompt: prompt)
    monkeypatch.setattr(
        used_macros,
        "normalize_vcs_underscore_refs",
        lambda prompt: prompt,
    )


def test_collect_used_macros_mixed_parts_workflows_and_named_args(
    monkeypatch,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"review_checklist": _part("review_checklist")},
        workflows={
            "propose": _workflow("propose"),
            "cl": _workflow("cl"),
        },
    )

    result = collect_used_macros(
        "Run #propose(note=blah) then #cl and #review_checklist"
    )

    assert result == [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {"note": "blah"},
            "tags": [],
        },
        {
            "name": "cl",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]


def test_collect_used_macros_uses_kind_specific_arg_parsing(monkeypatch) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"part": _part("part")},
        workflows={"deploy": _workflow("deploy")},
    )

    result = collect_used_macros("#deploy:staging,prod and #part:hello+world")

    assert result[0]["name"] == "deploy"
    assert result[0]["positional"] == ["staging", "prod"]
    assert result[1]["name"] == "part"
    assert result[1]["positional"] == ["hello world"]


def test_collect_used_macros_dedupes_and_skips_fenced_disabled_unknown(
    monkeypatch,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"review": _part("review")},
        workflows={"cl": _workflow("cl")},
    )
    prompt = (
        "#cl #unknown #cl\n"
        "```text\n#cl\n```\n"
        "%xprompts_enabled:false\n"
        "#review\n"
        "%xprompts_enabled:true\n"
        "#review\n"
    )

    result = collect_used_macros(prompt)

    assert [(item["name"], item["kind"]) for item in result] == [
        ("cl", "workflow"),
        ("review", "part"),
    ]


def test_collect_used_macros_resolves_aliases(monkeypatch) -> None:
    import sase.macro.used_macros as used_macros

    _patch_catalogs(monkeypatch, parts={"review": _part("review")})
    monkeypatch.setattr(
        used_macros,
        "resolve_macro_aliases",
        lambda prompt: prompt.replace("#rv", "#review"),
    )

    result = collect_used_macros("Run #rv")

    assert result[0]["name"] == "review"
    assert result[0]["kind"] == "part"


def test_collect_used_macros_prefers_workflow_on_name_collision(
    monkeypatch,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"ship": _part("ship", tags=frozenset({MacroTag.crs}))},
        workflows={"ship": _workflow("ship", tags=frozenset({MacroTag.vcs}))},
    )

    result = collect_used_macros("#ship")

    assert result == [
        {
            "name": "ship",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": ["vcs"],
        }
    ]


def test_collect_used_macros_prepends_swarm_with_catalog_tags(
    monkeypatch,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={
            "research": _part("research"),
            "research_swarm": _part(
                "research_swarm",
                tags=frozenset({MacroTag.crs, MacroTag.mentor}),
            ),
        },
    )

    result = collect_used_macros(
        "Run #research",
        swarm_macros=["research_swarm"],
    )

    assert result == [
        {
            "name": "research_swarm",
            "kind": "swarm",
            "positional": [],
            "named": {},
            "tags": ["crs", "mentor"],
        },
        {
            "name": "research",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]


def test_collect_used_macros_records_unknown_swarm(monkeypatch) -> None:
    _patch_catalogs(monkeypatch)

    result = collect_used_macros(
        "Rendered swarm segment with no references",
        swarm_macros=["removed_swarm"],
    )

    assert result == [
        {
            "name": "removed_swarm",
            "kind": "swarm",
            "positional": [],
            "named": {},
            "tags": [],
        }
    ]


def test_collect_used_macros_upgrades_lexical_swarm_without_duplicate(
    monkeypatch,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={
            "research_swarm": _part(
                "research_swarm",
                tags=frozenset({MacroTag.crs}),
            )
        },
    )

    result = collect_used_macros(
        "#research_swarm:large #research_swarm:small",
        swarm_macros=["research_swarm"],
    )

    assert result == [
        {
            "name": "research_swarm",
            "kind": "swarm",
            "positional": [],
            "named": {},
            "tags": ["crs"],
        }
    ]


def test_collect_used_macros_preserves_nested_swarm_order(monkeypatch) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={
            "outer": _part("outer"),
            "inner": _part("inner"),
        },
    )

    result = collect_used_macros(
        "Rendered nested segment",
        swarm_macros=["outer", "inner", "outer"],
    )

    assert [(record["name"], record["kind"]) for record in result] == [
        ("outer", "swarm"),
        ("inner", "swarm"),
    ]


def test_collect_used_macros_without_swarm_provenance_is_unchanged(
    monkeypatch,
) -> None:
    _patch_catalogs(monkeypatch, parts={"research": _part("research")})

    result = collect_used_macros("Run #research")

    assert [(record["name"], record["kind"]) for record in result] == [
        ("research", "part")
    ]


def test_write_used_macros_writes_shared_and_step_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"review": _part("review")},
        workflows={"cl": _workflow("cl")},
    )

    records = write_used_macros(tmp_path, "#cl #review", step_name="main")

    assert json.loads((tmp_path / "macros.json").read_text()) == records
    assert json.loads((tmp_path / "macros_main.json").read_text()) == records


def test_write_used_macros_keeps_swarm_provenance_out_of_step_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={
            "research": _part("research"),
            "research_swarm": _part("research_swarm"),
        },
    )

    records = write_used_macros(
        tmp_path,
        "#research",
        step_name="main",
        swarm_macros=["research_swarm"],
    )

    assert json.loads((tmp_path / "macros.json").read_text()) == records
    assert [
        (record["name"], record["kind"])
        for record in json.loads((tmp_path / "macros_main.json").read_text())
    ] == [("research", "part")]


def test_write_used_macros_step_only_preserves_existing_shared(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={"plan": _part("plan"), "review": _part("review")},
    )

    # Launch boundary captures the root prompt metadata first.
    launch_records = write_used_macros(tmp_path, "#plan")
    assert [r["name"] for r in launch_records] == ["plan"]

    # Step execution writes its own file but must not clobber the shared file.
    step_records = write_used_macros(
        tmp_path, "#review", step_name="s1", step_only=True
    )

    assert [r["name"] for r in step_records] == ["review"]
    assert json.loads((tmp_path / "macros_s1.json").read_text()) == step_records
    # Shared file still holds launch-boundary metadata (#plan), not the step's.
    assert json.loads((tmp_path / "macros.json").read_text()) == launch_records


def test_write_used_macros_step_only_seeds_shared_when_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(monkeypatch, parts={"plan": _part("plan")})

    # No launch boundary wrote macros.json (mirrors the foreground/named
    # workflow paths), so the step seeds the shared file and writes its own.
    records = write_used_macros(tmp_path, "#plan", step_name="main", step_only=True)

    assert json.loads((tmp_path / "macros.json").read_text()) == records
    assert json.loads((tmp_path / "macros_main.json").read_text()) == records


def test_expand_embedded_workflows_in_query_writes_used_macros(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_write(
        artifacts_dir: str,
        raw_prompt: str,
        *,
        step_only: bool = False,
    ) -> None:
        calls.append((artifacts_dir, raw_prompt, step_only))

    monkeypatch.setattr(
        "sase.macro.used_macros.write_used_macros",
        fake_write,
    )
    monkeypatch.setattr("sase.macro.loader.get_all_workflows", lambda: {})
    monkeypatch.setattr(
        "sase.macro._parsing.normalize_vcs_underscore_refs",
        lambda prompt: prompt,
    )

    expanded, post_workflows = expand_embedded_workflows_in_query(
        "#review",
        artifacts_dir=str(tmp_path),
    )

    assert expanded == "#review"
    assert post_workflows == []
    assert calls == [(str(tmp_path), "#review", False)]


def test_expand_embedded_workflows_preserves_existing_macro_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(
        monkeypatch,
        parts={
            "research_swarm": _part("research_swarm"),
            "review": _part("review"),
        },
    )
    monkeypatch.setattr("sase.macro.loader.get_all_workflows", lambda: {})
    launch_records = write_used_macros(
        tmp_path,
        "Rendered swarm segment",
        swarm_macros=["research_swarm"],
    )

    expanded, post_workflows = expand_embedded_workflows_in_query(
        "#review",
        artifacts_dir=str(tmp_path),
        preserve_existing_macro_metadata=True,
    )

    assert expanded == "#review"
    assert post_workflows == []
    assert json.loads((tmp_path / "macros.json").read_text()) == launch_records


def test_expand_embedded_workflows_preservation_seeds_macro_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(monkeypatch, parts={"review": _part("review")})
    monkeypatch.setattr("sase.macro.loader.get_all_workflows", lambda: {})

    expanded, post_workflows = expand_embedded_workflows_in_query(
        "#review",
        artifacts_dir=str(tmp_path),
        preserve_existing_macro_metadata=True,
    )

    assert expanded == "#review"
    assert post_workflows == []
    records = json.loads((tmp_path / "macros.json").read_text())
    assert [record["name"] for record in records] == ["review"]


def test_write_used_macros_writes_no_legacy_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _patch_catalogs(monkeypatch, parts={"review": _part("review")})

    write_used_macros(tmp_path, "#review", step_name="main")

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["macros.json", "macros_main.json"]
