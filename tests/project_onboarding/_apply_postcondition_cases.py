"""Postcondition and concurrency cases for onboarding apply."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.project_onboarding.apply import apply_plan
from sase.project_onboarding.journal import lookup_journal
from sase.project_onboarding import parse_event_line
from ._apply_test_support import (
    IDENTITY,
    KEY,
    NAME,
    FakeGh,
    git,
    marker_commits,
    request as make_request,
    run,
    step_ids,
)


class TestActualPostconditions:
    def test_changed_allocation_uses_actual_record(self, fake_gh: FakeGh) -> None:
        fake_gh.allocate_key = "gh_sase-org__bob2"
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "off", "make_current": True}
        result, _ = run(request)

        assert result["status"] == "ok"
        assert result["project"]["key"] == "gh_sase-org__bob2"
        assert result["next_argv"] == []
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["project_key"] == "gh_sase-org__bob2"

    def test_dirty_matching_clone_is_preserved(self, fake_gh: FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[IDENTITY])
        git(fake_gh.home, "clone", str(fake_gh.origin), str(checkout))
        dirty = checkout / "notes.txt"
        dirty.write_text("local work\n", encoding="utf-8")
        git(checkout, "add", "notes.txt")
        spec_dir = sase_projects_dir() / KEY
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / f"{KEY}.sase").write_text(
            f"WORKSPACE_DIR: {checkout}\nPROJECT_NAME: {NAME}\n",
            encoding="utf-8",
        )
        request = make_request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, _ = run(request)

        assert result["status"] == "ok"
        assert fake_gh.resolve_calls == []
        assert dirty.read_text(encoding="utf-8") == "local work\n"

    def test_empty_checkout_dir_removed_for_clone(self, fake_gh: FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[IDENTITY])
        checkout.mkdir(parents=True)
        request = make_request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, _ = run(request)

        assert result["status"] == "ok"
        assert (checkout / ".git").is_dir()
        assert len(fake_gh.resolve_calls) == 2

    def test_reenable_restores_disabled_record(self, fake_gh: FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[IDENTITY])
        git(fake_gh.home, "clone", str(fake_gh.origin), str(checkout))
        spec_dir = sase_projects_dir() / KEY
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / f"{KEY}.sase").write_text(
            f"PROJECT_STATE: disabled\nWORKSPACE_DIR: {checkout}\n"
            f"PROJECT_NAME: {NAME}\n",
            encoding="utf-8",
        )
        request = make_request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, events = run(request)

        assert result["status"] == "ok"
        assert fake_gh.resolve_calls == []
        assert "reenable" in step_ids(events)
        content = (spec_dir / f"{KEY}.sase").read_text(encoding="utf-8")
        assert "disabled" not in content

    def test_simultaneous_submissions_share_one_commit(self, fake_gh: FakeGh) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "auto", "make_current": True}
        barrier = threading.Barrier(2)
        outcomes: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def submit() -> None:
            try:
                barrier.wait(timeout=30)
                outcomes.append(apply_plan(dict(request), emit=lambda event: None))
            except BaseException as exc:  # noqa: BLE001 - collected by test
                errors.append(exc)

        workers = [threading.Thread(target=submit) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=300)

        assert not errors
        assert sorted(item["status"] for item in outcomes) == ["ok", "ok"]
        assert len(marker_commits(fake_gh.origin)) == 2

    def test_result_events_are_valid_ndjson(self, fake_gh: FakeGh) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        result, events = run(make_request(checkout))

        assert result["status"] == "ok"
        lines = [json.dumps(item, ensure_ascii=True) for item in events]
        parsed = [parse_event_line(line) for line in lines]
        assert all(item is not None for item in parsed)
        assert parsed[-1] is not None and parsed[-1]["status"] == "ok"
