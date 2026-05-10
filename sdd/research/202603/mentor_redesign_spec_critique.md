## Prompt Review: Gaps & Design Decisions Needed

### 1. JSON Schema Design

The prompt says "figure out what JSON schema to use" but the two use cases (TUI overview vs. agent input for applying
changes) pull in different directions.

**Decisions needed:**

- **What is a "comment"?** Is every mentor output a proposed code change, or can some be informational observations that
  don't map to a file edit? The research docs distinguish `APPROVED / COMMENTED / CHANGES_REQUESTED` — your prompt seems
  to assume everything is a "change" that can be "applied."
- **Level of specificity for code changes**: Should the JSON contain file+line references with suggested replacement
  text (close to a diff), or high-level descriptions like "add error handling to `process_batch()`"? The former makes
  the apply-agent trivial but constrains the mentor; the latter gives mentors freedom but makes the apply-agent do
  heavier lifting.
- **What replaces `#propose`?** You say mentors stop creating proposals, but the current system has proposals as
  first-class objects with IDs, accept workflows, and rebase support. Is the new JSON output + apply-agent a complete
  replacement for the proposal system (for mentors specifically), or do mentors still need to interact with proposals?

### 2. "Comment" vs "Mentor" Granularity in the Popup

The popup description mixes two levels of navigation:

- `j`/`k` to navigate between **mentors**
- `ctrl+n`/`ctrl+p` to navigate between **comments** within a mentor

**Decisions needed:**

- **What is the side panel listing?** Profile names? Individual mentor names? Or mentor runs (since a profile can have
  multiple mentors)? Currently `mentor_profiles` has a list of `mentors` within each profile — but your new design
  eliminates per-mentor prompts. Does each profile now produce exactly one mentor run with potentially multiple
  comments?
- **What happens at the boundary?** If I'm on mentor A, comment 3 (the last one) and press `ctrl+n`, does it wrap around
  to comment 1, stay on comment 3, or jump to mentor B comment 1?
- **Can you un-accept?** Is `<space>` a toggle? Can I deselect a previously accepted comment?

### 3. Cross-Mentor Acceptance & the Apply Agent

**Decisions needed:**

- **Scope of a single apply run**: You say the user presses `<enter>` to launch "a single agent that makes all of those
  necessary file changes." Does this mean accepted comments from **all** mentors in the popup are batched into one agent
  call? Or only from the currently-focused mentor?
- **Conflict handling**: Two mentors might suggest contradictory changes to the same file/region. Is this the
  apply-agent's problem to resolve, or should the TUI warn about conflicts before launching?
- **Agent lifecycle**: Does the apply-agent run in the foreground (blocking the popup) or background? What happens to
  the popup after — does it close, refresh, or let the user accept more?
- **Iterability**: Can the user do multiple rounds (accept some → apply → accept more → apply again), or is it a
  one-shot workflow?

### 4. The `#make_mentor_changes` XPrompt

**Decisions needed:**

- **Input format**: How does the accepted-comments data get passed to this xprompt? As a JSON file path? Inline JSON?
  Via the `#json` workflow's input mechanism?
- **Workspace**: Does the apply-agent need a workspace checkout (like current mentor runs), or does it operate on the
  current CL's workspace?
- **What does "override via tag" mean operationally?** If a user sets the `make_mentor_changes` tag on their own
  xprompt, does it receive the same structured input? This implies a contract: the tag-based override must accept the
  same input schema. Is that documented/enforced?

### 5. `mentor_profiles` Config Redesign

This is the biggest open area. You say "use a rubric / configuration to control which instructions are rendered in the
`#mentor` prompt" but:

**Decisions needed:**

- **What replaces the `mentors` list?** Currently each profile has `mentors: [{mentor_name, prompt}]`. If we're removing
  per-mentor prompts, do we also remove the concept of multiple mentors per profile? Or does a single profile now map to
  exactly one `#mentor` run with config-driven instructions?
- **What is the rubric schema?** The research docs propose dimensions with severity policies. Do you want something like
  that, or simpler (e.g., just a list of focus areas as strings like `["security", "error handling", "naming"]`)?
- **How does config become prompt content?** The `#mentor` xprompt needs to render differently based on profile config.
  Is the rubric templated into the prompt via Jinja (e.g., `{{ rubric }}`), or does the xprompt workflow have a step
  that reads the config and builds instructions?
- **Model selection**: Currently not part of `mentor_profiles`. The research docs suggest `model_tier` or `tier`. Should
  the new config support per-profile model selection?
- **What about the retired Mercurial plugin `mentor.md`?** It currently defines the entire mentor persona/workflow. Under the new
  system, the built-in `#mentor` xprompt (tagged `mentor`) replaces it. Does the retired Mercurial plugin plugin need any changes, or
  does it just stop providing a `mentor.md`?

### 6. The `mentor` XPrompt Tag

**Decisions needed:**

- **Enforcement of "one and only one"**: What happens if a user accidentally tags two xprompts as `mentor`? Error at
  load time? Silently use highest priority? The existing tag system (`get_by_tag`) returns the highest-priority match —
  is that sufficient, or do you want a hard error?
- **Scope of override**: Does the user's tagged xprompt completely replace the built-in `#mentor`, or does it
  extend/wrap it? If complete replacement, the user takes on responsibility for the JSON output schema, rubric
  rendering, etc.

### 7. Storage & Persistence

The prompt doesn't address:

- **Where does mentor JSON output live?** The research suggests `~/.sase/mentors/<cl>-...review.json`. Is that the plan,
  or should it live in the changespec directory, or somewhere else?
- **Persistence across TUI sessions**: If I accept 2 comments, close the TUI, and reopen, are those acceptances
  preserved? Or is acceptance ephemeral (popup-session-only)?
- **How does this interact with stale mentor killing?** When a new commit is pushed, stale mentors are killed. Are stale
  JSON outputs cleaned up too, or preserved for reference?

### 8. Status Model

The prompt doesn't mention changes to the mentor status lifecycle, but the shift from proposals to JSON output implies
changes:

- Currently `FAILED` + entry_ref = successful proposal. What's the new terminal status for a mentor that produces JSON
  output? `SUCCEEDED`? `COMMENTED`?
- Does the `MENTORS` field in the changespec still exist in its current format, or does it change?

### 9. Missing Details

- **Empty state**: What does the `,m` popup show when no mentors have run yet, or all are still `RUNNING`?
- **Error display**: What if a mentor produces invalid JSON (fails `#json` validation)?
- **Keybinding for dismissing the popup**: `<esc>`? `q`? Both?
- **Relationship to existing `,M` (kill mentors)**: Should killing be accessible from within the review popup too?

---

### Suggested Approach

If I were implementing this, the single biggest blocker is the **config schema** — everything else flows from what
`mentor_profiles` looks like and what data structure the `#mentor` xprompt produces. I'd want you to decide:

1. Concrete example of a new-format `mentor_profiles` entry (even rough/pseudocode)
2. Whether comments are purely informational or always code-change-oriented
3. Whether acceptance state is ephemeral (popup only) or persisted

Everything else I could design with reasonable defaults and iterate.
