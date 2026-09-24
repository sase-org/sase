"""Tests for classifying failed ``git push`` output as a lost push race."""

from __future__ import annotations

import pytest

from sase.sdd._push_race import is_retryable_push_race

_CANNOT_LOCK_REF = (
    " ! [remote rejected] main -> main (cannot lock ref 'refs/heads/main': "
    "is at bd35e42 but expected b4b58c9)\n"
    "error: failed to push some refs to 'github.com:sase-org/sase--beads.git'"
)


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("", " ! [rejected] main -> main (non-fast-forward)"),
        ("", " ! [rejected] main -> main (fetch first)"),
        (
            "",
            "hint: Updates were rejected because the remote contains work that you do",
        ),
        ("", "! [rejected] main -> main (stale info)\nerror: failed to push some refs"),
        ("", _CANNOT_LOCK_REF),
        (
            "",
            " ! [remote rejected] main -> main (incorrect old value provided)",
        ),
        (_CANNOT_LOCK_REF, ""),
        (None, " ! [REMOTE REJECTED] main -> main (Cannot Lock Ref 'refs/heads/main')"),
    ],
)
def test_is_retryable_push_race_accepts_race_phrasings(
    stdout: str | None, stderr: str | None
) -> None:
    assert is_retryable_push_race(stdout, stderr) is True


@pytest.mark.parametrize(
    "stderr",
    [
        " ! [remote rejected] main -> main (pre-receive hook declined)",
        " ! [remote rejected] main -> main (protected branch hook declined)",
        " ! [remote rejected] main -> main (permission denied)\n"
        "error: failed to push some refs",
        "fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host",
        "[rejected] main -> main (already exists)",
        "",
    ],
)
def test_is_retryable_push_race_rejects_non_race_failures(stderr: str) -> None:
    assert is_retryable_push_race("", stderr) is False
    assert is_retryable_push_race(None, None) is False
