---
create_time: 2026-05-28 09:15:24
status: wip
prompt: sdd/prompts/202605/chop_indexed_agent_names.md
---
# Plan: Move Chezmoi-Defined Chops to Indexed Agent Names

## Goal

Start migrating all SASE chops defined in the chezmoi source repo to the new indexed agent-name template syntax:

```text
%n:<base>-@
```

instead of generating names with embedded timestamps, run IDs, SHAs, or other one-off entropy such as
`<base>-<timestamp>`.

The desired result is that recurring chop-launched agents form stable, readable agent-name families such as
`sase_refresh_docs-1`, `sase_refresh_docs-2`, and `gha_fix_sase_org_sase-1`, while still preserving existing ChangeSpec
and duplicate-launch safeguards.

## Context Found

The chezmoi source path is:

```text
/home/bryan/.local/share/chezmoi/home
```

The configured SASE chop files are:

- `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_work.yml`
- `/home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_sase_fix_just`
- `/home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix`

The SASE implementation already supports indexed names:

- `%n:foo-@` / `%name(foo-@)` parse as indexed templates.
- Concrete names allocate as `foo-1`, `foo-2`, etc.
- Indexed bases cannot contain `-` or `@`, so bases must be sanitized to underscores/dots before appending `-@`.
- `validate_launch_name_requests()` special-cases indexed templates, so the terminal `-@` form is allowed even though
  normal user-specified hyphenated names are rejected.

Current chezmoi chop inventory:

- Direct `agent:` chops in `sase_athena.yml`:
  - `sase_pylimit_split`
  - `sase_recent_bug_audit`
  - `sase_recent_improvement_audit`
  - `sase_refresh_docs`
  - `sase_core_refresh_docs`
  - `sase_github_refresh_docs`
  - `sase_nvim_refresh_docs`
  - `sase_telegram_refresh_docs`
- Script-backed chops in `sase_athena.yml`:
  - `sase_fix_just`
  - `gh_actions_fix`
- Integration script chops without agent prompts:
  - `tg_inbound`, `tg_outbound`, `gc_inbound`, `gc_outbound`

The clearest existing timestamp/run-id style agent name is in `executable_sase_chop_gh_actions_fix`, where the prompt
uses:

```text
%n:gha-fix-{repo_slug}-{run_id}-a{attempt}
```

That should become an indexed template with a stable sanitized base, while the `#pr(...)` ChangeSpec name can keep the
run ID and attempt because it is part of duplicate-work isolation rather than agent-family naming.

## Implementation Plan

### 1. Define the naming convention

Use the chop name, or a narrowly scoped chop sub-key, as the indexed base.

Rules:

- Replace hyphens and other non-agent-base characters with underscores before adding `-@`.
- Do not include timestamps, commit SHAs, GitHub run IDs, attempts, or random IDs in the agent name base.
- Keep identifiers that affect work isolation in ChangeSpec names, marker files, or script state files.
- Put `%n:<base>-@` at the start of each prompt so it is visible and parsed before the rest of the launch prompt.

Initial mapping:

```text
sase_pylimit_split              -> %n:sase_pylimit_split-@
sase_recent_bug_audit          -> %n:sase_recent_bug_audit-@
sase_recent_improvement_audit  -> %n:sase_recent_improvement_audit-@
sase_refresh_docs              -> %n:sase_refresh_docs-@
sase_core_refresh_docs         -> %n:sase_core_refresh_docs-@
sase_github_refresh_docs       -> %n:sase_github_refresh_docs-@
sase_nvim_refresh_docs         -> %n:sase_nvim_refresh_docs-@
sase_telegram_refresh_docs     -> %n:sase_telegram_refresh_docs-@
sase_fix_just                  -> %n:sase_fix_just-@
gh_actions_fix for <repo>       -> %n:gha_fix_<repo_slug_with_underscores>-@
```

### 2. Update direct `agent:` chop prompts in chezmoi config

Edit `dot_config/sase/sase_athena.yml` so each direct agent chop includes the corresponding `%n:<base>-@` directive.

For single-line prompts:

```yaml
agent: "%n:sase_pylimit_split-@ #gh:sase %g:chop #!sase/pylimit_split %approve"
```

For wrapped prompts, keep YAML readability and make the first token the `%n:` directive.

Do not add `%n:` to script-only chops or inbound/outbound integration chops that do not launch agents directly.

### 3. Update script-backed chop launch prompts

In `bin/executable_sase_chop_sase_fix_just`:

- Change `FIX_JUST_PROMPT` to include `%n:sase_fix_just-@`.
- Keep the ChangeSpec guard prefix unchanged.
- Keep `#gh:sase %g:chop #!sase/fix_just` unchanged.

In `bin/executable_sase_chop_gh_actions_fix`:

- Replace the current concrete `agent_name = f"gha-fix-{repo_slug(repo)}-{run_id}-a{attempt}"` with an indexed template
  derived from the repo only.
- Suggested helper:

```python
def agent_name_template(repo: str) -> str:
    return f"gha_fix_{repo_slug(repo).replace('-', '_')}-@"
```

- Emit `%n:{agent_name_template(repo)}` in the prompt.
- Keep `pr_name(repo, run_id, attempt)` unchanged so each failed run attempt still gets an isolated ChangeSpec.
- Keep `gh_actions_fix_seen.json` dedupe unchanged.

### 4. Treat workflow-internal names as a second slice

Some agents launched by these chops are created inside SASE xprompt workflows rather than directly in the chezmoi chop
definition. Examples in the SASE repo include:

- `xprompts/refresh_docs.yml`
- `xprompts/audit_recent_bugs.yml`
- `xprompts/audit_recent_improvements.yml`
- `xprompts/pylimit_split.yml`
- `xprompts/fix_just.yml`

Do not mix that broader migration into the first chezmoi-only edit unless the explicit acceptance criterion is "every
descendant agent spawned by a chop must use indexed naming." If that is required, do it as a follow-up with focused SASE
tests, because direct workflow `agent:` steps and multi-agent chained prompts have different naming paths.

For that follow-up:

- Prefer terminal indexed templates per visible child agent, such as `%n:refresh_docs_update-@` and
  `%w:refresh_docs_update-@`, rather than manually allocating `foo-1` and appending `.update`, because concrete
  hyphenated names emitted as ordinary `%name:` values are rejected by launch validation.
- For generated per-file or per-repo names, sanitize dynamic bases before appending `-@`.
- Add tests around the actual xprompt/workflow expansion path, not only helper functions.

### 5. Verification

After implementation:

1. Run a targeted syntax/config check against the chezmoi YAML and scripts:
   - `python -m py_compile /home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_sase_fix_just`
   - `python -m py_compile /home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix`
   - Use `sase axe lumberjack list` or the closest available config-loading command to confirm config still parses.
2. Exercise SASE parser behavior with existing tests or a small focused command:
   - `%n:sase_refresh_docs-@` should validate.
   - `%n:gha_fix_sase_org_sase-@` should validate.
   - Any accidental `%n:gha-fix-...-@` should fail, confirming we did not leave hyphenated bases.
3. If SASE repo files are edited later, run the relevant focused tests first, then `just check` because the SASE repo
   AGENTS instructions require it after code changes.

## Non-Goals

- Do not rewrite historical agent artifacts or existing name registry entries.
- Do not change ChangeSpec naming, marker naming, GitHub Actions dedupe state, or chop run-history IDs unless a concrete
  collision appears during testing.
- Do not modify memory files.
