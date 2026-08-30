"""Tests scoping the generated task-type memory web to managed project repos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main.init_memory import root_rendering_task_types as task_types_rendering
from sase.main.parser import create_parser
from sase.memory.cli_read import handle_memory_read_command
from sase.task_types._models import (
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)
from sase.task_types.detail import task_type_detail, task_type_detail_to_json
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    short_note,
    write,
)

_GENERATED_TASK_TYPES_BODY = (
    "# Task Bead Types\n\n"
    "Stale generated catalog from an older SASE.\n\n"
    "## Types\n\n"
    "No agent-creatable task types are registered.\n"
)
_HAND_AUTHORED_TASK_TYPES_BODY = (
    "# Custom Task Catalog\n\nHand-authored home task types.\n"
)


def _fake_record(
    slug: str,
    label: str,
    *,
    source: str = "builtin",
    package: str = "sase",
    agent_creatable: bool = True,
    spec_overrides: dict[str, Any] | None = None,
) -> TaskTypeRecord:
    spec: dict[str, Any] = {
        "task_type": slug,
        "label": label,
        "summary": f"{label} summary.",
        "when_to_use": f"File one when {label.lower()} applies.",
        "glyph": "?",
        "accent_color": "#5FAFFF",
        "agent_creatable": agent_creatable,
        "fields": [],
    }
    spec.update(spec_overrides or {})
    return TaskTypeRecord(
        task_type=slug,
        spec=spec,
        digest="b" * 64,
        provenance=TaskTypeProvenance(
            source=source,  # type: ignore[arg-type]
            name=package,
            package=package,
            version="1.0.0",
            builtin=source == "builtin",
        ),
        resolved_glyph=str(spec.get("glyph") or "?"),
        resolved_accent_color=str(spec.get("accent_color") or "#5FAFFF"),
    )


def _registry(*records: TaskTypeRecord) -> TaskTypeRegistry:
    return TaskTypeRegistry(records=records, diagnostics=())


def test_home_root_omits_task_types_memory_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0

    assert (project_root / "sase" / "memory" / "task_types.md").exists()
    assert (project_root / "sase" / "memory" / "task_types" / "bug.md").exists()
    assert (project_root / "sase" / "task_types.json").exists()
    assert not (home_root / "sase" / "memory" / "task_types.md").exists()
    assert not (home_root / "sase" / "memory" / "task_types").exists()
    assert not (home_root / "sase" / "task_types.json").exists()

    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    project_agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Task Bead Types" not in home_agents
    assert "Task Bead Types" in project_agents

    assert plan_memory().actions == ()


def test_project_root_writes_task_type_web_descriptor_and_strands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0

    descriptor = project_root / "sase" / "memory" / "task_types.md"
    strand = project_root / "sase" / "memory" / "task_types" / "bug.md"
    descriptor_text = descriptor.read_text(encoding="utf-8")
    assert "web: true" in descriptor_text
    assert "roster: list" in descriptor_text
    assert "strand_noun: task type" in descriptor_text
    assert "- **Bug** (`bug`)" in descriptor_text

    strand_text = strand.read_text(encoding="utf-8")
    assert "keyword: Bug" in strand_text
    assert "generated_by: sase.task_types.generated-strand.v1" in strand_text
    assert "## Identity" in strand_text
    assert "- Task type: `bug`" in strand_text
    assert "## Related Task Types" in strand_text
    assert "- [[task_types/ci]]" in strand_text
    assert "- [[task_types/flake]]" in strand_text
    assert "[[task_types/bug]]" not in strand_text
    assert "## Fields" in strand_text
    assert "**Field `location`**" in strand_text
    assert "## Body Template" in strand_text
    assert "```markdown\n## Bug\n" in strand_text
    assert "## Provenance" in strand_text
    assert "Run `sase bead task-type show bug`" not in strand_text

    feature_text = (
        project_root / "sase" / "memory" / "task_types" / "feature.md"
    ).read_text(encoding="utf-8")
    assert "## Related Task Types" not in feature_text

    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    capsys.readouterr()
    handle_memory_read_command(
        create_parser().parse_args(
            [
                "memory",
                "read",
                "task_types:bug",
                "-r",
                "Need generated task-type detail",
            ]
        )
    )
    read_out = capsys.readouterr().out
    assert "MEMORY WEB: task_types" in read_out
    assert "# Bug" in read_out
    assert "## Identity" in read_out
    assert "- Task type: `bug`" in read_out
    assert "## Body Template" in read_out

    assert plan_memory().actions == ()


def test_generated_task_type_strand_represents_shared_show_detail() -> None:
    record = _fake_record(
        "audit",
        "Audit",
        source="plugin",
        package="sase-audit",
        agent_creatable=False,
        spec_overrides={
            "summary": "A task type for audit findings.",
            "when_to_use": "File one when an audit finding needs remediation.",
            "create_refusal": "Use the audit importer instead.",
            "fields": [
                {
                    "name": "severity",
                    "label": "Severity",
                    "type": "enum",
                    "required": True,
                    "role": ["data", "template"],
                    "help": "Audit severity",
                    "values": ["low", "high"],
                },
                {
                    "name": "score",
                    "label": "Score",
                    "type": "integer",
                    "required": False,
                    "role": ["data"],
                    "help": "Bounded audit score",
                    "minimum": 1,
                    "maximum": 10,
                },
                {
                    "name": "evidence",
                    "label": "Evidence",
                    "type": "string",
                    "required": True,
                    "help": "Evidence locator",
                    "pattern": r"\S+",
                    "max_length": 120,
                },
            ],
            "body_template": "## Audit\n\n{{ evidence }}\n",
            "triage": {"min_plus_ones": 3},
        },
    )

    strand = task_types_rendering._render_task_type_strand_content(record)
    detail_payload = task_type_detail_to_json(task_type_detail(record))
    flat = " ".join(strand.split())

    assert "generated_by: sase.task_types.generated-strand.v1" in strand
    for expected in (
        detail_payload["task_type"],
        detail_payload["label"],
        detail_payload["glyph"],
        detail_payload["accent_color"],
        detail_payload["summary"],
        detail_payload["when_to_use"],
        detail_payload["create_refusal"],
        detail_payload["digest"],
        detail_payload["schema_version"],
        detail_payload["triage"]["min_plus_ones"],
        detail_payload["provenance"]["label"],
        detail_payload["provenance"]["source"],
        detail_payload["provenance"]["package"],
    ):
        assert str(expected) in flat
    # The installed distribution version is the one detail field the strand
    # must not carry: it changes on every release bump while the committed
    # file does not, which would make the drift gate red on every release.
    assert "- Version:" not in strand
    assert detail_payload["provenance"]["version"] not in strand
    assert "Agent creatable: no" in flat
    for field in detail_payload["fields"]:
        assert f"Field `{field['name']}`" in flat
        for key, value in field.items():
            if key == "required":
                assert f"Required: {'yes' if value else 'no'}" in flat
                continue
            if key == "role":
                for role in value:
                    assert f"`{role}`" in flat
                continue
            if key == "values":
                for item in value:
                    assert f"`{item}`" in flat
                continue
            assert str(value) in flat
    assert "```markdown\n## Audit\n\n{{ evidence }}\n```" in strand
    assert "## Related Task Types" not in strand


def test_related_task_types_section_lists_matching_catalog_types_by_slug() -> None:
    alpha = _fake_record(
        "alpha",
        "Alpha",
        spec_overrides={
            "summary": "Mentions the zeta type.",
            "when_to_use": "Do not use this for a Zeta, a confirmed CI failure.",
            "create_refusal": "Use beta instead of inventing a new slug.",
        },
    )
    beta = _fake_record("beta", "Beta")
    ci = _fake_record("ci", "CI failure")
    zeta = _fake_record("zeta", "Zeta")
    unused = _fake_record("unused", "Unused")
    catalog = (zeta, unused, ci, beta, alpha)

    strand = task_types_rendering._render_task_type_strand_content(
        alpha, catalog=catalog
    )

    related_block = strand.split("## Related Task Types", 1)[1].split("## Fields", 1)[0]
    assert related_block.index("[[task_types/beta]]") < related_block.index(
        "[[task_types/ci]]"
    )
    assert related_block.index("[[task_types/ci]]") < related_block.index(
        "[[task_types/zeta]]"
    )
    assert "[[task_types/alpha]]" not in strand
    assert "[[task_types/unused]]" not in strand
    reversed_catalog = tuple(reversed(catalog))
    again = task_types_rendering._render_task_type_strand_content(
        alpha, catalog=reversed_catalog
    )
    assert again == strand


def test_related_task_types_section_omitted_when_nothing_matches() -> None:
    lone = _fake_record(
        "lone",
        "Lone",
        spec_overrides={
            "summary": "A lone type that names only itself.",
            "when_to_use": "File a lone when the work is a lone task.",
            "create_refusal": "Do not refile a lone as a social accident.",
        },
    )
    ci = _fake_record("ci", "CI failure")
    flake = _fake_record("flake", "Flaky test")
    strand = task_types_rendering._render_task_type_strand_content(
        lone, catalog=(lone, ci, flake)
    )

    assert "## Related Task Types" not in strand
    assert "[[task_types/ci]]" not in strand
    assert "[[task_types/flake]]" not in strand
    assert "[[task_types/lone]]" not in strand


def test_generated_task_type_web_uses_committed_agent_creatable_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builtin = _fake_record("bug", "Bug")
    project = _fake_record("project", "Project", source="project", package="project")
    required_plugin = _fake_record(
        "github", "GitHub", source="plugin", package="sase-github"
    )
    optional_plugin = _fake_record(
        "linear", "Linear", source="plugin", package="sase-linear"
    )
    uncreatable = _fake_record(
        "flag",
        "Feature flag",
        source="project",
        package="project",
        agent_creatable=False,
    )
    monkeypatch.setattr(
        task_types_rendering,
        "get_task_type_registry",
        lambda: _registry(
            builtin,
            project,
            required_plugin,
            optional_plugin,
            uncreatable,
        ),
    )
    monkeypatch.setattr(
        "sase.task_types.snapshot._project_required_plugin_packages",
        lambda: frozenset({"sase-github"}),
    )

    source, error = task_types_rendering._render_generated_task_types_web_sources()

    assert error is None
    assert source is not None
    assert [strand.slug for strand in source.strands] == ["bug", "github", "project"]
    assert "linear" not in source.descriptor_content
    assert "flag" not in source.descriptor_content
    strand_text = "\n".join(strand.content for strand in source.strands)
    assert "- Task type: `github`" in strand_text
    assert "sase-github" in strand_text
    assert "- Task type: `linear`" not in strand_text
    assert "- Task type: `flag`" not in strand_text


def test_retirement_deletes_stale_task_type_strand_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    real_records = task_types_rendering._agent_creatable_task_type_records
    monkeypatch.setattr(
        task_types_rendering,
        "_agent_creatable_task_type_records",
        lambda: (*real_records(), _fake_record("zzz_temp", "Temp Type")),
    )

    assert run_handler() == 0

    stale_strand = project_root / "sase" / "memory" / "task_types" / "zzz_temp.md"
    assert stale_strand.exists()

    monkeypatch.setattr(
        task_types_rendering, "_agent_creatable_task_type_records", real_records
    )

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}
    assert plan.blockers == ()
    assert ("delete", stale_strand) in changes

    assert run_handler() == 0
    assert not stale_strand.exists()
    assert plan_memory().actions == ()


def test_retirement_deletes_legacy_pointer_task_type_strand_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_handler() == 0
    assert plan_memory().actions == ()

    legacy = project_root / "sase" / "memory" / "task_types" / "zzz_legacy.md"
    write(
        legacy,
        "---\nkeyword: Legacy\nsummary: Old generated strand.\n---\n\n"
        "Run `sase bead task-type show zzz_legacy` for the full field list, "
        "validators, and body template.\n",
    )

    plan = plan_memory()
    assert plan.blockers == ()
    assert ("delete", legacy) in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_handler() == 0
    assert not legacy.exists()
    assert plan_memory().actions == ()


def test_retirement_leaves_hand_authored_task_type_strand_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0

    rogue = project_root / "sase" / "memory" / "task_types" / "rogue.md"
    write(
        rogue,
        "---\nkeyword: Rogue\nsummary: Hand-authored.\n---\n\nNot generated.\n",
    )

    plan = plan_memory()
    assert plan.blockers == ()
    assert ("delete", rogue) not in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_handler() == 0
    assert rogue.exists()


def test_retirement_deletes_generated_home_task_types_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(home_root / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')

    assert run_handler() == 0

    task_types_path = home_root / "sase" / "memory" / "task_types.md"
    write(task_types_path, short_note(_GENERATED_TASK_TYPES_BODY))

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}

    assert plan.blockers == ()
    assert ("delete", task_types_path) in changes
    assert not any("unreferenced memory file" in blocker for blocker in plan.blockers)

    assert run_handler() == 0

    assert not task_types_path.exists()
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Task Bead Types" not in home_agents
    assert plan_memory().actions == ()


def test_retirement_leaves_hand_authored_home_task_types_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(home_root / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')

    assert run_handler() == 0

    task_types_path = home_root / "sase" / "memory" / "task_types.md"
    write(task_types_path, short_note(_HAND_AUTHORED_TASK_TYPES_BODY))

    plan = plan_memory()
    assert plan.blockers == ()
    assert ("delete", task_types_path) not in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_handler() == 0

    assert task_types_path.exists()
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Custom Task Catalog" in home_agents
    assert "Task Bead Types" not in home_agents
