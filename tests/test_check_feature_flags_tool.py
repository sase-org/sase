"""Tests for the feature-flag registry and bead-integrity lint tool."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from datetime import date
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from sase.feature_flags import FeatureFlag, FeatureFlagDefinition
from sase.feature_flags.schema import feature_flags_schema_block

from tests.feature_flags._helpers import definitions, demo_flag


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_feature_flags"


@pytest.fixture(autouse=True)
def _restore_sys_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # The tool inserts `src` onto sys.path at import time so it keeps working
    # when run standalone. _load_tool() re-executes that module on every
    # call, so without this the insert accumulates across tests.
    monkeypatch.syspath_prepend(str(ROOT / "src"))


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_feature_flags_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "check_feature_flags_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.14) resolve annotations via sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_executable(path: Path, text: str) -> Path:
    _write(path, text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _rules(findings: list[Any]) -> list[int]:
    return [finding.rule for finding in findings]


def _broken_flag(
    key: str = "broken_flag",
    *,
    kind: str = "beta",
    bead: str | None = None,
) -> FeatureFlagDefinition:
    return FeatureFlagDefinition(
        key=cast(FeatureFlag, key),
        kind=cast(Any, kind),
        description=f"Description for {key}",
        bead=bead,
    )


def _schema_document(defs: dict[str, FeatureFlagDefinition]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"feature_flags": feature_flags_schema_block(defs)},
    }


def _bead(
    tool: ModuleType,
    *,
    bead_id: str = "sase-nb.test",
    key: str = "demo_flag",
    status: str = "open",
    issue_type: str = "flag",
    remove_by_date: str = "2026-12-01",
    remove_by_release: str = "0.19.0",
    source: str = "flag",
) -> Any:
    return tool.MarkerBead(
        source=source,
        id=bead_id,
        issue_type=issue_type,
        status=status,
        key=key,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )


def test_tool_script_is_executable() -> None:
    assert TOOL_PATH.exists()
    assert TOOL_PATH.stat().st_mode & 0o111


def test_rule_1_rejects_missing_bead() -> None:
    tool = _load_tool()

    findings = tool.check_definition_metadata(
        definitions(_broken_flag("beta_flag", kind="beta", bead=None))
    )

    assert _rules(findings) == [1]
    assert "beta_flag" in findings[0].message
    assert "must reference its flag bead" in findings[0].message


def test_rule_1_accepts_named_bead() -> None:
    tool = _load_tool()

    assert (
        tool.check_definition_metadata(
            definitions(demo_flag("beta_flag"), demo_flag("sunset_flag", kind="sunset"))
        )
        == []
    )


def test_rule_2_rejects_schema_drift() -> None:
    tool = _load_tool()
    defs = definitions(demo_flag("demo_flag"))
    schema = _schema_document(defs)
    schema["properties"]["feature_flags"]["description"] = "wrong"

    findings = tool.check_schema(schema, defs, schema_path=Path("sase.schema.json"))

    assert _rules(findings) == [2]
    assert "out of sync" in findings[0].message


def test_rule_2_accepts_matching_schema() -> None:
    tool = _load_tool()
    defs = definitions(demo_flag("demo_flag"))

    assert tool.check_schema(_schema_document(defs), defs) == []


def test_rule_3_rejects_flag_with_no_non_test_reference(tmp_path: Path) -> None:
    tool = _load_tool()
    src = _write(
        tmp_path / "src" / "sase" / "feature_flags" / "registry.py",
        "class FeatureFlag:\n    demo_flag = 'demo_flag'\n",
    )

    findings = tool.check_references(
        definitions(demo_flag("demo_flag")),
        [src],
        repo_root=tmp_path,
    )

    assert _rules(findings) == [3]
    assert "demo_flag" in findings[0].message
    assert "no non-test reference" in findings[0].message


def test_rule_3_accepts_feature_flag_attribute_use(tmp_path: Path) -> None:
    tool = _load_tool()
    consumer = _write(
        tmp_path / "src" / "sase" / "consumer.py",
        "from sase.feature_flags import FeatureFlag\n"
        "from sase.feature_flags.snapshot import current_flags\n"
        "\n"
        "def use_flag() -> bool:\n"
        "    return current_flags().enabled(FeatureFlag.demo_flag)\n",
    )

    assert (
        tool.check_references(
            definitions(demo_flag("demo_flag")),
            [consumer],
            repo_root=tmp_path,
        )
        == []
    )


def test_rule_4_rejects_import_time_resolution(tmp_path: Path) -> None:
    tool = _load_tool()
    path = _write(
        tmp_path / "src" / "sase" / "bindings.py",
        "from sase.feature_flags.snapshot import current_flags\n"
        "\n"
        "FLAGS = current_flags()\n",
    )

    findings = tool.check_import_time([path])

    assert _rules(findings) == [4]
    assert findings[0].path == path
    assert findings[0].line_number == 3
    assert "current_flags" in findings[0].message


def test_rule_4_allows_function_body_and_skips_guards(tmp_path: Path) -> None:
    tool = _load_tool()
    path = _write(
        tmp_path / "src" / "sase" / "entry.py",
        "from typing import TYPE_CHECKING\n"
        "from sase.feature_flags.snapshot import current_flags\n"
        "from sase.feature_flags import install_process_feature_flags\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    current_flags()\n"
        "\n"
        "def main() -> None:\n"
        "    install_process_feature_flags()\n"
        "    current_flags()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    current_flags()\n",
    )

    assert tool.check_import_time([path]) == []


def test_rule_5_rejects_unregistered_repo_config_key(tmp_path: Path) -> None:
    tool = _load_tool()
    path = _write(
        tmp_path / "src" / "sase" / "default_config.yml",
        "feature_flags:\n  ghost_flag: true\n",
    )

    findings = tool.check_repo_config(definitions(demo_flag("demo_flag")), [path])

    assert _rules(findings) == [5]
    assert "ghost_flag" in findings[0].message
    assert findings[0].path == path


def test_rule_5_accepts_registered_or_absent_keys(tmp_path: Path) -> None:
    tool = _load_tool()
    present = _write(
        tmp_path / "src" / "sase" / "default_config.yml",
        "feature_flags:\n  demo_flag: true\n",
    )
    absent = _write(
        tmp_path / "src" / "plugin" / "default_config.yml",
        "max_running_agents: 4\n",
    )

    assert (
        tool.check_repo_config(definitions(demo_flag("demo_flag")), [present, absent])
        == []
    )


def test_rule_6_rejects_missing_wrong_type_and_key_mismatch() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(
        definitions(
            _broken_flag("missing_flag", bead="sase-nb.missing"),
            _broken_flag("wrong_type", bead="sase-nb.task"),
            _broken_flag("wrong_key", bead="sase-nb.key"),
        )
    )
    beads = [
        _bead(
            tool,
            bead_id="sase-nb.task",
            key="wrong_type",
            issue_type="task",
        ),
        _bead(tool, bead_id="sase-nb.key", key="other_key"),
    ]

    findings = tool.check_bead_status(
        markers,
        beads,
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert 6 in _rules(findings)
    messages = " ".join(finding.message for finding in findings if finding.rule == 6)
    assert "missing bead" in messages
    assert "expected 'flag'" in messages
    assert "whose key is 'other_key'" in messages


def test_rule_6_accepts_matching_flag_bead() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_7_rejects_closed_bead_with_surviving_definition() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    findings = tool.check_bead_status(
        markers,
        [_bead(tool, status="closed")],
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert _rules(findings) == [7]
    assert "closed" in findings[0].message
    assert "demo_flag" in findings[0].message


def test_rule_7_accepts_live_bead_with_definition() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool, status="in_progress")],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_8_rejects_live_orphan_flag_bead() -> None:
    tool = _load_tool()

    findings = tool.check_bead_status(
        (),
        [_bead(tool, bead_id="sase-orphan", key="ghost_flag")],
        today=date(2026, 1, 1),
        release="0.10.0",
    )

    assert _rules(findings) == [8]
    assert "sase-orphan" in findings[0].message
    assert "ghost_flag" in findings[0].message


def test_rule_8_accepts_closed_orphan_and_defined_live_bead() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [
                _bead(tool),
                _bead(tool, bead_id="sase-old", key="retired_flag", status="closed"),
            ],
            today=date(2026, 1, 1),
            release="0.10.0",
        )
        == []
    )


def test_rule_9_warns_when_overdue_and_never_errors() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    findings = tool.check_bead_status(
        markers,
        [_bead(tool)],
        today=date(2026, 12, 2),
        release="0.19.0",
    )

    assert len(findings) == 1
    assert findings[0].rule == 9
    assert findings[0].severity == "warning"
    assert "overdue" in findings[0].message


def test_rule_9_is_silent_when_live_or_soon() -> None:
    tool = _load_tool()
    markers = tool.markers_from_flag_definitions(definitions(demo_flag("demo_flag")))

    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 12, 2),
            release="0.10.0",
        )
        == []
    )
    assert (
        tool.check_bead_status(
            markers,
            [_bead(tool)],
            today=date(2026, 1, 1),
            release="0.19.0",
        )
        == []
    )


def test_second_marker_source_reuses_bead_status_rules() -> None:
    tool = _load_tool()
    markers = [
        tool.MarkerDefinition(
            source="backcompat",
            key="old_api",
            kind="sunset",
            bead="sase-bc.1",
        )
    ]
    beads = [
        _bead(
            tool,
            bead_id="sase-bc.1",
            key="old_api",
            issue_type="task",
            status="closed",
            source="backcompat",
        )
    ]

    findings = tool.check_bead_status(
        markers,
        beads,
        today=date(2026, 1, 1),
        release="0.10.0",
        expected_bead_type="task",
    )

    assert _rules(findings) == [7]
    assert "backcompat" in findings[0].message


def test_static_subset_does_not_query_beads(tmp_path: Path) -> None:
    tool = _load_tool()
    exploding = _write_executable(
        tmp_path / "bd",
        "#!/usr/bin/env bash\nprintf 'should not run\\n' >&2\nexit 99\n",
    )
    src = tmp_path / "src" / "sase"
    _write(src / "default_config.yml", "max_running_agents: 1\n")
    _write(
        src / "config" / "sase.schema.json",
        json.dumps(_schema_document({})) + "\n",
    )
    _write(src / "ok.py", "VALUE = 1\n")

    findings = tool.run_checks(
        repo_root=tmp_path,
        definitions={},
        schema_document=_schema_document({}),
        python_files=[src / "ok.py"],
        config_files=[src / "default_config.yml"],
        bd_command=str(exploding),
        static_only=True,
    )

    assert findings == []


def test_main_static_on_repo_exits_zero() -> None:
    tool = _load_tool()

    assert tool.main(["--static", "--repo-root", str(ROOT)]) == 0


def test_load_flag_beads_reads_list_json(tmp_path: Path) -> None:
    tool = _load_tool()
    script = _write_executable(
        tmp_path / "bd",
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "if sys.argv[1] == 'list':\n"
        "    print(json.dumps({\n"
        "        'results': [{\n"
        "            'id': 'sase-x',\n"
        "            'status': 'open',\n"
        "            'issue_type': 'flag',\n"
        "            'flag': {\n"
        "                'key': 'demo_flag',\n"
        "                'remove_by_date': '2026-12-01',\n"
        "                'remove_by_release': '0.19.0',\n"
        "            },\n"
        "        }]\n"
        "    }))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
    )

    beads = tool.load_flag_beads(tmp_path, str(script))

    assert len(beads) == 1
    assert beads[0].id == "sase-x"
    assert beads[0].key == "demo_flag"


def test_overdue_warning_does_not_fail_main(tmp_path: Path) -> None:
    tool = _load_tool()
    defs = definitions(demo_flag("demo_flag"))
    src = _write(
        tmp_path / "src" / "sase" / "consumer.py",
        "from sase.feature_flags import FeatureFlag\n"
        "\n"
        "def use() -> object:\n"
        "    return FeatureFlag.demo_flag\n",
    )
    findings = tool.run_checks(
        repo_root=tmp_path,
        definitions=defs,
        schema_document=_schema_document(defs),
        python_files=[src],
        config_files=[],
        beads=[_bead(tool)],
        today=date(2026, 12, 2),
        release="0.19.0",
        static_only=False,
    )

    assert [finding.severity for finding in findings] == ["warning"]
    rendered = tool.format_finding(findings[0], tmp_path)
    assert rendered.startswith("warning: ")
    assert "rule 9:" in rendered


def test_empty_registry_full_check_with_no_flag_beads_passes(tmp_path: Path) -> None:
    tool = _load_tool()
    script = _write_executable(
        tmp_path / "bd",
        "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'results': []}))\n",
    )
    src = tmp_path / "src" / "sase"
    _write(src / "ok.py", "VALUE = 1\n")

    findings = tool.run_checks(
        repo_root=tmp_path,
        definitions={},
        schema_document=_schema_document({}),
        python_files=[src / "ok.py"],
        config_files=[],
        bd_command=str(script),
        static_only=False,
    )

    assert findings == []


def test_static_main_ignores_exploding_bd_command(
    tmp_path: Path, monkeypatch: Any
) -> None:
    tool = _load_tool()
    exploding = _write_executable(
        tmp_path / "bd",
        "#!/usr/bin/env bash\nexit 99\n",
    )
    monkeypatch.setenv("BD_COMMAND", str(exploding))

    # main() reads the installed registry, so the fixture must be a real
    # checkout whose schema and call sites match. Static mode must still
    # ignore BD_COMMAND even when that command would explode.
    assert tool.main(["--static", "--repo-root", str(ROOT)]) == 0
