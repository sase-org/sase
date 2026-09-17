from __future__ import annotations

from pathlib import Path
import re

from sase.agents_sync.inventory import (
    InventoryRun,
    ProjectHoodInventory,
    _InventoryRelationship,
)
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

_HEADING_RE = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
    )


def _run(
    name: str,
    suffix: str,
    *,
    state: str = "completed",
    commit: bool = False,
    family: str | None = None,
    output_variables: dict[str, str] | None = None,
    chat: bytes | None = b"chat\n",
    relationships: tuple[_InventoryRelationship, ...] = (),
) -> InventoryRun:
    owner = AgentOwnerIdentity("alice", "athena")
    metadata = (("model", "gpt"),)
    if family is not None:
        metadata += (("agent_family", family),)
    if output_variables is not None:
        metadata += (("output_variables", output_variables),)
    commits = (CommitRecord("a" * 39 + suffix[-1], name, 1),) if commit else ()
    finished_at = (
        None if state in {"active", "waiting"} else "2026-07-23T12:01:00+00:00"
    )
    return InventoryRun(
        f"run-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        state,
        "2026-07-23T12:00:00+00:00",
        finished_at,
        finished_at if state == "dismissed" else None,
        tuple(sorted(metadata)),
        commits,
        f"prompt for {name}\n".encode(),
        chat,
        family,
        None,
        relationships,
        f"20260723120{suffix[-2:]}",
    )


def _inventory(owner: AgentOwnerIdentity) -> ProjectHoodInventory:
    runs = (
        _run("foo", "01", output_variables={"status": "ready"}),
        _run("foo.bar", "02"),
        _run(
            "foo.bar.baz--code",
            "03",
            state="active",
            commit=True,
            family="foo.bar.baz",
            output_variables={"report_path": "reports/code.md"},
            chat=None,
            relationships=(_InventoryRelationship("parent", "foo.bar", "name"),),
        ),
        _run(
            "foo.bar.baz--plan",
            "04",
            family="foo.bar.baz",
            output_variables={
                "plan_file": "plans/foo.md",
                "status": "approved",
            },
            relationships=(_InventoryRelationship("parent", "foo.bar", "name"),),
        ),
        _run("foo.bar.baz.child", "12"),
        _run("foo.boom", "05", state="waiting"),
        _run("foo.bar.kazam", "06", state="failed"),
        _run("foo.rootless--left", "07", family="foo.rootless"),
        _run("foo.rootless--right", "08", family="foo.rootless"),
        _run("foo.archive", "11", state="dismissed"),
        _run("zap.solo", "09"),
        _run("work.committer", "10", commit=True),
    )
    return ProjectHoodInventory(owner, "proj", runs)


def _identity() -> AgentIdentitySnapshot:
    return AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))


def _snapshot_path(root: Path) -> Path:
    return (
        root
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )


def _section_titles(page: str) -> tuple[str, ...]:
    return tuple(match.group("title") for match in _HEADING_RE.finditer(page))


def _assert_summary_anchors_resolve(page: str) -> None:
    marker = "## Summary\n\n"
    if marker not in page:
        return
    summary = page.split(marker, 1)[1].split("\n## ", 1)[0]
    anchors = re.findall(r"\]\(#([^)]+)\)", summary)
    headings = {title.casefold().replace(" ", "-") for title in _section_titles(page)}
    for anchor in anchors:
        assert anchor in headings
