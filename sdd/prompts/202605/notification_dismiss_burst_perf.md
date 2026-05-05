---
plan: sdd/tales/202605/notification_dismiss_burst_perf.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

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

---------- Phase 7E regression floor (sase-1e.5) ----------
.venv/bin/python tests/perf/phase7_check_regression.py 


Phase 7E floor check FAILED.
==== Phase 7E floor: bench_core_parse ====

# golden_myproj (1019 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct           0.104        0.108      0.115      0.117
  rust_direct             0.030        0.033      0.034      0.043
  rust_facade             0.045        0.046      0.049      0.049

# synthetic_200_specs (132898 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct          10.826       10.899     11.131     18.611
  rust_direct             3.187        3.253      3.518      3.713
  rust_facade             4.563        4.613      4.986     12.349

==== Phase 7E floor: bench_core_query ====

# parse_only
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.008        0.008      0.010      0.011
  python_facade_parse               0.009        0.009      0.010      0.011
  rust_direct_parse                 0.003        0.003      0.004      0.004
  rust_facade_parse                 0.009        0.009      0.011      0.013

# synthetic_100_specs (100 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.007        0.008      0.010      0.010
  python_facade_parse               0.009        0.009      0.010      0.010
  python_parse_and_evaluate         0.357        0.369      0.383      0.402
  reference_python_batch_evaluate_many      0.378        0.383      0.414      0.418
  rust_one_shot_diagnostic_evaluate_many      3.643        3.683      3.754      3.892
  rust_persistent_corpus_compile      5.971        6.091      6.223      6.431
  rust_persistent_fully_compiled_evaluate_many      0.005        0.005      0.006      0.006
  rust_persistent_query_keystroke_evaluate_many      0.007        0.007      0.008      0.008

# synthetic_1000_specs (1000 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.007        0.008      0.009      0.009
  python_facade_parse               0.009        0.009      0.010      0.010
  python_parse_and_evaluate         3.590        3.671      3.742      3.749
  reference_python_batch_evaluate_many      3.833        3.893      4.024      4.043
  rust_one_shot_diagnostic_evaluate_many     37.278       37.841     38.870     39.246
  rust_persistent_corpus_compile     64.344       70.495     83.370     88.754
  rust_persistent_fully_compiled_evaluate_many      0.052        0.052      0.053      0.062
  rust_persistent_query_keystroke_evaluate_many      0.054        0.055      0.056      0.065

# home_tree [skipped]
  reason=pass --include-home-tree for local-only home-tree measurement

==== Phase 7E floor: bench_agent_scan ====

# synthetic_6p_200pp
  projects_root=/tmp/tmp9na3ju01/projects
  runs=8 warmup=2 target_name='proj001_agent_0000' workflow_name='wf_0'
  scenario                                 min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------------------------
  find_named_agent                          0.084        0.101      0.204      0.204
  is_workflow_complete                      0.070        0.079      0.143      0.143
  list_running_agents                       0.113        0.131      0.873      0.873
  list_all_agents                           0.098        0.126     50.924     50.924
  list_running_agents_shared_snapshot     108.463      110.612    112.498    112.498
  list_all_agents_shared_snapshot         106.907      113.556    114.612    114.612
  tui_artifact_load                         0.124        0.138      0.219      0.219
  scan_rust_to_dict                        92.890       93.777     94.451     94.451
  scan_rust_dict_to_wire                  128.546      130.870    131.677    131.677
  scan_rust_facade                        131.380      133.272    135.965    135.965

==== Phase 7E floor: bench_status_state_machine ====

# golden_myproj_pure (1019 bytes)
  runs=200 warmup=20 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   2.434        2.564      2.754      3.245
  remove_workspace_suffix                               0.731        0.781      0.921     13.170
  read_status_from_lines                                2.824        3.065      3.335      5.188
  apply_status_update                                   3.165        3.315      3.455     20.662
  plan_status_transition                               13.600       13.951     14.772     27.281

# golden_myproj_transition (1019 bytes)
  runs=5 warmup=10 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft           671.331      711.801    719.894    719.894
  transition_changespec_status_wip_to_ready           684.701      703.840    759.604    759.604

# synthetic_200_specs_pure (128808 bytes)
  runs=200 warmup=20 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   2.413        2.514      2.674      2.744
  remove_workspace_suffix                               0.721        0.771      0.832      0.911
  read_status_from_lines                              267.363      282.962    296.266    349.266
  apply_status_update                                 299.541      306.887    321.183    359.582
  plan_status_transition                               13.400       13.771     20.551     86.901

# synthetic_200_specs_transition (128808 bytes)
  runs=5 warmup=10 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft         12986.647    16114.528 276877.426 276877.426
  transition_changespec_status_wip_to_ready         13764.629    14119.984 231320.539 231320.539

==== Phase 7 floor: bench_notification_store ====

==== Phase 7E floor check results ====
  rust_slowdown_factor = 1.40x phase7b rust median
  [PASS] parse_project_bytes.golden_myproj.facade: rust=45.76us python=n/a ceiling=174.09us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_project_bytes.synthetic_200_specs.facade: rust=4612.84us python=n/a ceiling=26762.65us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_query.parse_only.direct: rust=3.41us python=8.34us ceiling=8.08us must_beat_python=True
  [PASS] evaluate_query_many.synthetic_1000_specs.persistent_query_keystroke: rust=54.92us python=3893.45us ceiling=93.38us must_beat_python=True
  [PASS] scan_agent_artifacts.synthetic_6p_200pp.scan_facade: rust=133272.34us python=n/a ceiling=167984.20us must_beat_python=False
        note: scenario 'scan_facade' missing from baseline (python) summaries
  [PASS] apply_status_update.golden_myproj_pure.apply_status_update: rust=3.32us python=n/a ceiling=8.12us must_beat_python=False
        note: scenario 'apply_status_update' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_load_snapshot: rust=10671.14us python=n/a ceiling=18466.00us must_beat_python=False
        note: scenario 'notification_store_5k_load_snapshot' missing from baseline (python) summaries
  [FAIL] notification_store.synthetic_5k.notification_store_5k_mark_dismissed_burst: rust=9915948.11us python=n/a ceiling=6811056.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_dismissed_burst' missing from baseline (python) summaries
        FAIL: absolute floor: rust median 9915948.11us exceeds ceiling 6811056.00us (=1.40x phase7b rust median 4865040.00us)
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_all_read: rust=82072.54us python=n/a ceiling=100359.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_all_read' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_append_plus_rewrite_concurrency: rust=2160078.64us python=n/a ceiling=2717251.60us must_beat_python=False
        note: scenario 'notification_store_append_plus_rewrite_concurrency' missing from baseline (python) summaries
  [FAIL] notification_store.synthetic_5k.notification_modal_dismiss_burst: rust=6207460.21us python=n/a ceiling=5098492.80us must_beat_python=False
        note: scenario 'notification_modal_dismiss_burst' missing from baseline (python) summaries
        note: absolute floor uses per-anchor rust_slowdown_factor 1.60x instead of global 1.40x: This modal path performs 25 production one-at-a-time persisted dismissals from a loaded 5k inbox and has shown multi-second GitHub-hosted runner IO variance; keep the extra slack local to this anchor while preserving the global 1.4x gate for stable floors.
        FAIL: absolute floor: rust median 6207460.21us exceeds ceiling 5098492.80us (=1.60x phase7b rust median 3186558.00us)

  report written to sdd/tales/202604/perf_artifacts/rust_backend_phase7_floor_check.json
error: Recipe `phase7-perf-check` failed on line 383 with exit code 1
Error: Process completed with exit code 1.
```