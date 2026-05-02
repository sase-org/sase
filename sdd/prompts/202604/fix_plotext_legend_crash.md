---
plan: sdd/tales/202604/fix_plotext_legend_crash.md
---
Can you help me fix the below error? Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.

```
❯ sase telemetry dashboard -c

Traceback (most recent call last):
  File "/home/bryan/.local/bin/sase", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/entry.py", line 188, in main
    handle_telemetry_command(args)
    ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/main/telemetry_handler.py", line 34, in handle_telemetry_command
    handle_telemetry_dashboard(args)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/bryan/projects/github/sase-org/sase/src/sase/telemetry/cli_dashboard.py", line 416, in handle_telemetry_dashboard
    layout = _build_charts_dashboard(
        prom_url,
    ...<2 lines>...
        console.width,
    )
  File "/home/bryan/projects/github/sase-org/sase/src/sase/telemetry/cli_dashboard.py", line 339, in _build_charts_dashboard
    panel = render_line_chart(
        all_series,
    ...<4 lines>...
        legend_labels=legend_labels,
    )
  File "/home/bryan/projects/github/sase-org/sase/src/sase/telemetry/charts.py", line 53, in render_line_chart
    Text.from_ansi(plt.build()),
                   ~~~~~~~~~^^
  File "/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/plotext/_core.py", line 312, in build
    return _figure.build()
           ~~~~~~~~~~~~~^^
  File "/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/plotext/_figure.py", line 334, in build
    self._build_matrix()
    ~~~~~~~~~~~~~~~~~~^^
  File "/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/plotext/_figure.py", line 340, in _build_matrix
    self.monitor.build_plot() if not self.monitor.fast_plot else None
    ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/home/bryan/.local/share/uv/tools/sase/lib/python3.14/site-packages/plotext/_build.py", line 261, in build_plot
    [[self.matrix.insert_element(col_start + S + i, row_end - 1 - s, marker[s][i], color[s][i], style[s][i]) for i in range(3)] for s in range(l)] if legend_test else None
                                                                                   ~~~~~~~~^^^
IndexError: list index out of range


```
