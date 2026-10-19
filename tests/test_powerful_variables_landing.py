"""Landing guards for the published powerful-variable contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# The sase-core release that first published the powerful-variable bindings.
POWERFUL_VARIABLE_CORE_FLOOR = (0, 27, 9)
_CORE_FLOOR_RE = re.compile(
    r"^sase-core-rs(?:==|>=)(\d+(?:\.\d+)*)(?:,<\d+(?:\.\d+)*)?$"
)


def _declared_core_floor() -> tuple[int, ...]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency in data["project"]["dependencies"]:
        match = _CORE_FLOOR_RE.match(dependency)
        if match is not None:
            return tuple(int(part) for part in match.group(1).split("."))
    raise AssertionError("sase-core-rs dependency is missing from pyproject.toml")


def test_sase_core_rs_floor_is_published_powerful_variable_release() -> None:
    # Compare rather than pin: `tools/ratchet_core_pin` raises this pin on
    # the release branch, so an exact-string guard would fail every ratchet.
    assert _declared_core_floor() >= POWERFUL_VARIABLE_CORE_FLOOR


def test_output_variables_and_generated_cli_document_sase_var_contract() -> None:
    topic = (ROOT / "docs/reference/agents/output-variables.md").read_text(
        encoding="utf-8"
    )
    cli = (ROOT / "docs/reference/cli/var.md").read_text(encoding="utf-8")
    section = topic + "\n" + cli
    flat = " ".join(section.split())

    for required in [
        "`sase var get`",
        "`sase var get '<AGENT_NAME>'`",
        "`sase var get SELECTOR [...]`",
        "`sase var list`",
        "`sase var set KEY=VALUE [...]`",
        "Snapshot reads accept `--format pretty` or `json`; selectors also accept `raw` and `jsonl`",
        "--value-json JSON",
        "[SCOPE.]KEY[PATH ...]",
        "`--format raw` prints one",
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


def test_published_docs_do_not_restore_var_show() -> None:
    skill = ROOT / "src/sase/macros/skills/sase_var.md"
    assert "sase var show" not in skill.read_text(encoding="utf-8")

    for path in sorted((ROOT / "docs").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert "sase var show" not in text, path.relative_to(ROOT)
