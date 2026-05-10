---
plan: sdd/epics/202603/mentor_redesign.md
---
Can you help me plan a major re-design of sase mentors?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.

### New Mentor Instructions / Output

- I want mentors to stop creating new proposals. Instead, they will produce structured JSON output according to a schema
  we provide them in the `#mentor` xprompt via the embedded `#json` workflow.
- I want you to figure out what JSON schema to use exactly. Keep in mind that this output will be used for two purposes:
  1. To provide the user with a nice overview (see the "New Mentor Review Popup" section below) of the changes that the
     agent is proposing.
  2. To launch an agent to approve one or more of the changes proposed by one or more mentors. Make sure we can support
     partial approvals (for example, the user should be able to apply 2 of the 3 changes a mentor proposes).

### New Mentor Review Popup in `sase ace` TUI

- We should add a new `,m` (review mentors) keymap to the "CLs" tab of the `sase ace` TUI that opens up a new Mentor
  Review popup (should take up most of the screen) that has a side panel with a list of mentors for the latest commit
  only and a main panel that shows one mentor comment at a time.
- The user should be able to toggle through the mentor comments for a single mentor using the `n` and `p` keymaps and
  should be able to navigate through the different mentors using the `j` / `k` keys.
- The user should be able to accept each comment using the `<space>` keymap. Make sure we show which / how many
  proposals have been accepted somewhere in this popup. I want you to lead the design on this one. Just make sure it
  looks beautiful!
- If the user has accepted one or more comments using the `<space>` key, they should then be able to use the `<enter>`
  keymap to run a single agent that makes all of those necessary file changes. We will create a new
  `#make_mentor_changes` xprompt that is used for this agent. This xprompt should be given a new "make_mentor_changes"
  xprompt tag. Users should be able to set this tag on one (and only one) of their xprompts in order to override the
  `#make_mentor_changes` xprompt (i.e. use the user xprompt to apply mentor changes instead).

### `mentor_profiles` Config Field Changes

- We should no longer provide mentor prompts directly (see the `#mentor/*` xprompts in the ../sase-googe repo, for
  example). Instead, we should use a rubric / configuration to control which instructions are rendered in the `#mentor`
  prompt. I want you to lead the design on this one (the configuration schema). See the sdd/research/202603/mentor_redesign.md and
  sdd/research/mentor_redesign_v2.md (a critique of the previous file's research) for inspiration, but YOU should make the
  final call (i.e. feel free to ignore the research in those files if you have a better approach).
- We will start using the `#mentor` xprompt by default to run all mentors (we already do this, but it is by embedding
  the `#mentor` prompt in `mentor_profiles` mentor prompts, which we won't have anymore). We will accomplish this by
  adding support for a new "mentor" xprompt tag. Users should be able to set this tag on one (and only one) of their
  xprompts in order to override the `#mentor` xprompt (i.e. use the user xprompt to run mentors instead).

### Design Decisions

I prompted a previous agent to critique the above prompt to flesh out design decisions that I need to make. You can find
that agent's reply in the sdd/research/202603/mentor_redesign_spec_critique.md file. I have listed my replies, which match the
numbered sections in that file, below:

1. We should use the new "COMMENTED" MENTORS status when a mentor agent makes one or more comments. Mentor comments
   should always be actionable. The JSON schema should include a file+line reference and a high-level description of the
   changes that it thinks should be made. What replaces `#propose`?: We should use a new "commit" xprompt tag (only one
   xprompt should be allowed to have this tag) for this. When an xprompt exists that has this tag (which might not
   always be the case), we should append ` #<xprompt_name>` to the `#make_mentor_changes` agent's prompt.
2. The side panel should list all running, queued, or completed mentors from the latest commit (see the COMMITS
   ChangeSpec field) ONLY. What happens at the boundary?: Jump to mentor B comment 1. Note that we chose to use the `n`
   and `p` keymaps for this. Can you un-accept?: Yes. The `<space>` keymap should toggle acceptance.
3. All mentors are batched into a single `#make_mentor_changes` agent call. This agent should act just as if we launched
   it manually (ex: It should show on the "Agents" tab of the `sase ace` TUI). The user SHOULD be able to do multiple
   rounds of mentor acceptance for a single commit.
4. The `#mentor` agents should NOT need to claim workspaces anymore, but the `#make_mentor_changes` agent does need to
   claim one. If the user overrides `#mentor` or `#make_mentor_changes`, they will need to make sure it accepts the same
   input and produces the same output.
5. Each mentor in `mentor_profiles` should continue to run as a distinct mentor agent. The `mentors` schema should
   require each mentor to have a `role` (ex: "code quality expert") that gets passed to the `#mentor` xprompt. Each
   mentor should also have a list of `(focus_name, review_focus_desc)` pairs, where `focus_name` is a distinct name for
   the focus area (should be included in the `#json` output schema and displayed on the Mentors Review popup) and
   `review_focus_desc` is a description of the focus area. These pairs are also passed to the `#mentor` xprompt, which
   will format them properly in a pre-step (we'll need to use an xprompt YAML workflow for this) so they can be injected
   into the `#mentor` agent's prompt. Remove the retired Mercurial plugin plugin repo's mentor.md file and make sure to update the
   default_config.yml file (which defines `mentor_profiles`) in that repo.
6. The "one and only one" constraint should be enforced (throw an error) if the xprompts have the same priority
   (otherwise, we just use the higher priority xprompt). xprompt tag overrides are a complete replacement for the lower
   priroity xprompts with the same tag.
7. Acceptance / unacceptance (we should be able to unaccept with the `<space>` keymap) should be persisted to disk. JSON
   outputs of stale mentors should be perserved.
8. COMMENTED.
9. If a mentor fails or produces invalid output, we should mark that MENTORS line as "FAILED" (make sure to include the
   appropriate failure log file on that line). We SHOULD be able to kill running mentors from the Mentor Review panel.
