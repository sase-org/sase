# Antigravity trajectory fixtures

These fixtures exercise SASE's guarded Antigravity (`agy`) trajectory extractor. The checked-in
tests build small benign SQLite trajectory databases from protobuf-wire payloads that contain only
harmless commands such as `echo`.

Do not copy arbitrary local Antigravity conversation databases into this directory. They may contain
prompts, file contents, command output, or other private workspace data. If the private Antigravity
trajectory format changes, refresh fixtures only from a controlled disposable workspace and inspect
the payloads before committing them.

`capture_fixture.py` documents the manual capture flow. It is not run by CI.
