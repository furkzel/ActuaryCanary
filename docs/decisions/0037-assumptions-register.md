# 0037 — The assumptions register as data

## Context
Blueprint section 12 asks for every judgement (selected factors, exclusions, prior loss ratios, future inflation, tail factors, selection overrides) to be recorded with who chose it, when, why and the alternative. No register existed; methods must stay pure functions on arrays (record 0022).

## Decision
- An entry (`methods/assumptions.py`) has: method (spec ID), name (a parameter of that spec), scope (group and measure such as `NON_LIFE/MOTOR_TPL/paid`, or `*` for every scope), target, value, default, who, when, why. The default is the alternative the entry replaces.
- Targets: empty for the whole scope, an origin label (`2021`), a development column by ages (`12-24`) or a cell (`2021:12-24`).
- An entry for the exact scope wins over one for `*`. Two entries for the same method, name, scope and target are an error; so is an entry whose target does not exist or whose value is not a number where one is needed (a settings error, never a guess).
- A user entry must say why. Platform defaults are recorded too, with who = `default`; a tail factor taken from the run settings has who = `run settings`.
- `methods/judgement.py` turns entries into method parameters and returns the entries in force: MT02 tail_factor, exclusion, selected_factor; MT03 prior_loss_ratio; MT05 expected_loss_ratio; MT07 future_inflation; MT10 bf_below_maturity and method. A register can be read from YAML (an `entries:` list).

## Consequences
- Every judgement a method uses can be listed with its value, default, who, when and why.
- Not yet wired: `canary run` neither reads a register file nor writes the entries to the manifest; that comes with wiring the methods into the reserving module (P09 owns `modules/`).
