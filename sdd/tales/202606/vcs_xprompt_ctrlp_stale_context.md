---
create_time: 2026-06-08 07:14:18
status: done
prompt: sdd/prompts/202606/vcs_xprompt_ctrlp_stale_context.md
---
# Fix: `<ctrl+p>` VCS xprompt prefill launches in the wrong workspace / desyncs `<ctrl+space>`

## Problem statement

The prompt input bar lets the user prefill the bar with a recent **VCS xprompt workflow** (`#gh:sase`, `#cd:~/org`, …)
via two keymaps:

- `<ctrl+space>` (`start_agent_from_changespec`) — opens the prompt bar prefilled with the **last agent selection**
  (e.g. `#gh:sase `).
- `<ctrl+n>` / `<ctrl+p>` — cycle the bar text through the **VCS xprompt MRU** list.

Two related defects occur when the user opens the bar with one VCS ref and then cycles to a _different_ ref before
launching:

1. **Wrong-workspace launch + misleading toast.** After `<ctrl+p>` changes the prefill to a different workflow and the
   user submits, the launch toast (and, in the failure path, the actual workspace) reflects the project from the
   **initial** prompt (e.g. `sase`), not the cycled-to ref.
2. **`<ctrl+space>` replays the stale ref.** After launching a `<ctrl+p>`-prefilled agent, pressing `<ctrl+space>`
   repopulates the bar with the _previously_ logged workflow instead of the one that was just used.

## Root cause (diagnosed with reproductions)

The `_prompt_context` (`ctx`) is **baked once** when the prompt bar opens. For the `<ctrl+space>` flow this happens in
`EntryPointsMixin.action_start_agent_from_changespec` → `_start_custom_agent_from_selection` →
`_show_prompt_input_bar_for_home` (`_prompt_bar_mount.py:_setup_home_prompt_context`), which stamps `ctx.display_name` /
`ctx.history_sort_key` / `ctx.project_name` / `ctx.workspace_dir` / `ctx.is_home_mode` from the **last selection**
(`sase`).

Cycling with `<ctrl+p>` (`PromptTextArea._on_key`, `prompt_text_area.py:341-379`) only mutates the _text_ of the bar —
it never updates `ctx`. The launch path is expected to re-derive the identity from the submitted text, but it leaks the
stale `ctx` in two places:

### Defect A — immediate toast uses pre-resolution `ctx.display_name`

`AgentLaunchStartMixin._finish_agent_launch` (`_launch_start.py:69`) fires
`self.notify(f"Launching agent for {ctx.display_name}...")` **synchronously**, before the worker thread re-resolves the
ref. So this toast _always_ shows the baked initial project (`sase`) when the user cycled to something else — even when
the cycled ref is perfectly valid.

### Defect B — home-mode resolution silently falls back to the stale `ctx`

`AgentLaunchBodyMixin._run_agent_launch_body` (`_launch_body.py:209-275`) re-resolves the VCS ref from the submitted
prompt inside `if ctx.is_home_mode:`. It only overrides `ctx.display_name` / `ctx.project_name` / `ctx.workspace_*`
**when a `vcs_ref` is resolved**. When the cycled ref does **not** resolve (`vcs_ref is None` after both the workflow
loop and the `resolve_known_project_vcs_launch_ref` fallback), the body keeps the **entire baked context**:

