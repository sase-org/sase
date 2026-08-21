"""Infrastructure entries for the ACE proc-producer inventory."""

from __future__ import annotations

from sase.ace.tui._proc_producer_site import ProcProducerSite, site


INFRASTRUCTURE: tuple[ProcProducerSite, ...] = (
    site(
        "infra.submit_durable",
        "src/sase/ace/tui/actions/_proc_action_submission.py",
        "_submit_durable_proc",
        "definition",
        "",
        "infrastructure",
        "ProcActionsMixin",
        "",
        restart_recovery="submit only; observer decodes typed result envelope",
    ),
    site(
        "infra.submit_session",
        "src/sase/ace/tui/actions/_proc_action_submission.py",
        "_submit_session_worker",
        "definition",
        "",
        "infrastructure",
        "ProcActionsMixin",
        "",
        restart_recovery="session-local worker; not durable",
    ),
    site(
        "infra.proc_observer",
        "src/sase/ace/tui/proc_observer.py",
        "ProcObserver",
        "definition",
        "",
        "infrastructure",
        "ProcObserver",
        "",
        restart_recovery="read-only durable proc projection",
    ),
    site(
        "infra.observer_completion",
        "src/sase/ace/tui/actions/_proc_action_completion.py",
        "_apply_proc_observer_snapshot",
        "definition",
        "",
        "infrastructure",
        "ProcActionsMixin",
        "",
        restart_recovery="live-session callback from observer envelope",
    ),
)
