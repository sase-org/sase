---
name: pylimit_split_agent_names
status: done
create_time: 2026-04-28 11:31:04
prompt: sdd/prompts/202604/pylimit_split_agent_names.md
---

# Name `pylimit_split` chop agents `pysplit.<basename>`

## Problem

`xprompts/pylimit_split.yml` launches one agent per oversized Python file via `build_wait_chained_multi_prompt()`, but
each agent inherits an auto-generated single-letter workflow name (`a`, `b`, ...). When several split agents are running
concurrently it's hard to tell which agent is splitting which file.

The user wants every per-file split agent named `pysplit.<basename>`, where `<basename>` is the file's basename with its
`.py` extension stripped (e.g. `src/sase/foobar.py` → `pysplit.foobar`). In the rare case where two distinct files share
a basename within one workflow run (e.g. `src/sase/foo/bar.py` and `tests/sase/foo/bar.py`), the names must still be
unique.

## Approach

Modify the `launch_split_agents` Python step in `xprompts/pylimit_split.yml` so that each per-file prompt is prefixed
with a `%name:pysplit.<basename>` directive (placed on its own line, matching the convention used in
`src/sase/bead/work.py:175-179`).

Basename is computed via `Path(path).stem`, which strips the directory and the final extension (works correctly for
`.py` files; `.pyi` would also be stripped, fine for our purposes).

### Dedup logic

Walk the unique-files list once, maintaining a `dict[str, int]` of basenames seen so far. For each path:

- If `Path(path).stem` is unseen, agent name = `pysplit.<stem>`.
- If already seen with count `N`, agent name = `pysplit.<stem>-<N+1>` (i.e. second occurrence becomes `pysplit.foo-2`,
  third `pysplit.foo-3`, ...). Use `-` as the suffix separator rather than `.` to avoid colliding with the dotted-prefix
  reservation that the auto-name system uses for `%r` repeat-fanout children (see `src/sase/agent/names/_auto.py` and
  the `repeat_fanout_name_collision` work).

The counter is updated only after the name is computed, so the first occurrence stays bare (`pysplit.foo`) and
subsequent ones are suffixed.

`unique_files` is already deduped by path (`dict.fromkeys(files)`), so a basename collision can only happen for
genuinely-distinct file paths.

## Implementation

Single file changes in `xprompts/pylimit_split.yml`. The Python step becomes:

```python
import subprocess
from pathlib import Path

from sase.agent.launcher import launch_agent_from_cwd
from sase.agent.multi_prompt import build_wait_chained_multi_prompt

limits = "{{ limits }}".split()

files: list[str] = []
for tree in ("src", "tests"):
    result = subprocess.run(
        ["tools/pylimit_files-260227", tree, *limits],
        capture_output=True,
        text=True,
        check=False,
    )
    files.extend(line.strip() for line in result.stdout.splitlines() if line.strip())

unique_files = list(dict.fromkeys(files))

if not unique_files:
    print("launched=0")
else:
    seen: dict[str, int] = {}
    per_file_prompts: list[str] = []
    for path in unique_files:
        stem = Path(path).stem
        count = seen.get(stem, 0)
        suffix = "" if count == 0 else f"-{count + 1}"
        seen[stem] = count + 1
        agent_name = f"pysplit.{stem}{suffix}"
        per_file_prompts.append(
            f"%name:{agent_name}\n#gh:sase #sase/pysplit:{path} %approve"
        )
    multi_prompt = build_wait_chained_multi_prompt(per_file_prompts)
    launch_agent_from_cwd(multi_prompt)
    print(f"launched={len(unique_files)}")
```

Notes on directive placement:

- `%name:` must be on its own line at the start of the prompt segment to match the pattern in
  `src/sase/bead/work.py:175` (and parsing via `extract_prompt_directives` in `src/sase/xprompt/directives.py`).
- `build_wait_chained_multi_prompt` prepends `%wait\n` to segments [1:] before joining with `\n---\n`; it does not parse
  or reorder directives, so `%name:`, `%wait`, and `%approve` coexist on the chained segments cleanly.

## Validation

- `just check` (fmt + lint + mypy + pyvision + tests).
- Manual: trigger `#sase/pylimit_split` with low limits (e.g. `100 80 60`) so multiple files are produced; confirm in
  the agents tab that the launched chain shows `pysplit.<basename>` names matching the files being split, and that any
  basename collision yields a `-2`/`-3` suffix.

## Out of scope

- Cross-workflow collision (two concurrent `pylimit_split` runs both splitting `foo.py`). The existing `%name` claim
  mechanism would surface that as a launch error; users can re-run if it happens. The user explicitly noted this is not
  expected.
- Renaming the `pysplit` xprompt itself or the chop directive. No changes outside the YAML.
