# Agents-Tab Reproduction Fixtures

This directory contains commit-safe bundles for reproducing Agents-tab load/apply bugs without
depending on a private `~/.sase` corpus.

Run the known disappearing/reappearing rows fixture from a prepared checkout:

```bash
sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json --assert-stable --json
```

If the checkout's `sase` command is not on `PATH`, run `just install` first and use `.venv/bin/sase`
from the repo root. The current expected result is:

```json
{
  "result": "passed",
  "failed_invariants": [],
  "verdict": "current code fixed for the captured Agents-tab bug class"
}
```

To preserve visual evidence while replaying, add
`--write-artifacts /tmp/sase-agents-tab-repro-artifacts`. The command writes one `.txt` screen dump
and one `.svg` screenshot per replay step.

When creating a new regression fixture, start from a redacted bundle:

1. In the running ACE Agents tab, press `,B` immediately after seeing the bug. This writes
   `agents_tab_repro.json` under `~/.sase/repros/<timestamp>-manual-.../`.
2. Replay it locally with
   `sase repro replay <bundle> --assert-stable --json --write-artifacts <dir>`.
3. If the fixture is useful for CI, keep it commit-safe: no absolute home paths, chat bodies, prompt
   bodies, response bodies, or diff bodies.

Out-of-band capture is available for source-of-truth filesystem state:

```bash
sase repro capture agents-tab --output /tmp/sase-agents-tab-capture --commit-safe --json
```

That path is useful for a baseline bundle, but it cannot reconstruct refreshes that already happened
inside a live TUI session. Use the in-TUI capture for transient disappearance, reappearance, or
duplicate-parent bugs.
