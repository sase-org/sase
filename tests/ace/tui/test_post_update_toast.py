"""Tests for the ACE post-update restart toast."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import pytest
from textual.markup import escape

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui._keymap_unification_notice import (
    mark_keymap_unification_notice_shown,
)
from sase.ace.tui.actions import post_update_toast, update_toast
from sase.ace.tui.actions.post_update_toast import PostUpdateToastMixin
from sase.ace.update_receipt import (
    _ProviderUpdateReceiptResult,
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
    write_pending_update_toast,
)
from sase.dev_update.models import RepoCommit, RepoCommitLog, RepoDiffStat
from sase.updates import OutdatedComponent, UpdateStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def _receipt(*, created_at: float | None = None) -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="managed",
        created_at=time.time() if created_at is None else created_at,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),),
        dependency_count=2,
    )


def _diffstat_receipt() -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="dev",
        created_at=time.time(),
        primary=UpdateVersionTransition(
            "sase",
            "0.5.0+1.gabc123def",
            "0.5.0+2.gdef456abc",
            diffstat=RepoDiffStat(files_changed=12, insertions=1234, deletions=567),
        ),
        plugins=(
            UpdateVersionTransition(
                "sase-github",
                "1.2.0",
                "1.3.0",
                diffstat=RepoDiffStat(files_changed=1, insertions=0, deletions=0),
            ),
        ),
        plugin_overflow=2,
        plugin_overflow_diffstat=RepoDiffStat(
            files_changed=3,
            insertions=10,
            deletions=2,
        ),
        dependency_count=2,
    )


def _single_repo_dev_receipt() -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="dev",
        created_at=time.time(),
        primary=UpdateVersionTransition(
            "sase",
            "0.6.1+41.g26e9d358d",
            "0.6.1+43.g937278ecb",
            diffstat=RepoDiffStat(files_changed=8, insertions=171, deletions=26),
        ),
    )


def _commit_receipt() -> UpdateToastReceipt:
    long_subject = "[fix] " + "x" * 80
    return UpdateToastReceipt(
        kind="dev",
        created_at=time.time(),
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        commit_groups=(
            RepoCommitGroup(
                label="sase[dev]",
                commits=RepoCommitLog(
                    total=3,
                    commits=(
                        RepoCommit("abc[123", long_subject),
                        RepoCommit("def4567", "feat: another commit"),
                    ),
                ),
            ),
            RepoCommitGroup(
                label="sase-core",
                commits=RepoCommitLog(
                    total=2,
                    commits=(RepoCommit("7654321", "perf: faster parser"),),
                ),
            ),
        ),
        commit_group_overflow=2,
    )


def _status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="0.6.0",
                latest_version="0.7.0",
                distribution_name="sase",
            ),
        ),
    )


def _plain_text_lines(message: str) -> list[str]:
    return [re.sub(r"\[[^\]]+\]", "", line) for line in message.splitlines()]


def test_post_update_toast_formats_update_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls: list[dict[str, Any]] = []

        def notify(self, message: str, **kwargs: Any) -> None:
            self.calls.append({"message": message, **kwargs})

    monkeypatch.setattr(
        post_update_toast,
        "read_and_clear_pending_update_toast",
        lambda: _receipt(),
    )
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=True),
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app._update_toast_shown is True
    assert len(app.calls) == 1
    call = app.calls[0]
    assert call["severity"] == "information"
    assert call["title"] == "✓ Updated to sase 0.6.0"
    assert "sase" in call["message"]
    assert "0.5.0" in call["message"]
    assert "0.6.0" in call["message"]
    assert "sase-github" in call["message"]
    assert "+2 dependencies" in call["message"]
    assert "Reloaded into the new version." in call["message"]
    assert (
        "\n\n[dim]+2 dependencies · Reloaded into the new version.[/]"
        in call["message"]
    )


def test_post_update_toast_formats_diffstats() -> None:
    message = post_update_toast._format_post_update_toast_message(_diffstat_receipt())
    lines = message.splitlines()

    assert "[bold green]+1,234[/]" in message
    assert "[#D75F5F]−567[/]" in message
    assert "[bold green]+1,234[/]" not in lines[0]
    assert lines[1].startswith(" " * 15)
    assert "[bold green]+1,234[/]" in lines[1]
    assert "[dim]1 file[/]" in message
    assert "…and 2 more" in message
    assert "[bold green]+10[/]" in message
    assert (
        "\n\n[dim]16 files changed · +2 dependencies · "
        "Reloaded into the new version.[/]"
    ) in message


def test_post_update_toast_formats_grouped_commits_safely() -> None:
    receipt = _commit_receipt()

    message = post_update_toast._format_post_update_toast_message(
        receipt,
        max_commits_per_repo=1,
    )

    assert f"[bold cyan]↑ {escape('sase[dev]')}[/]" in message
    assert f"[dim]{escape('abc[123')}[/]" in message
    truncated = post_update_toast._truncate_commit_subject(
        receipt.commit_groups[0].commits.commits[0].subject
    )
    assert escape(truncated) in message
    assert len(truncated) == post_update_toast._COMMIT_SUBJECT_MAX
    assert "  [dim]+2 more…[/]" in message
    assert "  [dim]+1 more…[/]" in message
    assert "[dim]…and 2 more repositories[/]" in message
    assert "[dim]5 commits · Reloaded into the new version.[/]" in message


def test_post_update_toast_commit_gate_omits_section_and_tail_count() -> None:
    message = post_update_toast._format_post_update_toast_message(
        _commit_receipt(),
        show_commits=False,
    )

    assert "↑" not in message
    assert "abc" not in message
    assert "5 commits" not in message
    assert "Reloaded into the new version." in message


def test_post_update_toast_renders_provider_partial_failure_and_manual_guidance() -> (
    None
):
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        provider_results=(
            _ProviderUpdateReceiptResult(
                name="claude",
                display_name="Claude Code",
                status="failed",
                reason="command failed; see vendor docs",
            ),
            _ProviderUpdateReceiptResult(
                name="codex",
                display_name="Codex CLI",
                status="skipped",
                reason="Homebrew requires a manual upgrade",
                suggested_command=("brew", "upgrade", "codex"),
            ),
        ),
    )

    assert post_update_toast._format_post_update_toast_title(receipt) == (
        "⚠ SASE updated with Agent CLI issues"
    )
    message = post_update_toast._format_post_update_toast_message(receipt)
    assert "Agent CLIs" in message
    assert "Claude Code: [red]failed" in message
    assert "Codex CLI: [yellow]manual" in message
    assert "brew upgrade codex" in message


def test_post_update_toast_managed_receipt_keeps_legacy_rendering() -> None:
    receipt = _receipt()

    with_diffstat = post_update_toast._format_post_update_toast_message(
        receipt,
        show_diffstat=True,
    )
    without_diffstat = post_update_toast._format_post_update_toast_message(
        receipt,
        show_diffstat=False,
    )
    assert with_diffstat == without_diffstat
    assert "\n\n[dim]+2 dependencies · Reloaded into the new version.[/]" in (
        with_diffstat
    )


def test_post_update_toast_formats_install_receipt() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=None,
        plugins=(UpdateVersionTransition("sase-nvim", None, "2.0.0"),),
    )

    assert post_update_toast._format_post_update_toast_title(receipt) == (
        "✓ Installed sase-nvim"
    )
    message = post_update_toast._format_post_update_toast_message(receipt)
    plain = "\n".join(_plain_text_lines(message))
    assert "sase-nvim  installed v2.0.0" in plain
    assert "unknown" not in plain
    assert "Reloaded to load the new plugin." in plain


def test_post_update_toast_formats_uninstall_receipt() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=None,
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", None),),
    )

    assert post_update_toast._format_post_update_toast_title(receipt) == (
        "✓ Uninstalled sase-github"
    )
    message = post_update_toast._format_post_update_toast_message(receipt)
    plain = "\n".join(_plain_text_lines(message))
    assert "sase-github  uninstalled (was v1.2.0)" in plain
    assert "unknown" not in plain
    assert "Reloaded after removing the plugin." in plain


def test_post_update_toast_single_plugin_update_title_names_plugin() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=None,
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),),
    )

    assert post_update_toast._format_post_update_toast_title(receipt) == (
        "✓ Updated sase-github"
    )


def test_post_update_toast_diffstat_toggle_suppresses_churn() -> None:
    message = post_update_toast._format_post_update_toast_message(
        _diffstat_receipt(),
        show_diffstat=False,
    )

    assert "+1,234" not in message
    assert "16 files changed" not in message
    assert "0.5.0+1.gabc123def" in message
    assert "\n\n[dim]+2 dependencies · Reloaded into the new version.[/]" in message


def test_post_update_toast_single_repo_dev_receipt_does_not_wrap() -> None:
    message = post_update_toast._format_post_update_toast_message(
        _single_repo_dev_receipt()
    )
    lines = _plain_text_lines(message)

    assert lines == [
        "sase  0.6.1+41.g26e9d358d → 0.6.1+43.g937278ecb",
        "      +171 −26",
        "",
        "8 files changed · Reloaded into the new version.",
    ]
    assert all(len(line) <= 57 for line in lines)


def test_post_update_toast_absent_receipt_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls = 0

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1

    monkeypatch.setattr(
        post_update_toast,
        "read_and_clear_pending_update_toast",
        lambda: None,
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app.calls == 0
    assert app._update_toast_shown is False


def test_post_update_toast_disabled_consumes_without_showing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True

    class _App(PostUpdateToastMixin):
        def __init__(self) -> None:
            self._update_toast_shown = False
            self.calls = 0

        def notify(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1

    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=False),
    )
    app = _App()

    app._maybe_show_post_update_toast()

    assert app.calls == 0
    assert app._update_toast_shown is False
    assert not receipt_file.exists()


async def test_post_update_toast_appears_once_and_suppresses_available_toast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    # This test's own subject is toast suppression between the post-update and
    # update-available toasts; pre-seed the unrelated one-shot keymap-unification
    # notice as already shown so it doesn't ride along on this receipt and add a
    # third, unrelated notification.
    mark_keymap_unification_notice_shown()
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(
            startup_toast=True,
            post_update_toast=True,
        ),
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: _status(),
    )

    async with AcePage(query='"toast"') as page:
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.pause()
        notifications = list(page.app._notifications)
        assert len(notifications) == 1
        assert notifications[0].title == "✓ Updated to sase 0.6.0"
        assert "sase-github" in notifications[0].message
        assert not receipt_file.exists()
