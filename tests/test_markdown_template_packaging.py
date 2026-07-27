"""Distribution guard for generated-Markdown source templates."""

from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile


def test_wheel_contains_generated_markdown_templates(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(tmp_path),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("sase-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert {
        "sase/main/init_memory/templates/memory-sase.template.md",
        "sase/main/init_memory/templates/memory-README.template.md",
        "sase/sdd/templates/README.md",
        "sase/sdd/templates/plans-README.md",
        "sase/sdd/templates/research-README.md",
        "sase/sdd/templates/sidecar-beads-README.md",
        "sase/sdd/templates/sidecar-plans-README.md",
        "sase/sdd/templates/sidecar-research-README.md",
        "sase/xprompts/skills/SKILL.frame.template.md",
    } <= names
