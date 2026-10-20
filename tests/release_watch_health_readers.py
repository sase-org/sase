"""release watch health readers tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from _release_watch_health_test_helpers import (
    CORE_REPO,
    CORE_SHA,
    HEAD,
    PIN,
    REPO,
    WORKFLOW_YML,
    ReleaseFactsError,
    ReleaseTransportError,
    ScriptedGithub,
    b64,
    flat,
    make_facts,
    make_health,
    pypi_complete,
    transport_error,
)


def revision_reads(pin: str = PIN, ref: str = HEAD) -> dict[str, Any]:
    del ref
    return {
        f"repos/{REPO}/contents/sase-core-revision.txt": {
            "encoding": "base64",
            "content": b64(pin + "\n"),
        }
    }


def core_compare_reads(status: str = "ahead") -> dict[str, Any]:
    return {
        f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": status},
        f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
            "encoding": "base64",
            "content": b64(WORKFLOW_YML),
        },
    }


def release_raw(tag: str, draft: bool = False) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "draft": draft,
        "name": tag,
        "assets": [],
        "created_at": "2026-10-19T10:00:00Z",
        "html_url": f"https://example.test/{tag}",
    }


def test_core_ensure_prefers_pr_pin_over_master_pin() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(CORE_REPO, reads=core_compare_reads())
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    pr = {"source_pin": PIN, "head_sha": HEAD}
    assert health.read_core_ensure(pr, CORE_SHA)["kind"] == "pinned"
    assert f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0" in core.calls
    assert not any("contents/sase-core-revision" in call for call in sase.calls)


def test_core_ensure_falls_back_to_master_pin() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads(pin=PIN, ref=HEAD))
    core = ScriptedGithub(CORE_REPO, reads=core_compare_reads())
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure(None, HEAD)
    assert result["kind"] == "pinned"
    assert f"repos/{REPO}/contents/sase-core-revision.txt" in sase.calls


def test_core_ensure_lag_reports_newest_complete() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": "diverged"},
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result == {"kind": "core_lag", "pin": PIN, "newest_complete": "0.50.0"}


def test_core_ensure_error_is_a_ready_variant_not_an_outage() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": "weird"},
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result["kind"] == "error"
    assert "unknown status" in result["message"]


def test_core_ensure_compare_outage_is_an_error_variant() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": transport_error(
                "compare", "HTTP 500"
            ),
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result["kind"] == "error"


def test_read_ref_sha_validates_shape() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={f"repos/{REPO}/git/ref/heads/master": {"object": {"sha": HEAD}}},
    )
    assert make_facts(sase).read_ref_sha() == HEAD
    with pytest.raises(ValueError):
        make_facts(sase).read_ref_sha("not a ref")


def test_read_jobs_validates_arguments() -> None:
    sase = ScriptedGithub(REPO)
    facts = make_facts(sase)
    with pytest.raises(ValueError):
        facts.read_jobs("", 1)
    with pytest.raises(ValueError):
        facts.read_jobs("7", 0)


def test_git_file_decodes_wrapped_base64() -> None:
    long_text = "x = 1  # " + "padding " * 40
    sase = ScriptedGithub(
        REPO,
        reads={
            f"repos/{REPO}/contents/pyproject.toml": {
                "encoding": "base64",
                "content": b64(long_text),
            }
        },
    )
    assert "padding" in make_facts(sase)._git_file("pyproject.toml", HEAD)


def test_read_source_pin_reads_remote_identity() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads(pin=PIN, ref=CORE_SHA))
    assert make_facts(sase).read_source_pin(CORE_SHA) == PIN.lower()


def test_read_repository_uses_slashless_path() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={
            f"repos/{REPO}": {
                "owner": {"login": "sase-org"},
                "name": "sase",
                "default_branch": "master",
            }
        },
    )
    assert make_facts(sase).read_repository() == {
        "owner": "sase-org",
        "name": "sase",
        "default_branch": "master",
    }


def test_read_releases_accepts_flattened_array_pages() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={},
        listings={
            f"repos/{REPO}/releases": flat(
                [release_raw("v0.18.0"), release_raw("v0.19.0", draft=True)]
            )
        },
    )
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = datetime(2026, 10, 21, tzinfo=UTC)
    assert make_facts(sase).read_releases(since=start, until=end) == [
        {
            "tag": "v0.18.0",
            "draft": False,
            "name": "v0.18.0",
            "assets": [],
            "url": "https://example.test/v0.18.0",
        },
        {
            "tag": "v0.19.0",
            "draft": True,
            "name": "v0.19.0",
            "assets": [],
            "url": "https://example.test/v0.19.0",
        },
    ]
