---
create_time: 2026-06-23 18:31:14
bead_id: sase-56
tier: epic
status: done
prompt: sdd/prompts/202606/auto_approve_menu_and_tale_directive.md
---
# Plan: `%tale` Auto-Approval Directive + Auto-Approve Quick-Action Menu

## Summary

Two intertwined changes to how a SASE agent's plan auto-approval is configured:

1. **Directive migration & new directive.** Rename the `%a`/`%approve` directive to `%p`/`%plan` (keeping
   `%a`/`%approve` as a hidden deprecated alias), and add a brand-new `%t`/`%tale` directive that auto-approves a
   submitted plan as a **tale**. `%time` gives up its `%t` short alias (long form `%time` only). The directive family
   becomes a clean parallel set: `%plan` / `%tale` / `%epic`.

2. **A new auto-approve menu (TUI model).** Today the `a` key on the Agents tab _cycles_ an agent through a 3-state
   toggle (off → normal-plan → epic → off). Replace that cycle with a small, beautiful **modal** that lists the
   auto-approval options, each selectable with a single key press, with the agent's current state clearly marked. The
   menu exposes the new **Tale** option, which the toggle never could.

These are decoupled at the seam between the directive/backend contract and the TUI presentation, which lets the work be
split across three independent agent instances.

### Decisions already ratified by the user (Q&A)

- **Q1 — `%plan` collision:** Repurpose `%plan`. `%p`/`%plan` becomes the canonical name for what `%approve` does today
  (auto-approve the submitted plan as a normal plan). The dead, Rust-only "enable plan mode" meaning of `%plan` is
  dropped.
- **Q2 — `%approve` back-compat:** Keep `%a`/`%approve` as a **hidden deprecated alias** that still parses to the same
  behavior. `%p`/`%plan` becomes the canonical/documented spelling; the bead generator and docs switch to `%plan`.
- **Q3 — `%time` alias:** Drop the `%t` alias from `%time`. `%time` keeps its long form only; `%t` cleanly becomes
  `%tale`.

---

## Background: how things work today

### Directive registries (two parallel sources of truth)

- **Rust** (`crates/sase_core/src/editor/directive.rs`, in the `sase-core` linked repo): the `DIRECTIVES` array drives
  editor/LSP completion & hover (Neovim) and `canonical_directive_name()` alias resolution used by the agent-launch
  fan-out planner. Each entry has a `name` plus one optional short `alias`. Relevant entries today:
  - `approve` / alias `a` — "Run the agent fully autonomously"
  - `plan` / alias `p` — "Enable plan mode" (latent; the Python runtime ignores it)
  - `epic` / no alias — "Enable plan mode and approve the plan as an epic"
  - `time` / alias `t` — "Wait for a duration or absolute wall-clock time"
- **Python** (`src/sase/xprompt/_directive_types.py` + `directives.py`): the _runtime_ parser. `_KNOWN_DIRECTIVES`,
  `_DIRECTIVE_ALIASES`, and the `PromptDirectives` dataclass. Note: the Python side already **removed** `%plan`/`%p` —
  they currently parse as inert unknown text (see `tests/test_directives_flags.py`). `_DIRECTIVE_ALIASES` maps
  `a→approve`, `t→time`, etc.
- The two registries are **not** bound by a shared golden table; they are kept in parity by hand and by their respective
  test suites. (This is unlike `vcs_project_completion`, which _does_ share a golden vector table.) Both must be updated
  deliberately.

### Auto-approval data flow

- A prompt directive is parsed into `PromptDirectives` (`directives.py`), then `src/sase/axe/run_agent_directives.py`
  writes the result into `agent_meta.json`:
  - `%approve` → `agent_meta["approve"] = True`
  - `%epic` → `agent_meta["auto_approve_plan_action"] = "epic"` **and** `agent_meta["plan"] = True`
- When an agent submits a plan, `src/sase/main/plan_approve_handler.py::get_auto_plan_approval_action()` resolves the
  action: it checks env vars, then `agent_meta["auto_approve_plan_action"]` (normalized by `_normalize_plan_action`,
  which today only recognizes `"approve"` and `"epic"`), then falls back to `"approve"` if `agent_meta["approve"]` is
  truthy. `PlanAutoApprovalAction = Literal["approve", "epic"]`.
