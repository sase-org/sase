"""Automatic provider drain after a manual hard disable."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.agent_durable import submit_provider_drain

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


def _completion_count_text(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _payload_count(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _join_and(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _stranded_target(detail: object) -> str:
    text = detail if isinstance(detail, str) else ""
    prefix = "pinned to "
    if text.startswith(prefix):
        rest = text[len(prefix) :].split(";", 1)[0].strip()
        return rest or "that model"
    return "that model"


def _skip_group_label(reason: str, detail: object) -> str:
    if reason == "stranded":
        return f"pinned to {_stranded_target(detail)}"
    if reason == "pending_question":
        return "waiting on a question"
    if reason == "monitor":
        return "monitor row"
    if reason == "caller":
        return "current agent"
    if reason == "capped":
        return "over the drain limit"
    return reason.replace("_", " ") or "left alone"


def _skip_breakdown(skips: object) -> str:
    """Return a comma-joined per-reason skip summary like the old prompt did."""
    if not isinstance(skips, list):
        return ""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for skip in skips:
        if not isinstance(skip, Mapping):
            continue
        reason = skip.get("reason")
        key = reason if isinstance(reason, str) and reason else "left alone"
        grouped.setdefault(key, []).append(skip)
    parts: list[str] = []
    for reason in sorted(grouped):
        rows = grouped[reason]
        label = _skip_group_label(reason, rows[0].get("detail"))
        parts.append(f"{len(rows)} {label}")
    return ", ".join(parts)


def _ok_target_providers(payload: Mapping[str, Any]) -> list[str]:
    """Return distinct upper-cased target providers for ok results, in order."""
    moves = payload.get("moves")
    results = payload.get("results")
    if not isinstance(moves, list) or not isinstance(results, list):
        return []
    ok_names = {
        result.get("name")
        for result in results
        if isinstance(result, Mapping) and result.get("status") == "ok"
    }
    providers: list[str] = []
    for move in moves:
        if not isinstance(move, Mapping):
            continue
        if move.get("name") not in ok_names:
            continue
        route = move.get("route")
        target = route.get("target_provider") if isinstance(route, Mapping) else None
        provider = str(target).upper() if target else ""
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def _relaunched_summary(relaunched: int, providers: list[str]) -> str:
    text = f"Relaunched {_completion_count_text(relaunched, 'agent')}"
    if providers:
        text += f" on {_join_and(providers)}"
    return text


def _left_alone_summary(skipped: int, skips: object) -> str:
    text = f"{_completion_count_text(skipped, 'agent')} left alone"
    breakdown = _skip_breakdown(skips) if isinstance(skips, list) else ""
    if breakdown:
        text += f" ({breakdown})"
    return text


def _drain_completion_toast(provider: str, completion: Any) -> tuple[str, str, str]:
    """Return (title, message, severity) for an automatic drain completion."""
    short = provider.upper()
    payload = getattr(completion, "payload", None)
    if getattr(completion, "collision", False):
        return (
            f"{short} drain",
            f"A {short} drain is already running; check Procs for its result.",
            "warning",
        )
    if not isinstance(payload, Mapping):
        if not getattr(completion, "success", False):
            proc_id = getattr(getattr(completion, "proc_info", None), "proc_id", "?")
            message = getattr(completion, "message", "")
            return (
                f"{short} drain failed",
                f"Proc {proc_id} failed; inspect Procs: {message}",
                "error",
            )
        return (f"{short} drain done", "Provider drain completed.", "information")
    error = payload.get("error")
    reason = error.get("reason") if isinstance(error, Mapping) else None
    if reason in {"not_disabled", "soft_disabled"}:
        return (
            f"{short} drain done",
            f"{short} is no longer hard-disabled; nothing was drained.",
            "information",
        )
    counts = payload.get("counts")
    counts_map = counts if isinstance(counts, Mapping) else {}
    relaunched = _payload_count(counts_map, "relaunched")
    skipped = _payload_count(counts_map, "skipped")
    failed = _payload_count(counts_map, "failed")
    skips = payload.get("skips")
    proc_id = getattr(getattr(completion, "proc_info", None), "proc_id", "?")
    if failed > 0:
        providers = _ok_target_providers(payload)
        body = (
            f"{_relaunched_summary(relaunched, providers)}; "
            f"{_completion_count_text(failed, 'agent')} failed; "
            f"{_left_alone_summary(skipped, skips)}."
            f" Inspect proc {proc_id} in Procs."
        )
        return (f"{short} drain finished with failures", body, "error")
    if relaunched > 0:
        providers = _ok_target_providers(payload)
        body = _relaunched_summary(relaunched, providers)
        if skipped > 0:
            body += f"; {_left_alone_summary(skipped, skips)}"
        body += "."
        return (f"{short} drained", body, "information")
    if skipped > 0:
        return (
            f"{short} drain: nothing could move",
            f"{_left_alone_summary(skipped, skips)}.",
            "warning",
        )
    return (
        f"{short} drain done",
        f"No agents depended on {short}; nothing to relaunch.",
        "information",
    )


class ProviderRoutingDrainMixin(_MixinBase):
    """Submit an automatic provider drain after a hard-disable write."""

    def _start_provider_drain(self, provider: str) -> None:
        app = self.app  # type: ignore[attr-defined]

        def on_complete(completion: Any) -> None:
            title, message, severity = _drain_completion_toast(provider, completion)
            app.notify(message, title=title, severity=severity)  # type: ignore[arg-type]

        try:
            submitted = submit_provider_drain(
                app,
                provider=provider,
                on_complete=on_complete,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
            app.notify(
                f"Could not start the {provider.upper()} drain: {exc}",
                severity="error",
            )
            return
        if not submitted:
            return
        app.notify(
            f"Relaunching agents stranded on {provider.upper()} onto enabled "
            "providers in the background. In-flight work on those agents "
            "restarts; chat transcripts are kept. Track it in Procs — "
            "another toast follows when it finishes.",
            title=f"Draining {provider.upper()}",
            timeout=10,
        )
