---
plan: sdd/tales/202605/phase7_agent_scan_perf_failure.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
  
```
Run just phase7-perf-check

---------- Phase 7E regression floor (sase-1e.5) ----------
.venv/bin/python tests/perf/phase7_check_regression.py 

Phase 7E floor check FAILED.

==== Phase 7E floor: bench_core_parse ====

# golden_myproj (981 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct           0.147        0.156      0.188      0.203
  rust_direct             0.039        0.040      0.047      0.063
  rust_facade             0.063        0.066      0.076      0.087

# synthetic_200_specs (125298 bytes)
  runs=15 warmup=3
  rust_available=True
  scenario               min_ms    median_ms     p95_ms     max_ms
  ----------------------------------------------------------------
  python_direct          14.756       15.025     15.406     22.755
  rust_direct             3.927        3.993      4.059      4.238
  rust_facade             5.691        5.780      6.165     13.986

==== Phase 7E floor: bench_core_query ====

# parse_only
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  --------------------------------------------------------------------------
  python_direct_parse               0.011        0.012      0.014      0.015
  python_facade_parse               0.012        0.013      0.016      0.043
  rust_direct_parse                 0.004        0.005      0.005      0.005
  rust_facade_parse                 0.012        0.013      0.013      0.014

# synthetic_100_specs (100 specs)
  query='"feature" OR status:Ready'
  scenario                         min_ms    median_ms     p95_ms     max_ms
  is_valid_transition                                   3.617        3.812      4.058     22.713
  remove_workspace_suffix                               1.092        1.133      1.203      1.683
  read_status_from_lines                                3.236        3.557      4.188     28.282
  apply_status_update                                   3.557        3.957      4.088     17.232
  plan_status_transition                               19.637       20.253     21.610    297.989

# golden_myproj_transition (981 bytes)
  runs=5 warmup=10 target_name='beta'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft           791.914      842.620    876.504    876.504
  transition_changespec_status_wip_to_ready           854.141      897.513   1892.219   1892.219

# synthetic_200_specs_pure (121208 bytes)
  runs=200 warmup=20 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  is_valid_transition                                   3.507        3.676      3.887     17.703
  remove_workspace_suffix                               1.042        1.082      1.153      1.302
  read_status_from_lines                              334.597      362.885    398.938    472.877
  apply_status_update                                 367.549      385.102    437.790   1872.231
  plan_status_transition                               18.976       19.526     21.410    114.905

# synthetic_200_specs_transition (121208 bytes)
  runs=5 warmup=10 target_name='spec-199'
  scenario                                             min_us    median_us     p95_us     max_us
  ----------------------------------------------------------------------------------------------
  transition_changespec_status_wip_to_draft         18918.684    19086.950  19211.494  19211.494
  transition_changespec_status_wip_to_ready         18360.818    18573.647  18991.962  18991.962

==== Phase 7 floor: bench_notification_store ====

==== Phase 7E floor check results ====
  rust_slowdown_factor = 1.40x phase7b rust median
  [PASS] parse_project_bytes.golden_myproj.facade: rust=65.90us python=n/a ceiling=174.09us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_project_bytes.synthetic_200_specs.facade: rust=5780.27us python=n/a ceiling=26762.65us must_beat_python=False
        note: scenario 'facade' missing from baseline (python) summaries
  [PASS] parse_query.parse_only.direct: rust=4.60us python=11.63us ceiling=8.08us must_beat_python=True
  [PASS] evaluate_query_many.synthetic_1000_specs.persistent_query_keystroke: rust=69.17us python=4920.44us ceiling=93.38us must_beat_python=True
  [FAIL] scan_agent_artifacts.synthetic_6p_200pp.scan_facade: rust=174449.33us python=n/a ceiling=167984.20us must_beat_python=False
        note: scenario 'scan_facade' missing from baseline (python) summaries
        FAIL: absolute floor: rust median 174449.33us exceeds ceiling 167984.20us (=1.40x phase7b rust median 119988.71us)
  [PASS] apply_status_update.golden_myproj_pure.apply_status_update: rust=3.96us python=n/a ceiling=8.12us must_beat_python=False
        note: scenario 'apply_status_update' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_load_snapshot: rust=16420.23us python=n/a ceiling=18466.00us must_beat_python=False
        note: scenario 'notification_store_5k_load_snapshot' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_dismissed_burst: rust=21185.23us python=n/a ceiling=6811056.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_dismissed_burst' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_5k_mark_all_read: rust=20399.74us python=n/a ceiling=100359.00us must_beat_python=False
        note: scenario 'notification_store_5k_mark_all_read' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_store_append_plus_rewrite_concurrency: rust=2334265.04us python=n/a ceiling=2717251.60us must_beat_python=False
        note: scenario 'notification_store_append_plus_rewrite_concurrency' missing from baseline (python) summaries
  [PASS] notification_store.synthetic_5k.notification_modal_dismiss_burst: rust=104779.25us python=n/a ceiling=5098492.80us must_beat_python=False
        note: scenario 'notification_modal_dismiss_burst' missing from baseline (python) summaries
        note: absolute floor uses per-anchor rust_slowdown_factor 1.60x instead of global 1.40x: This modal path performs 25 production one-at-a-time persisted dismissals from a loaded 5k inbox and has shown multi-second GitHub-hosted runner IO variance; keep the extra slack local to this anchor while preserving the global 1.4x gate for stable floors.

  report written to sdd/tales/202604/perf_artifacts/rust_backend_phase7_floor_check.json
error: Recipe `phase7-perf-check` failed on line 434 with exit code 1
Error: Process completed with exit code 1.
```