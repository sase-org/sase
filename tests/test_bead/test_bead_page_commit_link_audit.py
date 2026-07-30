"""Tests for the published bead-page commit-link attribution audit."""

from __future__ import annotations

from pathlib import Path

from sase.bead_pages.audit import audit_commit_link_attribution

_PRIMARY_REMOTE = "git@github.com:sase-org/sase.git"


def _row(label: str, repo_url: str, sha: str) -> str:
    return f"| [`{label}`]({repo_url}/commit/{sha}) | subject | [b](b.md) | now |"


def _write_page(pages_root: Path, name: str, rows: str) -> Path:
    page = pages_root / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "\n".join(
            (
                "## Commits",
                "",
                "| Commit | Subject | Bead | Committed (UTC) |",
                "|---|---|---|---|",
                rows,
                "",
            )
        ),
        encoding="utf-8",
    )
    return page


def test_bare_label_pointing_at_a_sidecar_remote_is_reported(tmp_path: Path) -> None:
    page = _write_page(
        tmp_path,
        "sase-b3/README.md",
        _row("6c21bbb", "https://github.com/sase-org/sase--plans", "6c21bbb6" * 5),
    )

    findings = audit_commit_link_attribution(
        tmp_path,
        primary_remote_url=_PRIMARY_REMOTE,
    )

    assert len(findings) == 1
    assert findings[0].page == page
    assert findings[0].label == "6c21bbb"
    assert findings[0].url.startswith("https://github.com/sase-org/sase--plans/commit/")


def test_bare_label_pointing_at_a_linked_remote_is_reported(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "sase-b3/sase-b3.1.md",
        _row("1290667", "https://github.com/sase-org/sase-core", "12906673" * 5),
    )

    findings = audit_commit_link_attribution(
        tmp_path,
        primary_remote_url=_PRIMARY_REMOTE,
    )

    assert [finding.label for finding in findings] == ["1290667"]


def test_qualified_non_primary_labels_are_accepted(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "sase-b3/README.md",
        "\n".join(
            (
                _row(
                    "sase--plans@6c21bbb",
                    "https://github.com/sase-org/sase--plans",
                    "6c21bbb6" * 5,
                ),
                _row(
                    "sase-core@1290667",
                    "https://github.com/sase-org/sase-core",
                    "12906673" * 5,
                ),
                _row("cbe3d21", "https://github.com/sase-org/sase", "cbe3d214" * 5),
            )
        ),
    )

    assert (
        audit_commit_link_attribution(
            tmp_path,
            primary_remote_url=_PRIMARY_REMOTE,
        )
        == ()
    )


def test_primary_remote_matches_across_transports(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "sase-b3/README.md",
        _row("cbe3d21", "https://github.com/sase-org/sase", "cbe3d214" * 5),
    )

    assert (
        audit_commit_link_attribution(
            tmp_path,
            primary_remote_url="https://github.com/sase-org/sase",
        )
        == ()
    )


def test_unknown_primary_remote_or_missing_pages_prove_nothing(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "sase-b3/README.md",
        _row("6c21bbb", "https://github.com/sase-org/sase--plans", "6c21bbb6" * 5),
    )

    assert audit_commit_link_attribution(tmp_path, primary_remote_url=None) == ()
    assert (
        audit_commit_link_attribution(
            tmp_path / "absent",
            primary_remote_url=_PRIMARY_REMOTE,
        )
        == ()
    )


def test_unreadable_page_is_skipped_without_raising(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "sase-b3/README.md",
        _row("cbe3d21", "https://github.com/sase-org/sase", "cbe3d214" * 5),
    )
    (tmp_path / "sase-b3" / "broken.md").write_bytes(b"\xff\xfe not utf-8")

    assert (
        audit_commit_link_attribution(
            tmp_path,
            primary_remote_url=_PRIMARY_REMOTE,
        )
        == ()
    )
