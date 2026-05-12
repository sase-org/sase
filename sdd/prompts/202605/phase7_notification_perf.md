---
plan: sdd/epics/202605/phase7_notification_perf.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Do not lower the expected performance expectations. Do what needs to be done to make things faster if necessary and then verify that the benchmark GitHub Actions workflow passes. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

  
```
Run just phase7-perf-check
  just phase7-perf-check
  shell: /usr/bin/bash -e {0}
  env:
    SASE_CORE_DIR: /home/runner/work/sase/sase/sase-core
    UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
    CARGO_HOME: /home/runner/.cargo
    CARGO_INCREMENTAL: 0
    CARGO_TERM_COLOR: always

.venv/bin/python tests/perf/phase7_check_regression.py 
---------- Phase 7E regression floor (sase-1e.5) ----------


Phase 7E floor check FAILED.
==== Phase 7E floor: bench_core_parse ====

# golden_myproj (981 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct           0.123        0.127      0.142      0.157
  rust_direct             0.039        0.040      0.045      0.061
  rust_facade             0.058        0.062      0.065      0.077

# synthetic_200_specs (125298 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct          13.005       13.190     14.940     22.531
  rust_direct             4.040        4.100      4.149      4.152
  rust_facade             5.901        6.261      6.877     17.163

==== Phase 7E floor: bench_core_query ====

# parse_only
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.010        0.011      0.014      0.015
  python_facade_parse               0.012        0.013      0.014      0.015
  rust_direct_parse                 0.004        0.004      0.005      0.005
  rust_facade_parse                 0.012        0.012      0.013      0.013

# synthetic_100_specs (100 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.010        0.010      0.011      0.013
  python_facade_parse               0.012        0.012      0.013      0.013
  python_parse_and_evaluate         0.450        0.461      0.478      0.478
  reference_python_batch_evaluate_many      0.487        0.495      0.510      0.520
  rust_one_shot_diagnostic_evaluate_many      4.754        4.840      4.867      4.951
  rust_persistent_corpus_compile      7.931        8.062      8.158      8.264
  rust_persistent_fully_compiled_evaluate_many      0.007        0.007      0.007      0.007
  rust_persistent_query_keystroke_evaluate_many      0.009        0.009      0.010      0.010

# synthetic_1000_specs (1000 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.010        0.010      0.011      0.011
  python_facade_parse               0.012        0.012      0.016      0.020
  python_parse_and_evaluate         4.567        4.647      4.777      4.811
  reference_python_batch_evaluate_many      4.862        4.999      5.364      9.413
  rust_one_shot_diagnostic_evaluate_many     48.270       48.849     49.404     50.858
  rust_persistent_corpus_compile     82.826       86.882    107.475    109.951
  rust_persistent_fully_compiled_evaluate_many      0.063        0.063      0.067      0.078
  rust_persistent_query_keystroke_evaluate_many      0.067        0.068      0.073      0.080

# home_tree [skipped]
  reason=pass --include-home-tree for local-only home-tree measurement

==== Phase 7E floor: bench_agent_scan ====

# synthetic_6p_200pp
  projects_root=/tmp/tmpr24l9e45/projects
  runs=8 warmup=2 target_name='proj001_agent_0000' workflow_name='wf_0'
  scenario                                 min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------------------------
  find_named_agent                          0.125        0.133      0.199      0.199
  is_workflow_complete                      0.093        0.114      0.186      0.186
  list_running_agents                       0.150        0.167      0.241      0.241
  list_all_agents                           0.123        0.134      0.214      0.214
  list_running_agents_shared_snapshot     147.352      150.837    156.958    156.958
  list_all_agents_shared_snapshot         154.908      161.811    163.720    163.720
  tui_artifact_load                         0.157        0.182      0.262      0.262
  scan_rust_to_dict                       128.948      129.998    134.075    134.075
  scan_rust_dict_to_wire                  173.855      179.513    244.752    244.752
  scan_rust_facade                        173.610      180.882    247.578    247.578

==== Phase 7E floor: bench_status_state_machine ====

# golden_myproj_pure (981 bytes)
  runs=200 warmup=20 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   3.155        3.325      3.496      4.056
  remove_workspace_suffix                               0.981        1.041      1.151      1.342
  read_status_from_lines                                3.545        3.885      4.057     17.256
  apply_status_update                                   3.936        4.287      4.476     13.901
  plan_status_transition                               17.787       18.543     19.900     37.807

# golden_myproj_transition (981 bytes)
  runs=5 warmup=10 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft           756.879      765.432    816.388    816.388
  transition_changespec_status_wip_to_ready           743.198      761.596    795.707    795.707

# synthetic_200_specs_pure (121208 bytes)
  runs=200 warmup=20 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   3.105        3.305      3.495      3.915
  remove_workspace_suffix                               0.971        1.022      1.102      1.271
  read_status_from_lines                              319.932      341.038    356.016    441.664
  apply_status_update                                 355.706      365.976    380.272    418.009
  plan_status_transition                               17.627       18.322     19.519    135.805

# synthetic_200_specs_transition (121208 bytes)
  runs=5 warmup=10 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft         15566.702    16571.985  17030.834  17030.834
  transition_changespec_status_wip_to_ready         15895.817    16063.049  16635.811  16635.811

==== Phase 7 floor: bench_notification_store ====

==== Phase 7E floor check results ====
  rust_slowdown_factor = 1.40x phase7b rust median
  [PASS] parse_project_bytes.golden_myproj.facade: rust=61.80us python=n/a ceiling=174.09us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_project_bytes.synthetic_200_specs.facade: rust=6261.07us python=n/a ceiling=26762.65us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_query.parse_only.direct: rust=4.48us python=10.85us ceiling=8.08us must_beat_python=True
  [PASS] evaluate_query_many.synthetic_1000_specs.persistent_query_keystroke: rust=67.99us python=4999.24us ceiling=93.38us must_beat_python=True
  [PASS] scan_agent_artifacts.synthetic_6p_200pp.scan_facade: rust=180881.53us python=n/a ceiling=191981.94us must_beat_python=False
        note: scenario 'scan_facade' missing from baseline (python) summaries
        note: absolute floor uses per-anchor rust_slowdown_factor 1.60x instead of global 1.40x: The Phase 7B baseline (~120 ms) predates several intentional agent-scan wire-shape expansions: pending_question.json marker scanning, workspace_dir / agent-meta tag / PDF activity / image paths / workflow-relationship / epic-start fields on agent_meta and done markers. On the 6-project x 200-per-project synthetic each addition increases both serde parsing on the Rust side and per-record Python dataclass hydration; the dict-to-wire pass alone adds ~40 ms over the captured baseline. Local median sits around 150 ms; GitHub-hosted runner medians have been observed around 174 ms. Use a 1.60x absolute floor to absorb this without weakening the global 1.4x gate for stable anchors; revisit when the Python hydration is pushed across the PyO3 boundary.
  [PASS] apply_status_update.golden_myproj_pure.apply_status_update: rust=4.29us python=n/a ceiling=8.12us must_beat_python=False
        note: scenario 'apply_status_update' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_load_snapshot: rust=13598.70us python=n/a ceiling=18466.00us must_beat_python=False
        note: scenario 'notification_store_5k_load_snapshot' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_dismissed_burst: rust=20097.83us python=n/a ceiling=6811056.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_dismissed_burst' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_all_read: rust=18852.65us python=n/a ceiling=100359.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_all_read' missing from baseline (python) summaries
  [FAIL] notification_store.synthetic_5k.notification_store_append_plus_rewrite_concurrency: rust=2762291.15us python=n/a ceiling=2717251.60us must_beat_python=False
        note: scenario 'notification_store_append_plus_rewrite_concurrency' missing from baseline (python) summaries
        FAIL: absolute floor: rust median 2762291.15us exceeds ceiling 2717251.60us (=1.40x phase7b rust median 1940894.00us)
  [PASS] notification_store.synthetic_5k.notification_modal_dismiss_burst: rust=118823.69us python=n/a ceiling=5098492.80us must_beat_python=False
        note: scenario 'notification_modal_dismiss_burst' missing from baseline (python) summaries
        note: absolute floor uses per-anchor rust_slowdown_factor 1.60x instead of global 1.40x: This modal path performs 25 production one-at-a-time persisted dismissals from a loaded 5k inbox and has shown multi-second GitHub-hosted runner IO variance; keep the extra slack local to this anchor while preserving the global 1.4x gate for stable floors.

  report written to sdd/tales/202604/perf_artifacts/rust_backend_phase7_floor_check.json
error: Recipe `phase7-perf-check` failed on line 450 with exit code 1
Error: Process completed with exit code 1.
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `sase-core`)