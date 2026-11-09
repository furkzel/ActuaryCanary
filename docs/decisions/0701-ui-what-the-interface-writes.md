# 0701 — What the interface writes, and where

## Context
The item says the interface never writes outside the output folder the person chooses and never deletes anything, and also that a confirmed mapping profile is saved "in the same format and place the CLI uses". The command line reads and writes profiles in `profiles/` of the working folder and keeps its spreadsheet cache in `.cache/` of the working folder.

## Decision
- A run writes `<out>/<run id>/` through `pipeline.run`, exactly as the command line does, and the reader cache goes to `<out>/.cache` (the command line uses `.cache` of the working folder; the cache does not enter any run id, so this changes no number). The scan of a folder for the mapping screen uses the same cache.
- **One exception, on purpose:** a confirmed mapping is saved by `save_profile` into the profiles folder, which defaults to `profiles` of the working folder (the default of `--profiles`). It is shown on the page ("Folder of mapping profiles"), written only when the person presses a confirm button, and the next run, from the page or from the terminal, reads it. If the owner wants the strict reading of the item, the folder can be set to a folder inside the output folder on the page and with `canary ui --profiles`; the default stays the command line's.
- The demo writes to a temporary folder (`canary-demo-*` in the system's temporary folder), made once per start of the server, and shows the result from there; the demo reads profiles but writes none (its sheets are in the canonical layout).
- The interface deletes nothing: no run folder, no cache, no profile, no temporary demo folder. Past runs are listed, never removed. Folder browsing lists names and counts files by suffix; it reads no file.
- Relative paths typed on the page start at the folder the program runs in, as on the command line.

## Consequences
- A test runs a whole run through the interface and compares the tree: the sandbox holds the output folder and nothing else, the input folder is as it was (`tests/ui/test_end_to_end.py`).
- Because the demo output folder is not removed, a person who runs the demo many times in many starts leaves several temporary folders; the system cleans its temporary folder.
