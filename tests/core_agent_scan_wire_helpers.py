from __future__ import annotations


def record_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_name": "myproj",
        "project_dir": "/tmp/projects/myproj",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/projects/myproj/artifacts/ace-run/20260601010101",
        "timestamp": "20260601010101",
        "has_done_marker": True,
    }
    payload.update(overrides)
    return payload
