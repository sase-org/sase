"""Test helpers for ACE update toast tests."""

from __future__ import annotations

from collections.abc import Callable

from sase.ace.tui.actions.update_toast import UpdateToastMixin
from sase.updates import (
    CommitSummary,
    IncomingCommits,
    OutdatedComponent,
    UpdateStatus,
)
from sase.updates.status import ComponentRole


def _status(count: int = 2) -> UpdateStatus:
    components = [
        OutdatedComponent(
            display_name="sase",
            role="host",
            installed_version="1.0.0",
            latest_version="1.1.0",
            distribution_name="sase",
        ),
        OutdatedComponent(
            display_name="github",
            role="plugin",
            installed_version="0.5.0",
            latest_version="0.6.0",
            distribution_name="sase-github",
        ),
        OutdatedComponent(
            display_name="telegram",
            role="plugin",
            installed_version="0.1.0",
            latest_version="0.2.0",
            distribution_name="sase-telegram",
        ),
        OutdatedComponent(
            display_name="nvim",
            role="plugin",
            installed_version="0.3.0",
            latest_version="0.4.0",
            distribution_name="sase-nvim",
        ),
    ]
    return UpdateStatus(checked_at=100.0, components=tuple(components[:count]))


def _core_status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
            ),
            OutdatedComponent(
                display_name="sase-core",
                role="core",
                installed_version="2.0.0",
                latest_version="2.1.0",
                distribution_name="sase-core-rs",
            ),
        ),
    )


def _editable_component(
    name: str,
    *,
    role: ComponentRole = "plugin",
    root: str | None = None,
) -> OutdatedComponent:
    return OutdatedComponent(
        display_name=name,
        role=role,
        installed_version="1.0.0",
        latest_version="1.1.0",
        distribution_name=name,
        install_type="editable",
        source_root=root or f"/repo/{name}",
        upstream_ref="origin/main",
    )


def _incoming(prefix: str, total: int) -> IncomingCommits:
    return IncomingCommits(
        total=total,
        commits=tuple(
            CommitSummary(f"{prefix}{idx:06d}"[:7], f"{prefix} commit {idx}")
            for idx in range(total)
        ),
        source="git",
    )


class _Indicator:
    def __init__(self, count: int = 0) -> None:
        self.count = count
        self.sase_count = count
        self.agent_cli_count = 0
        self.manual_agent_cli_count = 0
        self.core = False

    def set_available(
        self,
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
    ) -> None:
        self.count = count + agent_cli_count
        self.sase_count = count
        self.agent_cli_count = agent_cli_count
        self.manual_agent_cli_count = manual_agent_cli_count
        self.core = core


class _AutomaticCheckApp(UpdateToastMixin):
    def __init__(self, *, indicator_count: int = 0) -> None:
        self._automatic_update_check_in_flight = False
        self._automatic_update_check_timer = None
        self._update_toast_shown = False
        self._automatic_update_status = None
        self._automatic_update_provider_names = None
        self.indicator = _Indicator(indicator_count)
        self.workers: list[tuple[Callable[[], None], dict[str, object]]] = []
        self.intervals: list[tuple[float, Callable[[], None], str]] = []
        self.notifications: list[dict[str, object]] = []

    def set_interval(
        self,
        interval: float,
        callback: Callable[[], None],
        *,
        name: str,
    ) -> object:
        self.intervals.append((interval, callback, name))
        return object()

    def run_worker(self, callback: Callable[[], None], **kwargs: object) -> None:
        self.workers.append((callback, kwargs))

    def query_one(self, *_args: object) -> _Indicator:
        return self.indicator

    def call_from_thread(self, callback: Callable[..., None], *args: object) -> None:
        callback(*args)

    def notify(self, message: str, **kwargs: object) -> None:
        self.notifications.append({"message": message, **kwargs})
