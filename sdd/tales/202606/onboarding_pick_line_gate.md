---
create_time: 2026-06-30 07:21:12
status: done
prompt: sdd/prompts/202606/onboarding_pick_line_gate.md
---
# Plan: Gate the onboarding "pick a project or CL first" line on having launch targets

## Goal / product context

The Agents-tab first-run onboarding panel ("Welcome to sase ace") shows a "Launch your first agent" card. Its second
bullet currently always reads:

```
+   pick a project or CL first.
```

This bullet advertises the `+` keymap (`start_custom_agent`), which opens the **Project/PR selection modal**
(`ProjectSelectModal`). For a brand-new user with nothing configured, that modal is empty — it has no projects and no
eligible PRs to pick — so the bullet tells the user to "pick a project or CL" when there is in fact nothing to pick. We
want to **hide this one bullet** whenever the `+` modal would present no selectable launch targets, while leaving the
rest of the onboarding card (the `<space>` "Start from the prompt" bullet, the "Works from any tab; shell: sase ace"
footer, and the other cards) untouched.

Only the single `+ pick a project or CL first.` line is conditional. Everything else on the onboarding page renders
exactly as today.

## Current behavior (where things live)

- **Widget that renders the bullet:** `src/sase/ace/tui/widgets/agent_onboarding.py`.
  `AgentOnboarding._build_launch_card(registry)` unconditionally appends the `+` keycap + "pick a project or CL first."
  text. `render_content(registry)` / `refresh_content()` / `compose()` drive it.
- **Visibility of the whole panel:** `src/sase/ace/tui/actions/agents/_display_detail.py`.
  `_should_show_agents_onboarding()` returns True only after first load, with no active agent search query, and when the
  **visible** agent list `_agents` is empty. `_sync_agents_onboarding(...)` shows/hides the panel and, when showing it,
  calls `onboarding.set_keymap_registry(...)` / `onboarding.refresh_content()`.
- **What the `+` modal shows** (the panel referenced by the request): `action_start_custom_agent` in
  `src/sase/ace/tui/actions/agent_workflow/_entry_custom.py` opens `ProjectSelectModal(exclude_project_names={"home"})`.
  In `src/sase/ace/tui/modals/project_select_modal.py::_load_items`, the modal rows come from:
  1. **Projects** — `list_launchable_projects()` (from `src/sase/ace/tui/modals/project_discovery.py`), minus the
     excluded `home`.
  2. **PRs / CLs** — `find_all_changespecs()` whose `remove_workspace_suffix(status)` is one of `WIP`, `Draft`, `Ready`,
     `Mailed`. (`include_all=False` here, so there is no synthetic "ALL" row.)

So "the panel triggered by `+` has something to pick" == "there is at least one launchable project (excluding `home`)
**or** at least one eligible PR/CL."

## Key decision: what counts as a "launch target"

The request says to show the line when "one or more projects that are configured ... will show up in the panel." The
panel itself, and the line's own wording ("pick a project **or CL** first"), cover both projects and PRs/CLs.

**Recommended semantics (primary):** show the line when the `+` modal would contain **at least one selectable row** —
i.e. at least one launchable project (excluding `home`) **OR** at least one eligible PR/CL. Rationale: the line offers
"project or CL"; it is only misleading when _neither_ exists. If the user has a PR but no launchable project, "pick a …
CL" is still actionable, so the line should stay.

**Alternative (strict, projects-only):** gate purely on `list_launchable_projects()` (the `[P]` rows), ignoring PRs.
This matches the most literal reading of "projects" in the request.

The implementation isolates this choice in one pure helper, so flipping between the two is a one-line change. **I
recommend the primary semantics and am flagging this as the one decision to confirm at plan review.**

## Design / approach

The decision of whether to render the bullet is a **presentation-only** choice. It does **not** cross the Rust core
backend boundary: it is composed entirely from existing Python discovery helpers (`list_launchable_projects`,
`find_all_changespecs_cached`) that already wrap core queries. No `sase-core` / `sase_core_rs` changes are needed (same
conclusion as the recent `agents_onboarding_visible_gate` change).

### Performance constraint

`list_launchable_projects()` and changespec discovery both do **synchronous disk I/O**. Per the TUI performance rules,
that must never run on the Textual event loop inside a refresh/display handler such as `_sync_agents_onboarding`. We
therefore compute the flag **off-thread** and render the card from a **cached boolean**, refreshing it in the background
— the standard "show cached instantly, reload in the background, coalesce concurrent requests" pattern.

We also want to avoid taxing the steady-state agent-refresh loop for the common case (users **with** agents, where
onboarding is never shown). So the off-thread computation is **triggered only while the onboarding panel is actually
visible** (i.e. from `_sync_agents_onboarding` on the show path), not on every agents reload. This naturally covers
every reason onboarding can appear — truly empty, or only-hidden/folded rows — because it keys off onboarding visibility
rather than the load internals.

### Data flow

