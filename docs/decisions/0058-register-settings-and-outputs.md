# 0058 — The register, the method settings and the new outputs in the run

## Context
0037 left the register unwired: no file, no manifest entry. The owner asked that a different assumption gives a different run id and that the register and the method settings are in the manifest.

## Decision
- `canary run --assumptions <file.yaml>` reads a register (`entries:`, each with method, name, scope, target, value and, for a user entry, who and why). It is a run setting (`RunSettings.assumptions`), so it is in the settings of the manifest and in the run id. A malformed entry is a settings error (exit 2); an entry that names a cell or origin that does not exist stops the run with that message (exit 1).
- The settings record gains `methods`: the fixed parameters of the methods (selection measure and maturity threshold, the diagnostic thresholds, the robust z-score and isolation forest settings with the seed). They are constants in code, not options; a change gives another run id.
- New outputs, all unrounded and listed in the manifest in this order after the earlier ones: `assumptions.csv` (every judgement in force with value, default, who, when, why; platform defaults have who = default), `ultimates.csv` (RS02 table), `reserve_range.csv` (RS03 table), `cash_flows.csv` (MT07 expected payments by future period), `diagnostics.csv`, `anomalies.csv`. The manifest also lists the assumptions in force and the seed of MT09 under `randomness`.
- The specification list of the manifest names the methods that produced a result: MT03 to MT07 and MT10 when they ran, MT08 and MT09 always. MT06 is absent where Mack did not run.

## Consequences
- Runs that differ only in an assumption differ in id; rerunning the same register reproduces the id.
- The run ids of every example changed with this item (conversion by default in P09, methods wired here).
