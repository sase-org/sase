---
create_time: 2026-05-30 13:43:03
status: done
prompt: sdd/prompts/202605/move_pick_plan_xprompt.md
---
# Move `pick_plan` xprompt into chezmoi

## Context

The current xprompt lives at `xprompts/pick_plan.md` in the SASE repo. It is a simple markdown xprompt with one required
`word` input named `name`, and it expands to a prompt that compares `{{ name }}.cdx` and `{{ name }}.cld` plan agents
using `#m_swarm`.

Chezmoi's source directory on this machine is `/home/bryan/.local/share/chezmoi/home`.

SASE's global markdown xprompt loader scans:

- `~/.xprompts/*.md`
- `~/xprompts/*.md`

It does not scan a flat `~/.config/sase/xprompts/*.md` directory for global xprompts; that path is only used for
project-specific xprompts under `~/.config/sase/xprompts/<project>/`.

Therefore the correct chezmoi source path for a globally available xprompt is:

- `/home/bryan/.local/share/chezmoi/home/dot_xprompts/pick_plan.md`

which manages:

- `/home/bryan/.xprompts/pick_plan.md`

There are unrelated local target diffs reported by `chezmoi diff` for `.chezmoiscripts/install_nvim` and
`.hammerspoon/init.lua`, while the chezmoi source git worktree is clean. Any apply step should be targeted to the new
xprompt path rather than applying the entire chezmoi state.

## Plan

1. Add `dot_xprompts/pick_plan.md` to the chezmoi source tree with the exact current content from
   `xprompts/pick_plan.md`, preserving YAML front matter, input metadata, description, and body text.

2. Apply only the new target file with chezmoi so the xprompt is available on this machine immediately:
   `chezmoi apply ~/.xprompts/pick_plan.md`.

3. Treat the chezmoi copy as the global source of truth. Remove `xprompts/pick_plan.md` from the SASE repo so the
   xprompt is not maintained in two places.

4. Update live SASE documentation that lists the local project xprompt catalog. In particular, remove or revise the
   `#sase/pick_plan` row in `docs/development.md` because the migrated prompt will now be invoked globally as
   `#pick_plan(...)`, not as a SASE project-local `#sase/pick_plan`.

5. Leave historical SDD/research references alone unless they are current user-facing catalog documentation. Those files
   record prior planning and should not be rewritten just because the xprompt has moved.

6. Verify the migration:
   - Confirm the chezmoi source git status shows only `dot_xprompts/pick_plan.md` added.
   - Confirm the SASE repo git status shows the xprompt removal and expected docs update.
   - Run a direct expansion such as `sase xprompt expand '#pick_plan(example)'` and check that it renders `example.cdx`,
     `example.cld`, and `#m_swarm`.
   - Run from outside the SASE repo as well, so the verification proves the prompt is coming from the global home
     xprompt path rather than the old repo-local file.
   - Because this changes the SASE repo, run `just install` if needed and then `just check` before finishing.

## Risks and mitigations

- Putting the file under `dot_config/sase/xprompts` would look natural but would not be loaded as a global xprompt. Use
  `dot_xprompts` instead.
- Running a full `chezmoi apply` could overwrite unrelated target-only changes. Use a targeted apply for
  `~/.xprompts/pick_plan.md`.
- Removing the SASE repo copy changes the trigger from `#sase/pick_plan` to global `#pick_plan`. Update active docs and
  call this out in the final summary.
