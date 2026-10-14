"""Aggregate observations into the verification report."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sase.instructions import run_index as runs
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport


def _tri(value: bool | None) -> str:
    if value is True:
        return "✓"
    if value is False:
        return "✗"
    return "◌"


def _modal_contract(counts: list[int | None]) -> str:
    known = [value for value in counts if isinstance(value, int)]
    if not known:
        return "◌" if counts else "0"
    tally = Counter(known)
    modal, _ = tally.most_common(1)[0]
    if len(tally) == 1:
        return f"{modal}×" if modal != 0 else "0"
    spread = ",".join(str(value) for value in sorted(tally))
    return f"{modal}× [{spread}]"


def _aggregate_rows(
    observations: list[SessionObservation],
    scored_runs: list[runs.ScoredRun],
    coverages: dict[str, str] | None = None,
) -> list[ProviderRow]:
    """Aggregate observations into one row per provider."""
    order = ("claude", "codex", "muse", "grok", "agy")
    by_provider: dict[str, list[SessionObservation]] = {name: [] for name in order}
    for obs in observations:
        by_provider.setdefault(obs.provider, []).append(obs)
    runs_by_provider: dict[str, int] = {}
    for run in scored_runs:
        runs_by_provider[run.provider] = runs_by_provider.get(run.provider, 0) + 1
    labels = coverages or {}
    rows: list[ProviderRow] = []
    for provider in order:
        obs_list = [
            o for o in by_provider.get(provider, []) if o.session_id != "unobserved"
        ]
        if not obs_list and provider not in runs_by_provider:
            continue
        rows.append(
            _aggregate_provider(
                provider,
                obs_list,
                runs_by_provider.get(provider, 0),
                coverage=labels.get(provider, "0/0"),
            )
        )
    # Keep providers with unobserved runs so the table names the gap.
    for provider in order:
        if provider in runs_by_provider and not any(
            r.provider == provider for r in rows
        ):
            rows.append(
                ProviderRow(
                    provider=provider,
                    runs=runs_by_provider[provider],
                    sessions=0,
                    coverage=labels.get(provider, "0/0"),
                )
            )
    return rows


def _aggregate_provider(
    provider: str,
    obs_list: list[SessionObservation],
    run_count: int,
    *,
    coverage: str = "0/0",
) -> ProviderRow:
    if not obs_list:
        return ProviderRow(provider=provider, runs=run_count, sessions=0)
    # Root sessions carry the delivery columns; helper observations feed
    # only the helpers column.
    root_obs = [o for o in obs_list if o.helper_type is None] or obs_list
    contract = _modal_contract([o.contract_count for o in root_obs])
    home = _tri(_mode_tri([o.home for o in root_obs]))
    project = _tri(_mode_tri([o.project for o in root_obs]))
    directive = _tri(_mode_tri([o.directive for o in root_obs]))
    native_counts = [o.native_full_count for o in root_obs]
    native = (
        _modal_contract(native_counts)
        if any(value for value in native_counts if value is not None)
        else (
            "◌"
            if native_counts and all(value is None for value in native_counts)
            else "0"
        )
    )
    if provider == "agy":
        native = "◌"
        contract = "◌"
    foreign = _foreign_label(provider, obs_list)
    helpers = _helpers_label(provider, obs_list)
    denials = sum(1 for o in obs_list if o.root_guard_denial)
    bundle_counts = [
        item.bundle_count for item in root_obs if item.delivery == "explicit"
    ]
    if bundle_counts:
        bundle = _modal_contract(bundle_counts)
    elif root_obs and all(item.delivery not in (None, "explicit") for item in root_obs):
        bundle = "—"
    else:
        bundle = "◌"
    deliveries = [item.delivery for item in root_obs if item.delivery]
    delivery = _mode_label(deliveries) if deliveries else "◌"
    channels = _aggregate_channels(root_obs)
    return ProviderRow(
        provider=provider,
        runs=run_count,
        sessions=len(obs_list),
        contract=contract,
        home=home,
        project=project,
        directive=directive,
        native_full=native,
        foreign=foreign,
        helpers=helpers,
        root_denials=denials,
        coverage=coverage,
        bundle=bundle,
        delivery=delivery,
        channels=channels,
    )


def _mode_label(values: list[str]) -> str:
    if not values:
        return "◌"
    counts = Counter(values)
    highest = max(counts.values())
    winners = sorted(value for value, count in counts.items() if count == highest)
    return winners[0] if len(winners) == 1 else "/".join(winners)


def _aggregate_channels(
    observations: list[SessionObservation],
) -> dict[str, dict[str, int | bool | None]]:
    result: dict[str, dict[str, int | bool | None]] = {}
    for column in ("contract", "home", "project", "directive"):
        breakdown: dict[str, int | bool | None] = {}
        for channel in ("native", "explicit"):
            values = [
                item.channels.get(column, {}).get(channel)
                for item in observations
                if column in item.channels
            ]
            if column == "contract":
                known = [value for value in values if isinstance(value, int)]
                counts = Counter(known)
                breakdown[channel] = (
                    min(
                        value
                        for value, count in counts.items()
                        if count == max(counts.values())
                    )
                    if counts
                    else None
                )
            else:
                breakdown[channel] = _mode_tri(
                    [value if isinstance(value, bool) else None for value in values]
                )
        result[column] = breakdown
    return result


def _mode_tri(values: list[bool | None]) -> bool | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return (
        True if sum(1 for v in known if v) >= sum(1 for v in known if not v) else False
    )


def _foreign_label(provider: str, obs_list: list[SessionObservation]) -> str:
    foreigns = [o.foreign for o in obs_list if o.foreign]
    if provider == "claude":
        return "auto-memory" if foreigns else "—"
    if provider == "grok":
        return foreigns[0] if foreigns else "—"
    if provider == "codex":
        return foreigns[0] if foreigns else "—"
    return "—"


def _helpers_label(provider: str, obs_list: list[SessionObservation]) -> str:
    helper_obs = [o for o in obs_list if o.helper_type]
    if provider == "agy":
        return "—"
    if not helper_obs:
        return (
            "0 spawns" if provider == "codex" else ("—" if provider == "muse" else "—")
        )
    attempts = sum(o.final_attempts for o in helper_obs)
    accepted = sum(o.final_accepted for o in helper_obs)
    types = sorted({str(o.helper_type) for o in helper_obs})
    if provider == "claude":
        checks = [o.helper_bundle for o in helper_obs if o.helper_bundle is not None]
        root_markers = [
            o.root_bundle_in_helper
            for o in helper_obs
            if o.root_bundle_in_helper is not None
        ]
        details = f"{','.join(types)}: {attempts} attempts, {accepted} accepted"
        if checks:
            details += f"; helper bundle {sum(checks)}/{len(checks)}"
        if root_markers:
            details += f"; root markers {sum(root_markers)}"
        return details
    return f"{len(helper_obs)} helpers"


def build_report(
    scored_runs: list[runs.ScoredRun],
    observations: list[SessionObservation],
    *,
    filters: dict[str, object],
    coverages: dict[str, str] | None = None,
) -> VerifyReport:
    """Build a ``VerifyReport`` from runs and observations."""
    rows = _aggregate_rows(observations, scored_runs, coverages)
    return VerifyReport(
        provider_rows=tuple(rows),
        observations=tuple(observations),
        filters=dict(filters),
        generated_at=datetime.now(tz=UTC).isoformat(),
    )
