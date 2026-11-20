"""Tests for the deep-only ``instructions.bundle_size`` doctor check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.doctor.checks_instructions_bundle_size import (
    CHECK_ID,
    _BundleSizeProject,
    check_instructions_bundle_size,
)
from sase.doctor.runner import DoctorContext
from sase.feature_flags import override_flags
from sase.instructions.compaction import STEP_SUPERSEDED_SUMMARIES
from sase.llm_provider.instruction_delivery import capped_root_providers
from tests.instructions.fixture_compiler import (
    core_note,
    make_roots,
    web_descriptor,
    write,
)

#: Codex's declared root-slot cap.
CODEX_CAP = 32 * 1024

#: Grok's declared root-slot cap.
GROK_CAP = 120 * 1024

_FILLER = "keeps this fixture roster long enough to matter for the provider cap "


@pytest.fixture(autouse=True)
def isolated_instructions_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bundle store and render cache at a tmp dir."""
    home = tmp_path / "ihome"
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(home))
    return home


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def _strand(keyword: str, summary: str, *, superseded: bool) -> str:
    metadata = (
        "metadata:\n  status: superseded-in-part\n  superseded_by: keep-00\n"
        if superseded
        else "metadata:\n  status: accepted\n"
    )
    return (
        f"---\nkeyword: {keyword}\nsummary: {summary}\n{metadata}---\n\n"
        "**Claim.** A test claim.\n"
    )


def _seed_superseded_heavy_web(project_root: Path) -> None:
    """Add a list roster whose superseded summaries push Codex over its cap."""
    memory = project_root / "sase" / "memory"
    write(memory / "decisions.md", web_descriptor("Decisions", "decisions web."))
    for index in range(10):
        write(
            memory / "decisions" / f"keep-{index:02d}.md",
            _strand(f"Keep {index:02d}", f"Rule {index} {_FILLER}", superseded=False),
        )
    for index in range(40):
        write(
            memory / "decisions" / f"old-{index:02d}.md",
            _strand(
                f"Old {index:02d}", f"Rule {index} " + _FILLER * 8, superseded=True
            ),
        )


def _seed_huge_core_note(project_root: Path, *, repeats: int) -> None:
    """Add a core note no compaction step can shrink."""
    write(
        project_root / "sase" / "memory" / "huge.md",
        core_note("# Huge\n\n" + "A core paragraph that cannot shrink. " * repeats),
    )


def _rows(check: Any) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["project"], row["provider"]): row for row in check.data["rows"]}


def test_bundle_size_ok_reports_sizes_when_every_bundle_fits(tmp_path: Path) -> None:
    project_root, home_root = make_roots(tmp_path)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("fixture", project_root, key="gh_o__fixture")],
        provider_caps={"codex": CODEX_CAP},
        home_root=home_root,
    )

    assert check.id == CHECK_ID
    assert check.status == "OK"
    assert "1 root bundle(s) across 1 project(s) fit without compaction" in (
        check.summary
    )
    assert "fixture/codex: " in check.summary
    row = _rows(check)[("fixture", "codex")]
    assert row["state"] == "ok"
    assert row["project_key"] == "gh_o__fixture"
    assert 0 < row["delivered_bytes"] <= CODEX_CAP
    assert row["compaction_step"] is None
    assert check.next_steps == ()


def test_bundle_size_warns_when_the_bundle_fits_only_after_compaction(
    tmp_path: Path,
) -> None:
    project_root, home_root = make_roots(tmp_path)
    _seed_superseded_heavy_web(project_root)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("fixture", project_root)],
        provider_caps={"codex": CODEX_CAP},
        home_root=home_root,
    )

    assert check.status == "WARN"
    row = _rows(check)[("fixture", "codex")]
    assert row["state"] == "compacted"
    assert row["compaction_step"] == STEP_SUPERSEDED_SUMMARIES
    assert row["uncompacted_bytes"] > CODEX_CAP >= row["delivered_bytes"]
    assert "1 root bundle(s) fit only after compaction" in check.summary
    assert f"after {STEP_SUPERSEDED_SUMMARIES}" in check.summary
    assert f"uncompacted {row['uncompacted_bytes']:,} bytes" in check.summary
    assert any(
        "`sase instructions render -f provider=codex -s`" in step
        for step in check.next_steps
    )


