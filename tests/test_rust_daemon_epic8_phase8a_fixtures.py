"""Phase 8A host-isolation inventory fixture validation."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from sase.llm_provider._hookspec import LLMHookSpec
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.workspace_provider._hookspec import WorkspaceHookSpec


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rust_daemon_epic8_phase8a"


def _read_json(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _hookspec_methods(cls: type) -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def test_operation_inventory_covers_current_pluggy_hooks() -> None:
    inventory = _read_json("operation_inventory.json")
    operations = inventory["operations"]

    by_group = {
        group: {row["name"] for row in operations if row["group"] == group}
        for group in ("sase_llm", "sase_vcs", "sase_workspace")
    }

    assert by_group["sase_llm"] == _hookspec_methods(LLMHookSpec)
    assert by_group["sase_vcs"] == _hookspec_methods(VCSHookSpec)
    assert by_group["sase_workspace"] == _hookspec_methods(WorkspaceHookSpec)

    valid_classes = set(inventory["classification_values"])
    for row in operations:
        assert row["classification"] in valid_classes
        assert row["operation_family"]
        assert isinstance(row["implemented_by"], list)
        assert row["host_isolated_v1"] in {
            "yes",
            "after_runtime",
            "after_manifest",
            "direct_fallback_ok",
        }
        assert row["compatibility_expectation"]


def test_inventory_records_required_entry_points_and_routing_candidates() -> None:
    inventory = _read_json("operation_inventory.json")
    entry_points = inventory["entry_points"]

    assert set(entry_points["sase_llm"]["builtin"]) == {
        "claude",
        "codex",
        "gemini",
        "opencode",
        "qwen",
    }
    assert entry_points["sase_vcs"]["builtin"] == {
        "bare_git": "sase.vcs_provider.plugins.bare_git:BareGitPlugin"
    }
    assert set(entry_points["sase_workspace"]["builtin"]) == {"bare_git", "cd"}
    assert set(entry_points["sase_vcs"]["maintained_external"]) == {"github"}
    assert set(entry_points["sase_workspace"]["maintained_external"]) == {"github"}
    assert set(entry_points["sase_config"]["maintained_external"]) == {"sase_github"}
    assert set(entry_points["sase_xprompts"]["maintained_external"]) == {"sase_github"}

    candidates = inventory["routing_candidates"]
    assert candidates["first_low_risk"]["operation_family"] == "llm.metadata"
    assert candidates["first_high_traffic"]["operation_family"] == "xprompt.catalog"


def test_manifest_fixtures_define_required_v1_policy_fields() -> None:
    fixture = _read_json("compatibility_manifests.json")
    required = set(fixture["required_fields"])
    manifests = fixture["manifests"]

    assert {manifest["plugin_id"] for manifest in manifests} >= {
        "builtin.vcs.bare_git",
        "builtin.workspace.cd",
        "external.github",
        "builtin.llm.claude",
        "builtin.llm.codex",
        "builtin.llm.gemini",
        "builtin.llm.opencode",
        "builtin.llm.qwen",
    }

    for manifest in manifests:
        assert required <= set(manifest)
        assert manifest["manifest_version"] == fixture["manifest_version"]
        assert manifest["entry_points"]
        assert manifest["operation_families"]
        assert manifest["network_policy"]
        assert isinstance(manifest["warm_host_eligible"], bool)
        assert manifest["wasm_compatibility_notes"]


def test_import_command_baselines_cover_phase8a_surfaces() -> None:
    baselines = _read_json("import_command_baselines.json")
    measurements = {row["id"]: row for row in baselines["measurements"]}

    assert set(measurements) == {
        "pure_read_bead_list_open",
        "daemon_status_json",
        "run_preflight_history_list",
        "import_sase_main_parser",
        "import_daemon_read_facade",
        "import_llm_registry",
        "llm_provider_names_metadata",
        "vcs_detect_current_repo",
        "vcs_query_current_branch",
        "workspace_get_workflow_names",
        "xprompt_catalog_all_prompts",
    }
    assert {row["surface"] for row in measurements.values()} >= {
        "pure_read_command",
        "daemon_read_command",
        "sase_run_preflight",
        "llm_metadata_lookup",
        "vcs_detect_query",
        "vcs_query",
        "workspace_metadata_lookup",
        "xprompt_catalog_load",
    }

    for row in measurements.values():
        assert row["runs"] == 3
        assert row["exit_codes"] == [0, 0, 0]
        assert row["min_wall_ms"] <= row["median_wall_ms"] <= row["max_wall_ms"]
