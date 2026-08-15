"""Landing guards for the published powerful-variable contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sase_core_rs_floor_is_published_powerful_variable_release() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]

    assert "sase-core-rs>=0.27.9,<0.28.0" in dependencies


def test_configuration_documents_complete_sase_var_contract() -> None:
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    section = text.split("### `sase var`", 1)[1].split("### `sase telemetry`", 1)[0]
    flat = " ".join(section.split())

    for required in [
        "`sase var get`",
        "`sase var get '<AGENT_NAME>'`",
        "`sase var get SELECTOR [...]`",
        "`sase var list`",
        "`sase var set KEY=VALUE [...]`",
        "-f pretty\\|raw\\|json\\|jsonl",
        "--value-json JSON",
        "[SCOPE.]KEY[PATH ...]",
        "`--format raw` prints",
        "one value only",
        "`--format jsonl` emits one compact JSON object per match",
        "sase var get '<build>' --format json",
        "sase var get build.*",
        "Snapshot mode",
    ]:
        assert required in flat

    assert "sase var show" not in section
    documented = set(re.findall(r"`sase var ([a-z]+)", section))
    assert documented == {"get", "list", "set"}

    table = section.split("| Form", 1)[1].split("\n\n", 1)[0]
    assert table.index("`sase var get`") < table.index("`sase var get '<AGENT_NAME>'`")
    assert table.index("`sase var get '<AGENT_NAME>'`") < table.index(
        "`sase var get SELECTOR [...]`"
    )
    assert table.index("`sase var get SELECTOR [...]`") < table.index("`sase var list`")
    assert table.index("`sase var list`") < table.index(
        "`sase var set KEY=VALUE [...]`"
    )


def test_published_docs_do_not_restore_var_show() -> None:
    for relative in (
        "docs/configuration.md",
        "docs/cli.md",
        "docs/xprompt.md",
        "src/sase/xprompts/skills/sase_var.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "sase var show" not in text, relative
