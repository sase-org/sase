#!/usr/bin/env python3
"""Fake Antigravity CLI for `/usage` usage-probe tests.

Answers ``--version`` with a bare triple, switches ``/usage`` behaviour on
``SASE_FAKE_AGY_MODE``, and appends every argv it receives to
``SASE_FAKE_AGY_ARGV`` so tests can assert on what was *not* spawned.
"""

from __future__ import annotations

import json
import os
import sys
import time

_TSV = (
    "Gemini Models\tWeekly Limit Remaining\t96%\t2026-09-27T20:14:34Z\n"
    "Gemini Models\tFive Hour Limit Remaining\t87%\t2026-09-21T23:31:12Z\n"
    "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-09-28T19:16:26Z\n"
    "Claude and GPT models\tFive Hour Limit Remaining\t100%\t2026-09-22T00:16:26Z\n"
)


def _bucket(
    bucket_id: str,
    name: str,
    window: str,
    reset_time: str,
    description: str = "You have used some of your limit.",
    **extra: object,
) -> dict[str, object]:
    bucket: dict[str, object] = {
        "id": bucket_id,
        "name": name,
        "window": window,
        "reset_time": reset_time,
        "description": description,
    }
    bucket.update(extra)
    return bucket


def _success_envelope() -> dict[str, object]:
    override = os.environ.get("SASE_FAKE_AGY_PAYLOAD")
    if override is not None:
        return json.loads(override)
    return {
        "conversation_id": "",
        "status": "SUCCESS",
        "response": _TSV,
        "duration_seconds": 0,
        "num_turns": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
        },
        "command": {
            "name": "usage",
            "data": {
                "description": "Within each group, models share a weekly limit "
                "and a 5-hour limit.",
                "groups": [
                    {
                        "name": "Gemini Models",
                        "description": "Models within this group: Gemini Flash, "
                        "Gemini Pro",
                        "buckets": [
                            _bucket(
                                "gemini-weekly",
                                "Weekly Limit Remaining",
                                "weekly",
                                "2026-09-27T20:14:34Z",
                                remaining_fraction=0.9612414240837097,
                            ),
                            _bucket(
                                "gemini-5h",
                                "Five Hour Limit Remaining",
                                "5h",
                                "2026-09-21T23:31:12Z",
                                remaining_fraction=0.8664969801902771,
                            ),
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "description": "Models within this group: Claude Opus, "
                        "Claude Sonnet, GPT-OSS",
                        "buckets": [
                            _bucket(
                                "3p-weekly",
                                "Weekly Limit Remaining",
                                "weekly",
                                "2026-09-28T19:16:26Z",
                                remaining_fraction=1,
                            ),
                            _bucket(
                                "3p-5h",
                                "Five Hour Limit Remaining",
                                "5h",
                                "2026-09-22T00:16:26Z",
                                remaining_fraction=1,
                            ),
                        ],
                    },
                ],
            },
        },
    }


def _record_argv() -> None:
    path = os.environ.get("SASE_FAKE_AGY_ARGV")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "no_auto_update": os.environ.get("AGY_CLI_DISABLE_AUTO_UPDATE"),
                    "cwd": os.getcwd(),
                }
            )
            + "\n"
        )


def _write_pidfile() -> None:
    path = os.environ.get("SASE_FAKE_AGY_PIDFILE")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def main() -> int:
    _record_argv()
    if sys.argv[1:] == ["--version"]:
        print(
            os.environ.get("SASE_FAKE_AGY_VERSION", "1.2.7"),
            flush=True,
        )
        return int(os.environ.get("SASE_FAKE_AGY_VERSION_EXIT", "0"))
    if sys.argv[1:3] != ["-p", "/usage"]:
        print(f"unexpected argv: {sys.argv[1:]}", file=sys.stderr)
        return 2
    _write_pidfile()
    mode = os.environ.get("SASE_FAKE_AGY_MODE", "success")
    if mode == "auth_prompt":
        print(
            "Authentication required. Please visit the URL below to authenticate…",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(60)  # sase-test-wait: hang until the probe deadline kills us
        return 0
    if mode == "hang":
        time.sleep(60)  # sase-test-wait: hang until the probe deadline kills us
        return 0
    if mode == "malformed":
        print("this is not json{{{", flush=True)
        return 0
    if mode == "turn_ran":
        envelope = _success_envelope()
        envelope["num_turns"] = 1
        envelope["conversation_id"] = "conv-123"
        print(json.dumps(envelope), flush=True)
        return 0
    if mode == "omitted_zero":
        envelope = _success_envelope()
        command = envelope["command"]
        assert isinstance(command, dict)
        data = command["data"]
        assert isinstance(data, dict)
        groups = data["groups"]
        assert isinstance(groups, list)
        buckets = groups[0]["buckets"]
        assert isinstance(buckets, list)
        del buckets[1]["remaining_fraction"]
        envelope["response"] = (
            "Gemini Models\tWeekly Limit Remaining\t96%\t2026-09-27T20:14:34Z\n"
            "Gemini Models\tFive Hour Limit Remaining\t0%\t2026-09-21T23:31:12Z\n"
        )
        print(json.dumps(envelope), flush=True)
        return 0
    print(json.dumps(_success_envelope()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
