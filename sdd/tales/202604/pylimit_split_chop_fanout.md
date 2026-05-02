---
create_time: 2026-04-24 18:29:09
status: wip
prompt: sdd/prompts/202604/pylimit_split_chop_fanout.md
---
# Fix `sase_pylimit_split` chop fan-out

## Problem

The `sase_pylimit_split` chop is intended to start one split agent for every Python file that currently violates the
line-limit policy. In practice, each chop tick launches one background workflow runner for
`#gh:sase #sase/pylimit_split %approve`. The `pylimit_split` workflow then discovers files and iterates over them with a
single `split_files` agent step:

```yaml
for: { file_path: "{{ find_files.files }}" }
agent: |
  #sase/pysplit:{{ file_path }}
```

That loop invokes the prompt step once per file, but the invocations happen synchronously inside the same workflow
process, with the same workflow step name and artifact directory. Recent run artifacts show this directly:

- `~/.sase/axe/lumberjacks/run_every/logs/output.log` has one `Launched agent chop 'sase_pylimit_split'` PID per tick.
- Runs such as `~/.sase/projects/sase/artifacts/ace-run/20260424151546/` contain multiple
  `workflow-pylimit_split-split_files` prompt/response sections in the same `sase.md` file.
- The run does not create one independent top-level background agent entry per file.

So the root cause is not the old `src`/`tests` workflow short-circuit; the installed workflow is already consolidated.
The current mismatch is that a workflow `for` loop is being used where the chop needs launch-time agent fan-out.

## Goal

Make the chop launch one independent background agent per file that needs splitting, while keeping the existing
`#sase/pylimit_split` workflow available for manual use.

## Design

Move the chop-specific behavior out of the `agent:` shortcut and into a dedicated external chop script in the chezmoi
repo:

1. Add a `~/.config/sase/chops` directory managed by chezmoi.
2. Add an executable `sase_pylimit_split` chop script there.
3. Configure `axe.chop_script_dirs` to include `/home/bryan/.config/sase/chops`.
4. Change the `sase_pylimit_split` chop from an `agent:` chop into a script chop.

The script should:

1. Resolve the `sase` workspace directory.
2. Run the same file discovery used by the gate:

   ```bash
   { tools/pylimit_files-260227 src 1000 850 700; tools/pylimit_files-260227 tests 1000 850 700; }
   ```

3. Deduplicate the resulting file list.
4. If no files are found, exit successfully without launching anything.
5. Build a multi-prompt with one segment per file, where each segment runs:

   ```text
   #gh:sase #sase/pysplit:<file> %approve
   ```

6. Add `%wait` to later segments so all file-specific agents are created as distinct entries without exhausting the
   finite axe workspace pool.
7. Launch the generated multi-prompt with `SASE_AGENT_AUTO_DISMISS=1 sase run -d ...`.

This uses SASE's existing multi-prompt launch path, which creates separate background agent subprocesses, agent names,
workspace claims, and artifact directories for each prompt segment.

## Implementation Steps

1. Update `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.
   - Add `/home/bryan/.config/sase/chops` to `axe.chop_script_dirs`.
   - Remove `agent:` and `gate:` from the `sase_pylimit_split` chop.
   - Keep `run_every: 60m`.

2. Add `~/.local/share/chezmoi/home/dot_config/sase/chops/executable_sase_pylimit_split`.
   - Use Bash for simple integration with existing repo tools.
   - Keep output concise: print how many file-specific agents were launched and list the files.
   - Fail clearly if the `sase` workspace cannot be found.

3. Validate locally.
   - Run the chop script directly in dry conditions if possible.
   - Run `just check` in the chezmoi repo.
   - Run `chezmoi apply` after the chezmoi changes are validated.

4. Optional SASE repo validation.
   - No SASE repo code change is expected. If no files here are modified, `just check` in the SASE repo is not required
     by the memory rules.

## Risks

- If more files need splitting than available workspaces, a fully parallel launch could fail. The `%wait` chain avoids
  that by creating one visible agent per file while letting only the first begin immediately.
- Since this becomes a script chop rather than an `agent:` chop, the lumberjack's per-agent PID tracking no longer sees
  each child. `run_every: 60m` still throttles launch cycles, and the `%wait` chain prevents workspace exhaustion within
  a single cycle.
