from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

from sase.stats.query import query_activity_stats, query_run_stats


def test_query_run_stats_passes_paths_and_request_to_rust(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[object, ...]] = []

    def binding(*args: object) -> dict[str, Any]:
        calls.append(args)
        return {"schema_version": 1}

    monkeypatch.setattr(
        "sase.stats.query.require_rust_binding",
        lambda name: binding if name == "agent_stats_query_runs" else None,
    )
    index = tmp_path / "index.sqlite"

    result = query_run_stats(
        start_ts=10,
        end_ts=20,
        runtime_group_by="tribe",
        bucket_seconds=5,
        top_n=9,
        project="sase",
        work_top_n=17,
        index_path=index,
    )

    assert result == {"schema_version": 1}
    assert calls == [
        (
            str(index),
            {
                "start_ts": 10,
                "end_ts": 20,
                "runtime_group_by": "tribe",
                "bucket_seconds": 5,
                "top_n": 9,
                "project": "sase",
                "work_top_n": 17,
                "xprompt_top_n": 40,
                "xprompt_breakdown_top_n": 5,
                "xprompt_focus": None,
            },
        )
    ]


def test_query_run_stats_passes_xprompt_request_controls(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    requests: list[dict[str, object]] = []

    def binding(_index: str, request: dict[str, object]) -> dict[str, Any]:
        requests.append(request)
        return {}

    monkeypatch.setattr("sase.stats.query.require_rust_binding", lambda _name: binding)

    query_run_stats(
        start_ts=10,
        end_ts=20,
        xprompt_top_n=21,
        xprompt_breakdown_top_n=8,
        xprompt_focus="split_file",
        index_path=tmp_path / "index.sqlite",
    )

    assert requests[0]["xprompt_top_n"] == 21
    assert requests[0]["xprompt_breakdown_top_n"] == 8
    assert requests[0]["xprompt_focus"] == "split_file"


def test_query_activity_stats_uses_home_for_default_index(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def binding(*args: object) -> dict[str, Any]:
        captured["args"] = args
        return {"schema_version": 1}

    monkeypatch.setattr(
        "sase.stats.query.require_rust_binding",
        lambda name: binding if name == "agent_stats_query_activity" else None,
    )

    result = query_activity_stats(
        start_ts=30,
        end_ts=40,
        project="sase",
        home_path=tmp_path,
    )

    assert result == {"schema_version": 1}
    assert captured["args"] == (
        str(tmp_path / "agent_artifact_index.sqlite"),
        str(tmp_path),
        {"start_ts": 30, "end_ts": 40, "top_n": 5, "project": "sase"},
    )


def test_query_run_stats_selects_product_bucket_size(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    requests: list[dict[str, object]] = []

    def binding(_index: str, request: dict[str, object]) -> dict[str, Any]:
        requests.append(request)
        return {}

    monkeypatch.setattr("sase.stats.query.require_rust_binding", lambda _name: binding)

    query_run_stats(start_ts=0, end_ts=48 * 3_600, index_path=tmp_path / "index")
    query_run_stats(
        start_ts=0,
        end_ts=48 * 3_600 + 1,
        index_path=tmp_path / "index",
    )

    assert requests[0]["bucket_seconds"] == 3_600
    assert requests[1]["bucket_seconds"] == 86_400


def test_query_run_stats_passes_new_runtime_groups_and_default_work_controls(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    requests: list[dict[str, object]] = []

    def binding(_index: str, request: dict[str, object]) -> dict[str, Any]:
        requests.append(request)
        return {}

    monkeypatch.setattr("sase.stats.query.require_rust_binding", lambda _name: binding)

    for group_by in ("project", "patch"):
        query_run_stats(
            start_ts=0,
            end_ts=100,
            runtime_group_by=group_by,
            index_path=tmp_path / "index",
        )

    assert [request["runtime_group_by"] for request in requests] == [
        "project",
        "patch",
    ]
    assert all(request["project"] is None for request in requests)
    assert all(request["work_top_n"] == 50 for request in requests)
    assert all(request["xprompt_top_n"] == 40 for request in requests)
    assert all(request["xprompt_breakdown_top_n"] == 5 for request in requests)
    assert all(request["xprompt_focus"] is None for request in requests)
