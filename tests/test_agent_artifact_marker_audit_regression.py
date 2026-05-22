"""Synthetic regression coverage for the agent marker audit scanners."""

from __future__ import annotations

from pathlib import Path

from tests._agent_artifact_marker_audit_helpers import (
    _artifact_directory_operation_contexts,
    _marker_mutation_contexts,
    _path_passing_contexts,
)


def test_audit_catches_planted_violations(tmp_path: Path) -> None:
    """Plant one violation per pattern and confirm each scanner fires."""
    fake_src = tmp_path / "src" / "sase" / "fake_audit_module"
    fake_src.mkdir(parents=True)
    (fake_src / "__init__.py").write_text("", encoding="utf-8")

    (fake_src / "direct_mutation.py").write_text(
        '"""Plants a direct tracked-marker mutation via Path.write_bytes."""\n\n'
        "from pathlib import Path\n\n\n"
        "def plant_write_bytes(artifact_dir: Path) -> None:\n"
        '    (artifact_dir / "agent_meta.json").write_bytes(b"{}")\n',
        encoding="utf-8",
    )
    (fake_src / "dir_op.py").write_text(
        '"""Plants a whole-directory rmtree."""\n\n'
        "import shutil\n\n\n"
        "def plant_rmtree(artifact_dir) -> None:\n"
        "    shutil.rmtree(artifact_dir)\n",
        encoding="utf-8",
    )
    (fake_src / "path_passing.py").write_text(
        '"""Plants a path-passing site handing a marker path to an unknown helper."""\n\n'
        "from pathlib import Path\n\n\n"
        "def plant_path_passing(artifact_dir: Path) -> None:\n"
        '    unknown_marker_consumer(artifact_dir / "running.json")\n\n\n'
        "def unknown_marker_consumer(path) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    mutation_contexts = _marker_mutation_contexts(tmp_path)
    assert (
        "src/sase/fake_audit_module/direct_mutation.py:plant_write_bytes"
        in mutation_contexts
    )

    dir_op_contexts = _artifact_directory_operation_contexts(tmp_path)
    assert "src/sase/fake_audit_module/dir_op.py:plant_rmtree" in dir_op_contexts

    path_passing = _path_passing_contexts(tmp_path)
    assert (
        "src/sase/fake_audit_module/path_passing.py:plant_path_passing" in path_passing
    )
