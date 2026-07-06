import json
from pathlib import Path


def agent_dir(tmp_path: Path) -> Path:
    artifacts_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260507123456"
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
