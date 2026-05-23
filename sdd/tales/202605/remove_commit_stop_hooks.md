---
create_time: 2026-05-22 21:10:16
status: done
prompt: sdd/prompts/202605/remove_commit_stop_hooks.md
---
# Remove Obsolete Commit Stop Hook Scripts

## Context

The repo still contains compatibility-only native stop-hook scripts:

- `src/sase/scripts/sase_commit_stop_hook.py`
- `src/sase/scripts/sase_commit_stop_hook`
- `tools/sase_sibling_commit_stop_hook`

SASE-launched agents now use the provider-neutral commit finalizer in `src/sase/llm_provider/commit_finalizer.py`, which
reuses the shared helpers in `src/sase/commit_instructions.py`. The stop-hook scripts are no longer supposed to be
configured in active agent settings.

I checked the chezmoi source at `/home/bryan/.local/share/chezmoi/home`. The active agent configuration files there do
not reference `sase_commit_stop_hook` or `sase_sibling_commit_stop_hook`:

- `dot_claude/settings.json`
- `dot_gemini/settings.json.tmpl`
- `dot_qwen/settings.json`
- `dot_codex/hooks.json`
- `dot_codex/config.toml`

`dot_codex/hooks.json` still references a personal `zorg_sibling_commit_stop_hook` command, but that is not one of the
SASE hook scripts being removed.

## Plan

1. Remove active script entry points for the obsolete hooks.
   - Delete `src/sase/scripts/sase_commit_stop_hook.py`.
   - Delete `src/sase/scripts/sase_commit_stop_hook`.
   - Delete `tools/sase_sibling_commit_stop_hook`.
   - Remove the `sase_commit_stop_hook` console-script export from `pyproject.toml`.
   - Remove the corresponding wrapper function from `src/sase/scripts/__init__.py`.

2. Update active tests so they no longer import or execute deleted scripts.
   - Remove the native stop-hook runtime tests that only validate the deleted compatibility script.
   - Preserve useful coverage for the shared commit instruction behavior by moving those assertions to direct
     `sase.commit_instructions` tests where appropriate.
   - Remove sibling stop-hook tests tied exclusively to `tools/sase_sibling_commit_stop_hook`.
   - Keep the static config guard that prevents repo-local agent configs from reintroducing `sase_commit_stop_hook` or
     `sase_sibling_commit_stop_hook`.

3. Update active documentation and local tool guidance.
   - Remove or rewrite docs that say the legacy stop-hook scripts still exist for compatibility.
   - Keep `SASE_DISABLE_COMMIT_STOP_HOOK` documentation where it still applies to the commit finalizer.
   - Remove obsolete `tools/AGENTS.md` sections describing the deleted scripts.

4. Re-run static searches.
   - Search the SASE repo for active code/docs references to deleted script paths, imports, console scripts, and hook
     command names.
   - Search the chezmoi agent configuration files again for `sase_commit_stop_hook` and `sase_sibling_commit_stop_hook`.
   - Treat historical SDD prompt/tale/research references as archival unless they are active tests, docs, or executable
     configuration.

5. Verify.
   - Run focused tests around commit instructions, commit finalizer behavior, and agent hook config guards.
   - Because this changes files in the SASE repo, run `just install` and then `just check` unless an earlier command
     exposes a blocking environment issue.

## Expected Outcome

No active agent configuration in chezmoi invokes the removed stop-hook scripts, and this repo no longer ships those
scripts or their console entry point. Commit enforcement remains covered by the provider-neutral commit finalizer and
shared commit instruction helpers.
