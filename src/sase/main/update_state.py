"""State helpers shared by ``sase update`` renderers and serializers."""

from __future__ import annotations

from sase.dev_update import DevUpdateResult
from sase.uv_tool.render import UpdateSummary


def dev_update_succeeded(result: DevUpdateResult) -> bool:
    return all(outcome.status != "failed" for outcome in result.outcomes)


def combined_changed(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> bool:
    return bool(
        (dev_result is not None and dev_result.changed)
        or (managed_summary is not None and managed_summary.changed)
    )


def dev_counts(result: DevUpdateResult | None) -> dict[str, int]:
    if result is None:
        return {"updated": 0, "skipped": 0, "failed": 0}
    return {
        "updated": sum(1 for outcome in result.outcomes if outcome.status == "updated"),
        "skipped": sum(1 for outcome in result.outcomes if outcome.status == "skipped"),
        "failed": sum(1 for outcome in result.outcomes if outcome.status == "failed"),
    }


def rust_prebuild_summary(result: DevUpdateResult | None) -> str | None:
    if result is None or not result.rust_prebuild.attempted:
        return None
    if result.rust_prebuild.hit:
        return "rust prebuild: hit"
    return f"rust prebuild: miss ({result.rust_prebuild.reason})"


def plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


def humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"