- The downstream plan-approval protocol (`src/sase/plan_approval_actions.py`) **already** fully supports `"tale"`:
  `PLAN_APPROVAL_KINDS` includes it, `_plan_response_json("tale")` →
  `{"action": "approve", "commit_plan": True, "run_coder": True}`, `_persisted_plan_action` maps a committed approve to
  `"tale"`, and `_archive_plan_for_approval` archives tales to `sdd/tales/YYYYMM/`. **The only missing link for tale
  auto-approval is the `_normalize_plan_action` / `PlanAutoApprovalAction` gate.**

### The `a` keymap toggle today

- Binding: `accept_proposal` → key `a` (`src/sase/default_config.yml`, `bindings.py`).
- On the Agents tab, `src/sase/ace/tui/actions/proposal_rebase.py::action_accept_proposal` routes: `WAITING INPUT`
  status → answer-HITL; approve-eligible status → `action_toggle_approve`.
- `src/sase/ace/tui/actions/agents/_approve.py::_next_auto_approval_state` cycles off → (`approve=True`, action=`None`)
  → (`approve=True`, action=`"epic"`) → off, persisting via `_persist_plan_auto_approval` to `agent_meta.json`.
- Agent model fields: `agent.approve: bool`, `agent.auto_approve_plan_action: str | None`
  (`src/sase/ace/tui/models/agent.py`). The filesystem loader (`.../models/_loaders/_meta_enrichment_filesystem.py`)
  sets `approve=True` whenever `auto_approve_plan_action` is present, so the icon shows for any auto-approval kind.
- Visual: `src/sase/ace/tui/widgets/_agent_list_render_agent.py` renders `⚡` (normal) or `⚡E` (epic). Footer
  (`_keybinding_bindings.py`) shows a dynamic `approve`/`epic`/`unapprove` label; help modal
  (`modals/help_modal/agents_bindings.py`) documents the toggle.
- There is a separate, unrelated **manual** plan-approval modal — `ApproveOptionsModal` ("Custom Approval", offering
  approve/tale/epic/legend) pushed from `plan_approval_modal.py` when a human reviews a submitted plan. It is the
  closest visual reference for the new menu but serves a different flow; do not conflate them.

---

## Target design

### Directive family (after migration)