1. **Pure helper (testable seam, no I/O):** `launch_targets_available(projects: list[str], changespecs) -> bool` —
   returns `bool([p for p in projects if p != "home"]) or any(eligible PR status)`. This is where the
   primary-vs-alternative semantics live. Trivially unit-tested.

2. **Disk wrapper (patchable seam):** a small function/method that reads `list_launchable_projects()` +
   `find_all_changespecs_cached(...)` and feeds the pure helper. This is the thing integration tests monkeypatch to
   drive deterministic states.

3. **Cached state on the app** (initialized in `src/sase/ace/tui/actions/_state_init.py` alongside
   `_agents_first_load_done`, typed in the relevant state mixin):
   - `_agents_onboarding_launch_targets_available: bool` — last computed flag (default `False`, so a fresh user never
     flashes the line).
   - an in-flight/coalesce guard so repeated `_sync_agents_onboarding` ticks don't pile up workers.

4. **`_sync_agents_onboarding` (show path):** render the launch card with the cached flag (folded into the existing
   registry/refresh call to avoid a double render), then schedule a coalesced off-thread recompute
   (`run_worker(thread=True)` / `to_thread`, marshalled back via `call_later`/ `call_after_refresh`). On completion,
   store the flag and, if it changed and onboarding is still visible, update only the launch-card `Static`
   (`#agent-onboarding-launch`). The scheduler is written defensively (guarded `getattr` for `run_worker`) so the
   lightweight `DetailMixin` test harness is unaffected.

5. **Widget (`AgentOnboarding`):**
   - add `self._launch_targets_available: bool` (default `False`) + a setter that re-renders the launch card;
   - thread the flag through `compose()` / `refresh_content()` / `render_content(...)` into
     `_build_launch_card(registry, launch_targets_available)`, which appends the `+` keycap + "pick a project or CL
     first." line **only when the flag is True**;
   - keep `render_content`'s new parameter defaulted so unrelated existing callers/tests are stable, but cover both
     states with explicit tests.

### Default / flicker note

Default `False` ("line hidden") is correct for the dominant onboarding scenario (a new user with nothing configured) —
no flicker. A user who somehow has projects/PRs but zero visible agents may see the line appear one frame after the
panel mounts; this is acceptable for a static guide and is the only edge with any visible change.

## Files expected to change

- `src/sase/ace/tui/widgets/agent_onboarding.py` — conditional bullet + flag plumbing.
- `src/sase/ace/tui/actions/agents/_display_detail.py` — read cached flag on show, schedule off-thread recompute, update
  card on completion.
- `src/sase/ace/tui/actions/_state_init.py` (+ the state-mixin type declaration) — new cached attributes.
- A small helper module (pure helper + disk wrapper) — most naturally next to
  `src/sase/ace/tui/modals/project_discovery.py` (or a focused new module under the agents actions package), reusing
  `list_launchable_projects` and `find_all_changespecs_cached`.
- Tests (below).

No keymap/default-config changes (no new or changed option), so no `default_config.yml`, help-modal, or footer updates
are required (the bullet is onboarding copy, not a footer binding).

## Tests

1. **Pure helper unit tests:** projects-only present → True; eligible PR only → True; both empty → False; only `home` in
   projects → False; only ineligible-status changespecs (e.g. Submitted) → False. (Encodes the chosen semantics; one
   case documents the projects-only alternative.)
2. **Widget rendering** (`tests/ace/tui/widgets/test_agent_onboarding.py`): `render_content` / `_build_launch_card`
   **includes** the "pick a project or CL first." text when `launch_targets_available=True` and **omits** it when
   `False`, while the `<space>` "Start from the prompt" bullet and "shell: sase ace" footer remain present in both. Keep
   the existing tabs/docs/keymap tests green.
3. **Integration** (`tests/ace/tui/test_agents_onboarding.py`): with the disk wrapper patched to report "has targets",
   mount the empty Agents tab and assert the onboarding panel shows the bullet (after the background recompute settles);
   with it patched to "no targets", assert the panel shows but the bullet is absent. Reuse the existing
   `patch_startup_loaders` / `wait_for_startup` harness and add a wait for the recompute worker. Keep the existing
   onboarding visibility tests unchanged.
4. **PNG visual snapshot:** add/adjust an empty-Agents-tab golden for the "no launch targets" state (bullet hidden) via
   the dedicated visual suite; accept new goldens only with `--sase-update-visual-snapshots`.

## Verification

- Targeted pytest subsets: the onboarding widget tests, the onboarding visibility integration tests, and the
  empty-Agents PNG snapshot suite.
- `just install` then `just check` for lint/type/static gates. The pre-existing, environment-only failures already
  documented in memory are unrelated to this change: the `default_effort` llm_provider failures, the `sase validate`
  memory-freshness gate, and sandbox SIGTERM kills of the full test run — rely on the targeted subsets plus the static
  gates.

## Out of scope

- Any change to _whether_ the onboarding panel appears (the visible-list gate is unchanged) or to which rows the `+`
  modal shows.
- Reworking other onboarding copy/cards.
- Surfacing launch targets anywhere outside this single bullet.
