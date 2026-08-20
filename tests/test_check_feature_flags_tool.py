"""Static registry, schema, reference, and config rules for the lint tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._check_feature_flags_tool_helpers import (
    TOOL_PATH,
    _broken_flag,
    _load_tool,
    _restore_sys_path,
    _rules,
    _schema_document,
    _write,
)
from tests.feature_flags._helpers import definitions, demo_flag


# Re-imported so pytest collects the autouse sys.path restore from the helper.
pytestmark = pytest.mark.usefixtures("_restore_sys_path")


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
        tmp_path / "plugin" / "default_config.yml",
        "max_running_agents: 4\n",
    )

    assert (
        tool.check_repo_config(definitions(demo_flag("demo_flag")), [present, absent])
        == []
    )