- launches in the baked **home/initial** workspace (wrong workspace),
- the post-launch `"Agent started for {display_name}"` toast (`_launch_body.py:506`) shows the stale `sase`,
- `save_replayable_vcs_selection` (`_launch_body.py:271`) and `record_resolved_vcs_xprompt_usage`
  (`_launch_body.py:274`) are **skipped** (both gated on `vcs_ref is not None`), so `_last_custom_agent_selection` and
  the MRU are never updated → `<ctrl+space>` keeps replaying the previous selection (Defect/bug #2).

### Defect C — the MRU keeps refs that no longer resolve (enables Defect B)

`load_launchable_vcs_xprompt_mru` → `_is_stale_known_project_prefix` (`history/vcs_xprompt_mru.py:80-99`) only prunes
prefixes whose **project** is a known non-launchable project. A CL/PR/changespec-name ref (e.g. `#gh:old_cl`) whose
changespec has since been submitted/archived is **not** a project file, so it is treated as "unclassified" and **kept**.
Cycling to such a ref later yields an unresolvable prompt → Defect B.

### Evidence (reproductions run against the real code)

- Cycling + submission deliver the **live** cycled text (`#cd:~/org do work`, `#git:foo do work`) to
  `_handle_text_submission` / `_finish_agent_launch`. The text plumbing is correct.
- Launch body with a baked `display_name="sase"` ctx + a **resolvable** `#git:foo` prompt: launches in `foo`, updates
  `_last_custom_agent_selection` → `foo`. **But** the first toast still says `"Launching agent for sase..."` (Defect A).
- Same baked ctx + an **unresolvable** `#git:stalepr` prompt: launches in **home** (`is_home_mode=True`),
  `_last_custom_agent_selection` stays the previous value, no MRU update — exactly reproducing both reported bugs
  (Defect B).

## Goals

When the user cycles to a VCS ref with `<ctrl+p>` and launches:

1. The launch toast(s) name the **cycled-to** ref, never the stale initial one.
2. A resolvable cycled ref launches in **its** workspace and becomes the new `<ctrl+space>` replay selection + MRU head
   (this already works for resolvable refs except the first toast).
3. An **unresolvable** cycled ref must **not** silently launch under the previous ref's identity in the home/initial
   workspace. It should fail loudly (or be prevented), and stale refs should not linger in the cyclable MRU.

## Proposed approach

Treat the submitted prompt's leading VCS tag as the source of truth for the launch identity, and stop letting a stale
baked `ctx` stand in for a _different_ ref.

### 1. Fix the immediate toast (Defect A)

In `_finish_agent_launch` (`_launch_start.py`), derive the toast label from the submitted prompt's leading VCS tag
(cheap, lexical — reuse `extract_vcs_workflow_tag` / `extract_project_from_vcs_tag`, already imported in
`prompt_text_area`) and fall back to `ctx.display_name` only when the prompt has no VCS tag. This makes the "Launching
agent for …" toast reflect the cycled ref without doing heavy resolution on the UI thread.

### 2. Don't reuse a different ref's identity when resolution fails (Defect B)

In `_run_agent_launch_body` (`_launch_body.py`), after the home-mode resolution + the `extract_known_project_vcs_ref`
detection, detect the case where the submitted prompt contains a **recognized** VCS workflow tag
(`extract_vcs_workflow_tag` returns non-`None`) but **no** `vcs_ref`/known-project ref was resolved. In that case:

- **Preferred:** abort the launch with a clear error toast (e.g. `Cannot resolve #gh:<ref>; not launching`), write a
  cancelled history entry (mirroring the existing `validate_launch_name_requests` error path at
  `_launch_body.py:285-298`), clear `_prompt_context`, and return — instead of falling through to a home-mode launch
  under the baked identity.
- At minimum, if we ever do continue, re-derive `ctx.display_name` / `ctx.history_sort_key` from the tag's literal ref
  so the toast/history never show the unrelated baked project, and do not treat it as the baked project's workspace.

This keeps the genuine "plain prompt, no VCS tag → home mode" behavior intact (that path has no VCS tag, so it is
unaffected).

### 3. Keep the cyclable MRU resolvable (Defect C)

Extend the MRU prune/validation so a prefix whose ref no longer resolves is dropped from the **cyclable** set (and
ideally pruned on write). Approach:

- Add a resolvability check to `load_launchable_vcs_xprompt_mru` / `_is_stale_known_project_prefix` (or a sibling
  helper) that also rejects refs which fail to resolve via the workspace provider — not only known non-launchable
  _projects_. Guard it to stay cheap/offline (the existing `resolve_gh_ref` path is local: project shorthand +
  changespec lookup), and degrade gracefully (keep the entry) if resolution is ambiguous/raises unexpectedly, to avoid
  nuking the MRU on transient errors.
- This makes `<ctrl+p>` only ever cycle to refs that will actually launch, which also prevents Defect B from being
  reachable through the normal cycling UX.

### Boundary note (`rust_core_backend_boundary.md`)

The VCS _ref-resolution semantics_ live behind the workspace-provider plugin system and the Rust core (`sase_core` /
`sase_core_rs`); this fix does **not** change those semantics. It changes **presentation + launch-orchestration glue**
in this repo (which toast string to show, whether to abort vs. fall back, which MRU entries are offered for cycling). No
`../sase-core` wire/API change is anticipated; if a shared "is this ref currently resolvable?" predicate is needed and
one already exists in core, prefer calling through the binding rather than re-implementing.

## Files in scope

- `src/sase/ace/tui/actions/agent_workflow/_launch_start.py` — toast label from prompt tag (Defect A).
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` — unresolved-VCS-tag guard / no stale-identity fallback
  (Defect B).
- `src/sase/history/vcs_xprompt_mru.py` — prune refs that no longer resolve, not just non-launchable projects (Defect
  C).
- Possibly `src/sase/ace/tui/widgets/prompt_text_area.py` — only if we choose to also refresh a lightweight context hint
  at cycle time (optional; the launch-side fixes are sufficient).

## Testing

- **Unit (launch body), extend `tests/ace/tui/test_agent_launch_vcs.py`:**
  - Baked `display_name="sase"` ctx + resolvable `#git:foo` prompt → launches in `foo`, toast text contains `foo` (not
    `sase`), `_last_custom_agent_selection` → `foo`.
  - Baked `display_name="sase"` ctx + **unresolvable** `#git:<stale>` prompt → launch is aborted with an error
    notification, **no** home-mode launch, `_last_custom_agent_selection` unchanged is acceptable because nothing was
    launched, and a cancelled history entry is written.
- **Toast (Defect A):** assert `_finish_agent_launch` notifies using the prompt's VCS ref, not the baked
  `ctx.display_name`, when they differ.
- **MRU (Defect C), extend `tests/test_vcs_xprompt_mru.py`:** a prefix whose ref no longer resolves is excluded from
  `load_launchable_vcs_xprompt_mru`; an entry that does resolve is retained; transient resolution errors do not drop
  entries.
- **Widget cycling regression (`tests/ace/tui/widgets/`):** `<ctrl+p>` on a VCS-only prompt cycles the bar text to the
  next MRU entry and that exact text is what reaches submission (lock in the already-correct text plumbing so a future
  change can't regress it).
- Run `just check`.

## Out of scope / open questions

- Whether an unresolvable cycled ref should hard-error vs. best-effort re-label and continue — the plan recommends
  hard-error (safer, avoids launching in the wrong place); confirm during review.
- The `<ctrl+space>` vs. MRU stores remain distinct (`last_agent_selection` vs. `vcs_xprompt_mru`); this fix keeps them
  in sync for the success path but does not merge them.
- The `is_non_workspace_workflow` gate on `save_replayable_vcs_selection` means `#cd:` refs never update the
  `<ctrl+space>` replay selection by design; not changing that here unless review wants `<ctrl+space>` to also replay
  directory refs.
