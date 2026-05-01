"""Generate deterministic notification JSONL corpora for store parity tests.

The module is intentionally standalone and file-oriented so future Rust tests
can consume the emitted JSONL without importing Python production code.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

BASE_TIMESTAMP = "2026-04-30T12:00:00+00:00"
SNOOZE_TIMESTAMP = "2026-04-30T13:00:00+00:00"
AGENT_CL_NAME = "sase-1n-demo"
AGENT_TIMESTAMP_14 = "20260430121530"
AGENT_TIMESTAMP_13 = "260430_121530"


def fixture_rows() -> list[dict[str, Any] | str]:
    """Return the small hand-authored fixture corpus.

    String entries are written verbatim and represent malformed JSONL lines.
    """
    return [
        {
            "id": "valid-full",
            "timestamp": BASE_TIMESTAMP,
            "sender": "crs",
            "notes": ["full row", "all fields populated"],
            "files": ["/tmp/full.py"],
            "action": "JumpToChangeSpec",
            "action_data": {
                "changespec_name": "valid-full",
                "project_file": "/tmp/project.gp",
            },
            "read": True,
            "dismissed": False,
            "silent": True,
            "muted": True,
            "snooze_until": SNOOZE_TIMESTAMP,
        },
        {
            "id": "legacy-minimal",
            "timestamp": BASE_TIMESTAMP,
            "sender": "legacy",
        },
        "{this is not valid json",
        {
            "id": "missing-required",
            "timestamp": BASE_TIMESTAMP,
        },
        {
            "id": "dismissed-row",
            "timestamp": BASE_TIMESTAMP,
            "sender": "sync",
            "dismissed": True,
            "action": "JumpToChangeSpec",
            "action_data": {"changespec_name": "dismissed-row"},
        },
        {
            "id": "silent-row",
            "timestamp": BASE_TIMESTAMP,
            "sender": "user-workflow",
            "silent": True,
        },
        {
            "id": "muted-row",
            "timestamp": BASE_TIMESTAMP,
            "sender": "user-agent",
            "action": "JumpToAgent",
            "action_data": {
                "cl_name": AGENT_CL_NAME,
                "raw_suffix": AGENT_TIMESTAMP_14,
            },
            "muted": True,
        },
        {
            "id": "snoozed-row",
            "timestamp": BASE_TIMESTAMP,
            "sender": "question",
            "action": "UserQuestion",
            "action_data": {
                "response_dir": "/tmp/question",
                "session_id": "session-question",
                "agent_cl_name": AGENT_CL_NAME,
                "agent_timestamp": AGENT_TIMESTAMP_13,
            },
            "muted": True,
            "snooze_until": SNOOZE_TIMESTAMP,
        },
        {
            "id": "priority-plan",
            "timestamp": BASE_TIMESTAMP,
            "sender": "plan",
            "action": "PlanApproval",
            "action_data": {
                "response_dir": "/tmp/plan",
                "session_id": "session-plan",
                "agent_cl_name": AGENT_CL_NAME,
                "agent_timestamp": AGENT_TIMESTAMP_14,
            },
        },
        {
            "id": "priority-question",
            "timestamp": BASE_TIMESTAMP,
            "sender": "question",
            "action": "UserQuestion",
            "action_data": {
                "response_dir": "/tmp/question-2",
                "session_id": "session-question-2",
            },
        },
        {
            "id": "priority-mentor",
            "timestamp": BASE_TIMESTAMP,
            "sender": "mentors",
            "action": "JumpToMentorReview",
            "action_data": {"changespec_name": "mentor-cl", "entry_id": "1"},
        },
        {
            "id": "priority-axe",
            "timestamp": BASE_TIMESTAMP,
            "sender": "axe",
            "action": "ViewErrorReport",
            "action_data": {"error_report_path": "/tmp/digest.txt"},
        },
        {
            "id": "priority-crs",
            "timestamp": BASE_TIMESTAMP,
            "sender": "crs",
            "action": "JumpToChangeSpec",
            "action_data": {"changespec_name": "crs-cl"},
        },
        {
            "id": "priority-user-agent-error",
            "timestamp": BASE_TIMESTAMP,
            "sender": "user-agent",
            "action": "ViewErrorReport",
            "action_data": {"error_report_path": "/tmp/agent-error.txt"},
        },
        {
            "id": "agent-jump-no-suffix",
            "timestamp": BASE_TIMESTAMP,
            "sender": "user-agent",
            "action": "JumpToAgent",
            "action_data": {"cl_name": AGENT_CL_NAME},
        },
    ]


def synthetic_rows(count: int) -> Iterable[dict[str, Any]]:
    """Yield a deterministic synthetic corpus with varied state/action rows."""
    actions = [
        None,
        "JumpToAgent",
        "PlanApproval",
        "UserQuestion",
        "JumpToMentorReview",
        "ViewErrorReport",
        "JumpToChangeSpec",
    ]
    senders = [
        "user-workflow",
        "user-agent",
        "plan",
        "question",
        "mentors",
        "axe",
        "sync",
    ]
    for idx in range(count):
        action = actions[idx % len(actions)]
        sender = senders[idx % len(senders)]
        row: dict[str, Any] = {
            "id": f"synthetic-{idx:06d}",
            "timestamp": f"2026-04-30T12:{idx % 60:02d}:{idx % 60:02d}+00:00",
            "sender": sender,
            "notes": [f"Synthetic notification {idx}"],
            "files": [f"/tmp/sase/synthetic_{idx % 17}.txt"],
            "action": action,
            "action_data": {},
            "read": idx % 3 == 0,
            "dismissed": idx % 19 == 0,
            "silent": idx % 23 == 0,
            "muted": idx % 11 == 0,
            "snooze_until": SNOOZE_TIMESTAMP if idx % 29 == 0 else None,
        }
        if action == "JumpToAgent":
            row["action_data"] = {
                "cl_name": f"sase-{idx % 31}",
                "raw_suffix": f"20260430{idx % 24:02d}{idx % 60:02d}{idx % 60:02d}",
            }
        elif action in {"PlanApproval", "UserQuestion"}:
            row["action_data"] = {
                "response_dir": f"/tmp/sase/response_{idx}",
                "session_id": f"session-{idx}",
                "agent_cl_name": f"sase-{idx % 31}",
                "agent_timestamp": f"260430_{idx % 24:02d}{idx % 60:02d}{idx % 60:02d}",
            }
        elif action == "JumpToMentorReview":
            row["action_data"] = {
                "changespec_name": f"sase-{idx % 31}",
                "entry_id": "1",
            }
        elif action == "ViewErrorReport":
            row["action_data"] = {"error_report_path": f"/tmp/sase/error_{idx}.txt"}
        elif action == "JumpToChangeSpec":
            row["action_data"] = {
                "changespec_name": f"sase-{idx % 31}",
                "project_file": "/tmp/sase/project.gp",
            }
        yield row


def write_jsonl(path: Path, rows: Iterable[dict[str, Any] | str]) -> None:
    """Write rows to ``path`` as JSONL, preserving malformed string entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            if isinstance(row, str):
                f.write(row)
            else:
                f.write(json.dumps(row, sort_keys=True))
            f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--small-fixture", action="store_true")
    args = parser.parse_args(argv)

    rows: Iterable[dict[str, Any] | str]
    if args.small_fixture:
        rows = fixture_rows()
    else:
        rows = synthetic_rows(args.count)
    write_jsonl(args.output, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
