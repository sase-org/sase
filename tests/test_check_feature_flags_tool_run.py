"""``run_checks`` / ``main`` coverage for ``tools/check_feature_flags``."""

from __future__ import annotations

import ast
import gc
import json
import weakref
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from tests._check_feature_flags_tool_helpers import (
    ROOT,
    _bead,
    _load_tool,
    _restore_sys_path,
    _schema_document,
    _write,
    _write_executable,
)
from tests.feature_flags._helpers import definitions, demo_flag


# Re-imported so pytest collects the autouse sys.path restore from the helper.
pytestmark = pytest.mark.usefixtures("_restore_sys_path")


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


def test_in_flight_orphan_warning_does_not_fail_main(tmp_path: Path) -> None:
    tool = _load_tool()
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    findings = tool.run_checks(
        repo_root=tmp_path,
        definitions={},
        schema_document=_schema_document({}),
        python_files=[],
        config_files=[],
        beads=[
            _bead(
                tool,
                bead_id="sase-qq",
                key="plugin_catalog_scoped_latest",
                created_at="2026-08-19T01:21:12Z",
                created_by="sase-qn.2",
            )
        ],
        today=date(2026, 8, 19),
        release="0.10.0",
        now=now,
        checkout_committed_at=datetime(2026, 8, 18, tzinfo=UTC),
        static_only=False,
    )

    assert [finding.severity for finding in findings] == ["warning"]
    rendered = tool.format_finding(findings[0], tmp_path)
    assert rendered.startswith("warning: ")
    assert "rule 8:" in rendered


def test_run_checks_drops_each_parsed_tree_before_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Holding every parsed src/ tree at once peaked near 1.7 GB inside a
    # contention-soak worker. Rules 3 and 4 must share one streaming parse.
    tool = _load_tool()
    src = tmp_path / "src" / "sase"
    files = [
        _write(
            src / "consumer.py",
            "from sase.feature_flags import FeatureFlag\n"
            "\n"
            "def use() -> object:\n"
            "    return FeatureFlag.demo_flag\n",
        ),
        _write(
            src / "bindings.py",
            "from sase.feature_flags.snapshot import current_flags\n"
            "\n"
            "FLAGS = current_flags()\n",
        ),
        *(_write(src / f"plain_{index}.py", "VALUE = 1\n") for index in range(4)),
    ]
    real_iter = tool.iter_parsed_python_files
    live: list[weakref.ref[ast.AST]] = []
    parsed = 0
    max_live = 0

    def tracking_iter(paths: Any) -> Iterator[tuple[Path, ast.AST]]:
        nonlocal parsed, max_live
        for path, tree in real_iter(paths):
            gc.collect()
            live[:] = [ref for ref in live if ref() is not None]
            live.append(weakref.ref(tree))
            parsed += 1
            max_live = max(max_live, len(live))
            yield path, tree

    monkeypatch.setattr(tool, "iter_parsed_python_files", tracking_iter)
    defs = definitions(demo_flag("demo_flag"), demo_flag("other_flag"))

    findings = tool.run_checks(
        repo_root=tmp_path,
        definitions=defs,
        schema_document=_schema_document(defs),
        python_files=files,
        config_files=[],
        static_only=True,
    )

    assert parsed == len(files)
    # The caller's loop variable still holds the previous tree while the
    # next one is parsed, so two may be alive; never all of them.
    assert max_live <= 2
    assert [(finding.rule, finding.path) for finding in findings] == [
        (3, None),
        (4, files[1]),
    ]
    assert "'other_flag'" in findings[0].message


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
