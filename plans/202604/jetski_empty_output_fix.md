---
create_time: 2026-04-24 19:20:30
status: done
---
# Jetski Empty Output Fix Plan

## Problem

The `jetski-cli` provider in `sase-google` occasionally (or frequently) returns an empty string as the result of an LLM
invocation, even though the CLI tool correctly printed the response to its standard output. This can be observed in the
SASE ACE interface where agents using the Jetski provider complete successfully (status `DONE`) but produce no response.

## Root Cause

The root cause is a race condition in `sase/llm_provider/_subprocess.py` within the `stream_process_output` function.

1. `stream_process_output` configures the subprocess's `stdout` and `stderr` pipes as non-blocking using
   `os.set_blocking(fileno, False)`.
2. It then reads from these streams in a `while True:` loop using `select()`.
3. If the subprocess exits quickly (which Jetski often does), `process.poll()` becomes non-`None` before all output is
   read.
4. The code then attempts to read any remaining output using a `for line in process.stdout:` loop.
5. Because `process.stdout` is a `TextIOWrapper` with a non-blocking underlying stream, the Python `io` module is prone
   to raising `BlockingIOError` (a subclass of `OSError`) when attempting to read if the buffer doesn't have a complete
   newline yet.
6. The `for line in process.stdout:` loop is wrapped in a `try...except OSError: pass` block. When `BlockingIOError` is
   raised, it is silently caught, the loop terminates immediately, and any remaining data in the stream is lost. This
   results in the final `stdout_content` being empty.

## Solution

When the process has already exited (`process.poll() is not None`), the process will not write any more data. To
reliably read the remaining data from the pipes until EOF without triggering `BlockingIOError`, we must restore the file
descriptors to blocking mode before performing the final read.

### Implementation Steps

1. Modify `stream_process_output` in `src/sase/llm_provider/_subprocess.py`. Before the final
   `for line in process.stdout:` loop, add `os.set_blocking(process.stdout.fileno(), True)`.
2. Do the same for `process.stderr`.
3. Apply the same fix to `stream_and_parse_json_output` and `stream_and_parse_codex_json_output` in the same file to
   prevent similar race conditions for Claude and Codex providers.

This fix will ensure that all remaining output is fully flushed and read before the function returns.
