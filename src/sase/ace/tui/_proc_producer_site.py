"""Shared model and factory for the ACE proc-producer inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Classification = Literal["durable", "ui_only", "adapter", "infrastructure"]
CallKind = Literal[
    "direct_submit_durable",
    "session_worker",
    "duck_submit_durable",
]


@dataclass(frozen=True, slots=True)
class ProcProducerSite:
    """One inventoried ACE submit site or related infrastructure entry."""

    site_id: str
    source_path: str
    function: str
    kind: CallKind | Literal["definition", "test_double", "ui_worker"]
    proc_type: str
    classification: Classification
    owning_action: str
    domain_command: str
    identifiers: tuple[str, ...]
    result_kind: str
    fingerprint_inputs: tuple[str, ...]
    concurrency_keys: tuple[str, ...]
    optimistic_ui: str
    restart_recovery: str


def site(
    site_id: str,
    source_path: str,
    function: str,
    kind: CallKind | Literal["definition", "test_double", "ui_worker"],
    proc_type: str,
    classification: Classification,
    owning_action: str,
    domain_command: str,
    *,
    identifiers: tuple[str, ...] = (),
    result_kind: str = "success_message",
    fingerprint_inputs: tuple[str, ...] = (),
    concurrency_keys: tuple[str, ...] = (),
    optimistic_ui: str = "none",
    restart_recovery: str = "replay from durable result envelope",
) -> ProcProducerSite:
    return ProcProducerSite(
        site_id=site_id,
        source_path=source_path,
        function=function,
        kind=kind,
        proc_type=proc_type,
        classification=classification,
        owning_action=owning_action,
        domain_command=domain_command,
        identifiers=identifiers,
        result_kind=result_kind,
        fingerprint_inputs=fingerprint_inputs or identifiers,
        concurrency_keys=concurrency_keys,
        optimistic_ui=optimistic_ui,
        restart_recovery=restart_recovery,
    )
