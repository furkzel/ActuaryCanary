# 0120 — Started without a command: a welcome text, and a wait on a console of its own

## Context
`canary.exe` double-clicked in Explorer printed its help and the window closed at once; a newcomer saw nothing. From PowerShell everything worked.

## Decision
- `canary` with no command prints a short welcome (name, version, one line on what it is, `canary demo`, `canary run <folder>`, open PowerShell in this folder) and exits with code 0. `--help` is unchanged.
- On Windows, when no other process shares the console (`GetConsoleProcessList` through `ctypes` returns 1: started by double-click), and input is a console, it then waits for a key. From an existing terminal, or with input from a pipe, it exits at once. The check sits in `actuarycanary.cli.welcome.console_is_only_ours` and is replaced by a fake in tests. Standard library only.
- After `canary demo` the program prints where the report and the run folder are and one line on running on your own files, in lines of at most 80 columns (paths excepted).

## Consequences
- A real double-click cannot be tested in the fast suite; it is checked by hand by the owner.