| Spelling         | Canonical | Effect                                                                 | Completion            |
| ---------------- | --------- | ---------------------------------------------------------------------- | --------------------- |
| `%plan`, `%p`    | `plan`    | Auto-approve the submitted plan as a normal plan (today's `%approve`). | advertised            |
| `%tale`, `%t`    | `tale`    | Plan first, then auto-approve & commit the plan as a **tale**.         | advertised            |
| `%epic`          | `epic`    | Plan first, then auto-approve & commit the plan as an epic.            | advertised (no alias) |
| `%approve`, `%a` | `plan`    | Deprecated alias of `%plan`; still parses, **hidden** from completion. | hidden                |
| `%time`          | `time`    | Wait for a duration / wall-clock time. **No short alias.**             | advertised            |

Notes:

- `%plan` does **not** enable plan mode (Q1) — it is purely "auto-approve as a normal plan", exactly matching today's
  `%approve`. It continues to set `agent_meta["approve"] = True`.
- `%tale`, by symmetry with `%epic`, sets both `agent_meta["auto_approve_plan_action"] = "tale"` and
  `agent_meta["plan"] = True` (so the agent's plan-review display behaves like an epic's).
- The "hidden deprecated alias" concept is new to both registries and must be added to each: the alias still resolves
  through `canonical_directive_name` (Rust) / `_DIRECTIVE_ALIASES` (Python) but is excluded from advertised completion
  candidates.

### The Auto-Approve menu (centerpiece — design lead)

A `ModalScreen` pushed when `a` is pressed on an approve-eligible agent. Goals: **intuitive, reliable, beautiful.** It
mirrors the visual language of the existing `ApproveOptionsModal` (double border, centered bold title, `$surface`
background, selected-row highlight) so it feels native, but its interaction model is **single-key instant select** (the
user's explicit requirement) rather than move-cursor-then-confirm.

Layout sketch:

```
╔════════════════ Auto-Approve ════════════════╗
║                                               ║
║    p   Plan      approve the plan as-is        ║
║    t   Tale      approve & commit as a tale     ║
║    e   Epic      approve & commit as an epic     ║
║  ▸ d   Disable   turn off auto-approval          ║   ◂ marker on current state
║                                               ║
║    agent: my-agent.3                          ║
║    esc cancel                                 ║
╚═══════════════════════════════════════════════╝
```

Interaction & reliability:

- **Single key applies immediately:** `p`/`t`/`e`/`d` select the option, dismiss the modal, and apply the change. No
  Enter needed.
- **Current state is marked** with a `▸` and highlighted styling so the user always sees where the agent stands before
  choosing (orientation, not a cursor).
- `esc` / `q` cancels with no change.
- Override `on_key` to `stop()` stray printable characters (the established modal pattern), so keys never leak to the
  app's custom-mode prefix handling.
- Choices are defined as a **data-driven list** (key, id, label, consequence) so a future `Legend` option is a one-line
  addition. (Legend is intentionally **out of scope**: there is no `%legend` directive, and we want menu/directive
  parity. Note this explicitly in code.)
- Return value: `Literal["plan","tale","epic","disable"]` or `None` (cancel).

Mnemonics intentionally mirror the directive aliases: `p`→Plan, `t`→Tale, `e`→Epic (and `d`→Disable).

State ↔ persistence mapping (reuses `_persist_plan_auto_approval`, matching today's epic handling):

| Menu choice | in-memory `agent.approve` | `auto_approve_plan_action` | persisted `approve` key     |
| ----------- | ------------------------- | -------------------------- | --------------------------- |
| Plan        | `True`                    | `None`                     | written `True`              |
| Tale        | `True`                    | `"tale"`                   | removed (action carries it) |
| Epic        | `True`                    | `"epic"`                   | removed (action carries it) |
| Disable     | `False`                   | `None`                     | removed                     |
| cancel      | unchanged                 | unchanged                  | unchanged                   |

### Visual / surface updates

- Row icon: add `⚡T` for tale alongside `⚡` (normal) and `⚡E` (epic).
- Footer: the `a` action now always opens a menu on eligible agents, so replace the dynamic `approve`/`epic`/`unapprove`
  label with a single concise `auto-approve` label.
- Help modal & agent-row glyph legend: document the menu and the `⚡T` glyph.
- `default_config.yml`: **no change** — the key (`a`) and action name (`accept_proposal`) are unchanged; only the
  action's behavior changes. (Per repo convention, default*config only needs edits when a _keymap* changes.)

---

## Phasing

Three phases, each completed by a distinct agent instance. The split follows the codebase's Rust-core ↔ Python-backend ↔
Python-TUI boundaries, so each phase is a coherent, independently shippable, independently testable unit.

> Implementation-agent reminders that apply to every phase:
>
> - This repo requires `just install` then `just check` to pass before completing (ephemeral workspaces).
>   Bead/markdown-only exceptions do not apply here.
> - All `sase` CLI options must have both a long and short form (n/a here, but keep in mind).
> - Treat all agent runtimes uniformly; no runtime-specific branching.

### Phase 1 — Directive registry migration (Rust core + Python parser + backend contract)

**Goal:** Make `%plan`/`%tale`/`%epic` the real directive family end-to-end, with `%approve`/`%a` as a hidden deprecated
alias and `%time` losing `%t`. After this phase a prompt containing `%tale` fully auto-approves a submitted plan as a
tale; `%plan`/`%approve` auto-approve as a normal plan. **No TUI keymap/menu/render changes** — the `a` toggle keeps its
current 3-state behavior.

Scope:

- **Rust** (`sase-core` linked repo — open it with `sase workspace open -p sase-core -r "<reason>" <N>` using this
  primary repo's workspace number, then edit under the printed path):
  - `crates/sase_core/src/editor/directive.rs`:
    - Repurpose the `plan` entry's description → "Auto-approve the submitted plan as a normal plan" (keep alias `p`).
    - Add a `tale` entry (alias `t`, no argument), description e.g. "Auto-approve the submitted plan as a tale".
    - Remove the `t` alias from `time` (`alias: None`).
    - Remove the `approve` entry from the advertised `DIRECTIVES` array and instead introduce a small
      **deprecated-alias** map (e.g. `DEPRECATED_ALIASES: &[(&str,&str)] = &[("approve","plan"),("a","plan")]`)
      consulted by `canonical_directive_name` (so `%approve`/`%a` still resolve to `plan`) but **not** by
      `build_directive_completion_candidates` (so they are hidden from completion).
    - Update the `directive_argument_candidates` match arms (`approve|edit|plan|epic|hide` → include `tale`, handle the
      now-aliasless `time`).
    - Update Rust unit tests: alias resolutions (`p→plan`, `t→tale`, `a→plan`, `approve→plan`), `time` has no alias, the
      `%t` completion test now yields `%tale` (not `%time`), and `%approve`/`%a` resolve but are absent from completion
      candidates.
  - Confirm the agent-launch fan-out planner (`crates/sase_core/src/agent_launch/`) does not special-case the
    `approve`/`plan` canonical names in a way the rename would break (it keys off `%wait`/`%alt`/`%model`/`%repeat`);
    adjust + retest if it does.
  - `cargo test` (or the repo's Rust test runner) green in `sase-core`.
- **Python** (this repo):
  - `src/sase/xprompt/_directive_types.py`: drop `approve` from `_KNOWN_DIRECTIVES`; add `plan` and `tale`. Update
    `_DIRECTIVE_ALIASES` → `p→plan`, `t→tale`, add full-word `approve→plan` and `a→plan` (remove `t→time`). Add a
    `_DEPRECATED_DIRECTIVE_ALIASES = frozenset({"a","approve"})`. Add a `tale: bool = False` field to `PromptDirectives`
    (keep the existing `approve: bool` field as the normal-plan flag).
  - `src/sase/xprompt/directives.py`: build `approve="plan" in expanded_args` and `tale="tale" in expanded_args`
    (aliases already resolve to canonical before this point — verify the resolution at lines ~101 and ~294 handles
    full-word `approve`). Ensure duplicate-directive and unknown-token handling still behaves.
  - `src/sase/ace/tui/widgets/directive_completion.py`: `_USER_FACING_DIRECTIVES` now follows `_KNOWN_DIRECTIVES` (shows
    `plan`/`tale`, not `approve`). Add argument-hint/description entries for `plan` and `tale`; drop `approve`. Exclude
    `_DEPRECATED_DIRECTIVE_ALIASES` from the advertised alias detail (so `plan` advertises only `p`, not `a`/`approve`).
  - `src/sase/axe/run_agent_directives.py`: keep `if directives.approve: agent_meta["approve"]=True`; add
    `if directives.tale: agent_meta["auto_approve_plan_action"]="tale"` and `agent_meta["plan"]=True` (mirroring the
    `%epic` block).
  - `src/sase/main/plan_approve_handler.py`: extend `PlanAutoApprovalAction` to `Literal["approve","epic","tale"]` and
    make `_normalize_plan_action` recognize `"tale"`.
  - `src/sase/bead/work.py`: switch the three emitted `"%approve"` lines to `"%plan"`.
  - Tests: rewrite the `tests/test_directives_flags.py` "removed `%plan`" section (now `%plan`/`%p` parse to
    `approve=True`); add `%tale`/`%t` tests; add deprecated `%approve`/`%a` still-works tests; assert `%time` no longer
    accepts `%t` (it parses as `%tale`); add a `_normalize_plan_action` "tale" test. Update any other tests asserting
    the old contract.
- **Docs:** grep the repo for literal `%approve` in user-facing docs/skill/xprompt content and switch canonical
  references to `%plan` (leaving a note that `%approve` is a deprecated alias).

**Done when:** Rust + Python test suites green; `just check` passes; a manual trace shows `%tale` → `agent_meta` →
`get_auto_plan_approval_action()` returns `"tale"`.

### Phase 2 — The Auto-Approve menu modal + keymap rewiring (TUI)

**Goal:** Replace the `a`-key 3-state toggle with the single-key Auto-Approve menu, including the new Tale option.
Depends on Phase 1 (tale recognized by the backend).

Scope:

- New modal `src/sase/ace/tui/modals/auto_approve_modal.py`: `ModalScreen` returning
  `Literal["plan","tale","epic","disable"] | None`, with the data-driven choice list, current-state marker, single-key
  instant select, `on_key` printable-char guard, and `esc`/`q` cancel. Export it from
  `src/sase/ace/tui/modals/__init__.py`.
- Styling in `src/sase/ace/tui/styles.tcss`: a block mirroring the `ApproveOptionsModal` styling (centered bold title,
  `border: double $primary`, `$surface` background, selected-row highlight in `$success`, key letters in an accent
  color, dim consequence text).
- Rewire `src/sase/ace/tui/actions/agents/_approve.py`: replace the `action_toggle_approve` cycle with an
  `action_open_auto_approve_menu` that pushes the modal and, in the dismiss callback, sets `agent.approve` /
  `agent.auto_approve_plan_action` per the state↔persistence table above and calls `_persist_plan_auto_approval` (keep
  the eligibility gate, optimistic in-memory patch, and rollback on persist failure). Keep `_persist_plan_auto_approval`
  as-is.
- Update the router `src/sase/ace/tui/actions/proposal_rebase.py::action_accept_proposal` to call the new menu action
  (the HITL branch is unchanged).
- Tests: modal key tests (`p`/`t`/`e`/`d` return correct value; current-state marker correct for each input state; `esc`
  → `None`; printable chars don't leak); an action-integration test (open menu → choose tale →
  `agent.auto_approve_plan_action == "tale"` and persist called with the right args; choose disable → cleared; cancel →
  unchanged). Replace the obsolete cycle tests in `tests/ace/tui/test_agent_toggle_approve.py`.

**Done when:** pressing `a` on an eligible agent opens the menu; each key applies & persists the right state;
`just check` passes.

### Phase 3 — Presentation polish: icon, footer, help, snapshot (TUI)

**Goal:** Make every surface reflect the new model and lock in the look. Depends on Phases 1–2.

Scope:

- Row icon: `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — add the `⚡T` (tale) branch next to `⚡`/`⚡E`.
  Update the glyph legend in `src/sase/ace/tui/widgets/_agent_list_styling.py`.
- Footer: `src/sase/ace/tui/widgets/_keybinding_bindings.py` — replace the dynamic `approve`/`epic`/`unapprove` label
  for `accept_proposal` (agents tab) with a single `auto-approve` label shown on approve-eligible agents.
- Help: `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — update the `accept_proposal` description to "Open
  auto-approve menu / answer HITL"; keep the help-box width convention. Refresh any other `?`-popup / help text
  mentioning the old toggle.
- `src/sase/ace/tui/models/agent.py`: update the `approve` / `auto_approve_plan_action` field comments to mention the
  tale value.
- Tests: render tests for the `⚡T` icon and footer label; **PNG visual snapshot** of the Auto-Approve modal added under
  `tests/ace/tui/visual/snapshots/png/` via `just test-visual --sase-update-visual-snapshots` (accept the new golden),
  plus snapshots for any changed agent-row/footer states.

**Done when:** tale agents show `⚡T`, footer/help describe the menu, the modal has a committed visual snapshot, and
`just check` + `just test-visual` pass.

---

## Risks & notes

- **Two registries, no shared golden table.** Rust (Phase 1 Rust portion) and Python (Phase 1 Python portion) must be
  changed in lockstep within Phase 1 to avoid a confusing window where the editor advertises directives the runtime
  ignores (or vice-versa). Keep them in one phase.
- **Behavior change for `%plan` passthrough.** `%plan`/`%p` previously survived in prompts as inert text (intentionally,
  per existing tests). After Phase 1 they are directives. The risk is low (repo grep shows `%plan` only in those tests +
  a comment), but the implementing agent should grep for live `%plan` usage in xprompts/prompts before assuming it is
  safe.
- **Manual vs auto approval modals.** The new `auto_approve_modal` configures _future_ auto-approval; it must not be
  confused with `ApproveOptionsModal`/`plan_approval_modal` (the human reviewing an already-submitted plan). Different
  flow, similar styling on purpose.
- **`agent.approve` stays `True` for tale/epic in memory** (drives the icon) while the persisted `approve` key is
  omitted; the filesystem loader re-derives `approve=True` from `auto_approve_plan_action` on reload. Preserve this
  asymmetry.
- **Legend deliberately excluded** from the menu and directives to keep menu/directive parity; the data-driven choice
  list makes adding it later trivial if desired.
