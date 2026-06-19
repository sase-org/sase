---
create_time: 2026-06-19 10:43:56
status: done
prompt: sdd/prompts/202606/remove_plan_search_skill.md
---
# Remove unintended plan-search skill

## Goal

Remove the unintended generated SASE xprompt skill named `sase_plan_search` from the current SASE source tree, generated
chezmoi skill outputs, and live provider skill directories, without removing the `sase plan search` CLI feature itself.

## Current Findings

- The authoritative generated-skill source is `src/sase/xprompts/skills/sase_plan_search.md`.
- `sase skill list` currently reports `/sase_plan_search` as a current generated skill for the provider target set.
- The generated copies exist in the chezmoi source tree at:
  - `/home/bryan/.local/share/chezmoi/home/dot_codex/skills/sase_plan_search`
  - `/home/bryan/.local/share/chezmoi/home/dot_claude/skills/sase_plan_search`
  - `/home/bryan/.local/share/chezmoi/home/dot_gemini/skills/sase_plan_search`
  - `/home/bryan/.local/share/chezmoi/home/dot_gemini/jetski/skills/sase_plan_search`
  - `/home/bryan/.local/share/chezmoi/home/dot_qwen/skills/sase_plan_search`
  - `/home/bryan/.local/share/chezmoi/home/dot_config/opencode/skills/sase_plan_search`
- The live installed copies exist at:
  - `/home/bryan/.codex/skills/sase_plan_search`
  - `/home/bryan/.claude/skills/sase_plan_search`
  - `/home/bryan/.gemini/skills/sase_plan_search`
  - `/home/bryan/.gemini/jetski/skills/sase_plan_search`
  - `/home/bryan/.qwen/skills/sase_plan_search`
  - `/home/bryan/.config/opencode/skills/sase_plan_search`
- The repo has support references that exist only because the skill was added:
  - `.gitignore` has a scoped negation for `src/sase/xprompts/skills/sase_plan_*.md`.
  - `tests/main/test_init_skills_sources.py` includes `sase_plan_search` in shipped skill-source coverage.
  - `tests/test_plan_search_cli.py` has a CLI-to-skill example parity test reading the skill source.
- The broader `sase plan search` command, implementation, docs, and tests are separate from the unwanted slash skill and
  should remain.

## Boundary

I will remove current/actionable references and generated files. I will not rewrite historical audit records such as
Claude/Codex session transcripts or SASE bead event streams unless explicitly asked, because those are immutable history
and this new plan artifact necessarily mentions the removed skill while documenting the work.

## Implementation Plan

1. Remove the authoritative generated-skill source file:
   - Delete `src/sase/xprompts/skills/sase_plan_search.md`.

2. Remove repo references that only supported that skill:
   - Delete the `sase_plan_*` exception block from `.gitignore`.
   - Remove the `sase_plan_search` parameter case from `tests/main/test_init_skills_sources.py`.
   - Remove the skill-example extraction helper and parity test from `tests/test_plan_search_cli.py`.
   - Remove now-unused imports such as `shlex` if they become dead after the test removal.

3. Remove generated skill directories from chezmoi source:
   - Delete each `sase_plan_search` directory under `dot_codex`, `dot_claude`, `dot_gemini`, `dot_gemini/jetski`,
     `dot_qwen`, and `dot_config/opencode`.

4. Remove live installed skill directories:
   - Delete each live `sase_plan_search` directory under `.codex`, `.claude`, `.gemini`, `.gemini/jetski`, `.qwen`, and
     `.config/opencode`.

5. Verify the generator and filesystem state:
   - Run `sase skill list` and confirm `/sase_plan_search` is gone.
   - Run exact path scans across the known provider skill roots and chezmoi source roots to confirm no
     `sase_plan_search` directories remain.
   - Run exact content scans over the active repo files and known skill roots to confirm current references are gone,
     while reporting any remaining historical matches separately.

6. Run focused tests:
   - `pytest tests/main/test_init_skills_sources.py tests/test_plan_search_cli.py`
   - If the focused run exposes broader coupling, expand to the relevant plan-search or skill-init test files.

## Expected Outcome

The unwanted `/sase_plan_search` skill will no longer be generated, listed, or installed in any current provider
environment on this machine. The `sase plan search` CLI remains intact.
