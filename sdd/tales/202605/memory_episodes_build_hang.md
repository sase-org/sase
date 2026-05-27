---
create_time: 2026-05-26 21:38:56
status: done
prompt: sdd/prompts/202605/memory_episodes_build_hang.md
---
# Plan: Fix `sase memory episodes build` project-scan fan-out

## Problem

`sase memory episodes build -s 2026-05-19 -u 2026-05-20 -p sase` appears hung because it is CPU-bound, not waiting on
I/O. A `py-spy` sample from the live process showed the hot path in:

- `CollectorSeedMixin._drain_queues`
- `CollectorRecordMixin._add_record_changespec_links`
- `CollectorGraphMixin._queue_record`
- `normalize_source_path`

The live process was repeatedly normalizing old artifact directories such as
`~/.sase/projects/sase/artifacts/ace-run/20260509010130`, outside the requested May 19-20 window.

The local scan confirms the scale of the fan-out:

- total `sase` records: `12727`
- date-window seed records: `255`
- seed records with ChangeSpec `sase`: `231`
- all records with ChangeSpec `sase`: `5672`

So project-scan date filtering applies to the seed set, but transitive expansion through ChangeSpec-related records
ignores the same project/date selector and pulls thousands of historical records into one episode build.

## Goals

1. Keep project-scan builds bounded by their project/date/limit selector.
2. Preserve rich transitive expansion for explicit selectors like `--agent`, `--artifact-dir`, `--changespec`, and
   `--chat`.
3. Avoid broad behavioral churn in episode rendering, storage, and explicit selector flows.
4. Add regression coverage that fails on the current unbounded project-scan behavior.

## Implementation Approach

1. Add a collector-level predicate for whether an `AgentArtifactRecordWire` is eligible for transitive inclusion.
   - For default project-scan selectors, require the record to match `selector.project`, `selector.since`, and
     `selector.until`.
   - Treat `selector.limit` as a seed limit, not a transitive hard cap, because the CLI help says it limits seed
     records.
   - For explicit selectors (`agent`, `artifact_dir`, `changespec`, `chat`), preserve current transitive behavior.

2. Apply the predicate at record queue boundaries instead of each individual expansion site.
   - Centralize this in `_queue_record` so ChangeSpec, bead, family, retry, parent, workflow-step, and chat expansions
     all honor the same boundary during project-scan builds.
   - Keep direct seed queueing working by ensuring the predicate admits all initially selected project-scan records.

3. Consider a small diagnostic warning only if useful and deterministic.
   - If records are skipped by project-scan bounds, the episode can still include the ChangeSpec source itself and any
     in-window records.
   - Avoid noisy counts unless tests show a stable, valuable user-facing warning.

4. Add focused tests.
   - Unit-level collector test: build from a project-scan selector with a date window where one seed record shares a
     ChangeSpec with an older out-of-window record. Assert only the in-window record is included.
   - Regression expectation: explicit `--agent` / `EpisodeSelector(agent=...)` still includes same-family or
     same-ChangeSpec related records as existing tests expect.
   - If needed, add a CLI-level JSON assertion for `metadata.agent_record_count`.

5. Verify.
   - Run focused memory episode tests first.
   - Because this repo requires it after code changes, run `just check` after implementation.

## Risk

The main risk is unintentionally weakening explicit selector episodes. The boundary must be conditional: only default
project-scan builds should constrain transitive records to the project/date window.
