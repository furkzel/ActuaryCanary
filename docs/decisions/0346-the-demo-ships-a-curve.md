# 0346 — The demo ships the scenario's interest rates and names its curve

## Context
Record 0328 kept the examples without interest rates and left to the owner whether the demo should ship a curve. P27 decides it: the demo gets the generator's interest-rate workbook (curve `TRY_GOV`) so that its report shows the discounted basis; `baseline` and `messy_headers` stay without interest rates. This supersedes 0328 for the demo only.

## Decision
- `just examples` copies `phase2/interest_rates.xlsx` of the demo scenario into `examples/demo/` beside the six workbooks (byte for byte what the generator writes; the slow examples test compares it) and runs the demo with the curve named.
- `canary demo` names the curve (`cli/demo.py`, `DEMO_CURVE`). A run of the folder equals the demo with `canary run examples/demo --yes --curve TRY_GOV`; without `--curve` the run id differs (nothing is discounted). The guide, the packaging comparison's note and the CLI test say so. The PyInstaller spec bundles every workbook of the folder, so the program gets the new one without a change of the spec.
- Run ids after this item: baseline `bd4528a4bbd8153d`, messy_headers `50b4544ddd98dcb8`, demo `5051bffa374d4614` (with the curve).

## Consequences
- The demo report carries both value bases (0344); its `quality.json` covers interest rates; the six workbooks are unchanged.
- The packaged program's comparison against the new manifest was not run in this item (the program was not rebuilt): UNVERIFIED until P37 rebuilds it.
