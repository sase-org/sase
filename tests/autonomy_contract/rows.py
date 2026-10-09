"""Data-only %auto behavior contract rows for epic E1.

Each row is ``(id, prompt or state, context)`` plus one expected outcome per
gate column: tale plan, epic plan, and question. Outcome values are ``ask``,
``approve+archive``, ``approve+launch``, ``first``, and ``launch_error``.

Later phases add rows and remove strict-xfail markers; they never edit the
expectation of a row outside the bold deliberate-change rows of the epic
plan ``plan:202610/auto_e1_autonomy_record.md``. The ``context`` names which
production helper seeds the row's live ``agent_meta.json`` (see
:mod:`tests.autonomy_contract.harness`); ``launch`` rows use the real launch
path only.

Consolidation map (P0 sources whose contract-row assertions live here too):
``tests/test_auto_grammar_parity.py`` (spelling accept/reject),
``tests/test_plan_auto_live_meta.py`` (live meta is the only source),
``tests/test_axe_plan_successor_auto_inherit.py`` (in-process tale inherit),
cross-tier cases in ``tests/test_plan_gates_execution.py``, and
``tests/plan_gate_turn/test_create.py``. Those files keep their unit-level
assertions; nothing was deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

ASK = "ask"
APPROVE_ARCHIVE = "approve+archive"
APPROVE_LAUNCH = "approve+launch"
FIRST = "first"
LAUNCH_ERROR = "launch_error"


@dataclass(frozen=True)
class ContractRow:
    """One contract row: prompt/state plus one outcome per gate column."""

    id: str
    prompt: str
    context: str
    tale: str
    epic: str
    question: str


# Launch-context spelling rows. These hold on master today.
SPELLING_ROWS: tuple[ContractRow, ...] = (
    ContractRow("no_auto", "Do the work", "launch", ASK, ASK, ASK),
    ContractRow(
        "bare", "%auto\nDo the work", "launch", APPROVE_ARCHIVE, APPROVE_LAUNCH, FIRST
    ),
    ContractRow(
        "short_a", "%a\nDo the work", "launch", APPROVE_ARCHIVE, APPROVE_LAUNCH, FIRST
    ),
    ContractRow(
        "plus", "%auto+\nDo the work", "launch", APPROVE_ARCHIVE, APPROVE_LAUNCH, FIRST
    ),
    ContractRow(
        "true",
        "%auto:true\nDo the work",
        "launch",
        APPROVE_ARCHIVE,
        APPROVE_LAUNCH,
        FIRST,
    ),
    ContractRow(
        "tale", "%auto:tale\nDo the work", "launch", APPROVE_ARCHIVE, ASK, FIRST
    ),
    ContractRow(
        "plan", "%auto:plan\nDo the work", "launch", APPROVE_ARCHIVE, ASK, FIRST
    ),
    ContractRow(
        "epic", "%auto:epic\nDo the work", "launch", ASK, APPROVE_LAUNCH, FIRST
    ),
    ContractRow("manual", "%auto:manual\nDo the work", "launch", ASK, ASK, ASK),
    ContractRow("off", "%auto:off\nDo the work", "launch", ASK, ASK, ASK),
)

# Invalid spellings fail at launch on every gate column.
INVALID_PROMPTS: tuple[str, ...] = (
    "%auto:foo\nDo the work",
    "%auto(plan=ask)\nDo the work",
    "%auto()\nDo the work",
    "%auto:epic_plan\nDo the work",
    "%auto:x(plan=ask)\nDo the work",
)

# State rows. ``a_off`` holds today; the rest are E1 deliberate changes
# owned by later phases (see the strict-xfail modules).
STATE_ROWS: tuple[ContractRow, ...] = (
    ContractRow("bare_a_off", "%auto\nDo the work", "a_off", ASK, ASK, ASK),
    # E1 target: A off then on restores the last profile (tale), not bare.
    ContractRow(
        "tale_a_off_on",
        "%auto:tale\nDo the work",
        "a_off_on",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    # E1 target: host-composed successors inherit the live record.
    ContractRow(
        "tale_pipe", "%auto:tale\nDo the work", "pipe", APPROVE_ARCHIVE, ASK, FIRST
    ),
    ContractRow(
        "tale_monitor_followup",
        "%auto:tale\nDo the work",
        "monitor_followup",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    ContractRow(
        "tale_gate_followup",
        "%auto:tale\nDo the work",
        "gate_followup",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    ContractRow(
        "tale_question_successor",
        "%auto:tale\nDo the work",
        "question_successor",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    # E1 target: a :plan monitor follow-up is not widened to bare.
    ContractRow(
        "plan_monitor_followup",
        "%auto:plan\nDo the work",
        "monitor_followup",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    # E1 target: A off on the live member means the next successor is manual.
    ContractRow(
        "bare_a_off_successor", "%auto\nDo the work", "a_off_successor", ASK, ASK, ASK
    ),
    # Already green today: in-process coder/replanner and epic workers.
    ContractRow(
        "tale_coder",
        "%auto:tale\nDo the work",
        "in_process_coder",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
    ContractRow(
        "tale_epic_worker",
        "%auto:tale\nDo the work",
        "epic_worker",
        APPROVE_ARCHIVE,
        ASK,
        FIRST,
    ),
)