def test_bundle_size_errors_when_compaction_cannot_fit_the_cap(
    tmp_path: Path,
) -> None:
    project_root, home_root = make_roots(tmp_path)
    _seed_huge_core_note(project_root, repeats=1200)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("fixture", project_root)],
        provider_caps={"codex": CODEX_CAP},
        home_root=home_root,
    )

    assert check.status == "ERROR"
    row = _rows(check)[("fixture", "codex")]
    assert row["state"] == "oversize"
    assert row["delivered_bytes"] > CODEX_CAP
    assert "exceed their cap after compaction" in check.summary
    assert "fall back to native delivery" in check.summary
    assert check.details[0].startswith("fixture/codex: ")


def test_bundle_size_checks_every_project_against_each_provider_cap(
    tmp_path: Path,
) -> None:
    small_root, home_root = make_roots(tmp_path, leaf="small")
    big_root, _ = make_roots(tmp_path, leaf="big")
    # Over Codex's 32 KiB cap but well under Grok's 120 KiB cap.
    _seed_huge_core_note(big_root, repeats=1200)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[
            _BundleSizeProject("small", small_root),
            _BundleSizeProject("big", big_root),
        ],
        provider_caps={"codex": CODEX_CAP, "grok": GROK_CAP},
        home_root=home_root,
    )

    rows = _rows(check)
    assert {key: row["state"] for key, row in rows.items()} == {
        ("small", "codex"): "ok",
        ("small", "grok"): "ok",
        ("big", "codex"): "oversize",
        ("big", "grok"): "ok",
    }
    assert check.status == "ERROR"
    assert "big/codex" in check.summary
    assert "big/grok" not in check.summary
    assert check.data["provider_caps"] == {"codex": CODEX_CAP, "grok": GROK_CAP}


def test_bundle_size_warns_when_a_bundle_fails_to_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, home_root = make_roots(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("broken memory\nnote")

    monkeypatch.setattr("sase.instructions.compile.compile_bundle", _boom)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("fixture", project_root)],
        provider_caps={"codex": CODEX_CAP},
        home_root=home_root,
    )

    assert check.status == "WARN"
    assert "1 root bundle(s) failed to render: fixture/codex" in check.summary
    assert _rows(check)[("fixture", "codex")]["error"] == "broken memory note"
    assert check.details == ("fixture/codex: render failed: broken memory note",)


def test_bundle_size_skips_without_a_capped_provider(tmp_path: Path) -> None:
    project_root, home_root = make_roots(tmp_path)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("fixture", project_root)],
        provider_caps={},
        home_root=home_root,
    )

    assert check.status == "SKIP"
    assert "no provider declares a root byte cap" in check.summary


def test_bundle_size_skips_without_an_enabled_project_checkout(
    tmp_path: Path,
) -> None:
    check = check_instructions_bundle_size(
        _context(tmp_path),
        projects=[_BundleSizeProject("gone", tmp_path / "missing")],
        provider_caps={"codex": CODEX_CAP},
        home_root=tmp_path,
    )

    assert check.status == "SKIP"
    assert check.summary == "no enabled project checkouts to compile (missing: gone)"


def test_bundle_size_enumerates_enabled_projects_by_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core import project_lifecycle_facade

    project_root, home_root = make_roots(tmp_path)
    projects_root = tmp_path / ".sase" / "projects"
    real_records = project_lifecycle_facade.list_project_records
    calls: list[dict[str, Any]] = []

    def _records(root: Path, states: Any = ("enabled",), **kwargs: Any) -> list[Any]:
        if Path(root) != projects_root:
            return real_records(root, states, **kwargs)
        calls.append({"states": states, **kwargs})
        return [
            SimpleNamespace(
                project_name="gh_o__fixture",
                display_name="fixture",
                workspace_dir=str(project_root),
                is_project=True,
            ),
            SimpleNamespace(
                project_name="gh_o__gone",
                display_name="gone",
                workspace_dir=None,
                is_project=True,
            ),
        ]

    monkeypatch.setattr(project_lifecycle_facade, "list_project_records", _records)

    check = check_instructions_bundle_size(
        _context(tmp_path),
        provider_caps={"codex": CODEX_CAP},
        home_root=home_root,
    )

    assert calls == [
        {"states": "enabled", "include_home": False, "projects_only": True}
    ]
    assert check.status == "OK"
    row = _rows(check)[("fixture", "codex")]
    assert row["project_key"] == "gh_o__fixture"
    assert list(check.data["projects_missing_checkout"]) == ["gone"]
    assert "skipped (checkout missing): gone" in check.details
    assert "gh_o__fixture" not in check.summary


def test_capped_root_providers_follow_explicit_flag_gating() -> None:
    with override_flags(codex_explicit_instructions=True):
        caps = capped_root_providers()
    assert caps["codex"] == CODEX_CAP
    assert "claude" not in caps
    with override_flags(codex_explicit_instructions=False):
        assert "codex" not in capped_root_providers()
