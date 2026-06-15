---
create_time: 2026-06-15 16:41:12
status: wip
prompt: sdd/prompts/202606/refresh_skill_use_directives.md
---
# Plan: Refresh Generated Skill Use Directives

## Current Findings

The previous SASE source change updated the workspace implementation, but the deployed/generated skill artifacts have
not been refreshed end to end.

- The workspace binary `./.venv/bin/sase` exposes `sase skills use` and rejects `sase skills log`, so the source-side
  CLI rename is present in this checkout.
- The active PATH binary `/home/bryan/.local/bin/sase` is still old: it rejects `sase skills use` and still accepts
  `sase skills log`.
- The source generator in this checkout emits `sase skills use <name> --reason ...`, and bundled skill source templates
  under `src/sase/xprompts/skills/` do not hand-code either command; the directive is injected by `sase skills init`.
- The current generated chezmoi skill files still contain 68 `sase skills log` directives and zero `sase skills use`
  directives.
- The live agent skill directories also still contain 68 `sase skills log` directives and zero `sase skills use`
  directives.
- With the workspace binary, `sase skills list` reports `12 current, 68 stale, 0 missing`; the 12 current targets are
  the skills where no audit directive is injected, while the 68 stale targets are the generated files that need the
  renamed injected directive.

## Implementation Plan

1. Confirm the SASE source checkout is clean enough to proceed, and keep historical `sdd/` records out of scope unless
   they are active generated-skill sources or active user docs.

2. Update the installed SASE CLI before changing generated skills.
   - Run the repo's install flow from this checkout, expected to be `just install`.
   - Verify that plain `sase skills use --help` works on PATH.
   - Verify that plain `sase skills log --help` fails with valid choices `init`, `list`, and `use`.
   - This matters because generated skills call `sase`, not `./.venv/bin/sase`.

3. Verify the initializer contract before writing generated outputs.
   - Run `sase skills init --help` and confirm `sase skills init` is the primary command and `sase init skills` remains
     the compatibility alias.
   - Run `sase skills init --dry-run` and confirm it sees the expected generated targets and stale count under the
     updated initializer.

4. Regenerate and deploy generated skills through the supported pipeline, without hand-editing generated `SKILL.md`
   files.
   - Run `sase skills init --force` using the updated PATH CLI.
   - Let the existing `use_chezmoi` flow handle the chezmoi source update, commit/push if configured, and
     `chezmoi apply` so live runtime directories are refreshed too.
   - If the automatic chezmoi sequence is blocked by remote changes or a dirty chezmoi repo, stop and report the exact
     blocker rather than manually patching generated files.

5. Verify the generated and live skill files.
   - Search `/home/bryan/.local/share/chezmoi/home` for `sase skills log`; expected: no matches.
   - Search `/home/bryan/.local/share/chezmoi/home` for `sase skills use`; expected: 68 matching generated skill files.
   - Search the live skill directories (`~/.codex/skills`, `~/.claude/skills`, `~/.gemini/skills`,
     `~/.gemini/jetski/skills`, `~/.config/opencode/skills`, `~/.qwen/skills`) for `sase skills log`; expected: no
     matches.
   - Search the same live directories for `sase skills use`; expected: 68 matching generated skill files.

6. Verify command-level health after regeneration.
   - Run `sase skills list` and confirm `80 current, 0 stale, 0 missing`.
   - Run `sase skills init --dry-run` and confirm no generated-skill drift is reported.
   - Run the relevant repo check that previously failed on generated-skill drift, preferably `just check` if time
     allows; otherwise run the focused init/skills checks and report the narrower coverage.

7. Report the result clearly.
   - State whether the answer changed from "not yet" to "yes".
   - Include the exact counts for stale/current targets and old/new command-string matches.
   - Mention any chezmoi commit/push/apply result from `sase skills init --force`.
