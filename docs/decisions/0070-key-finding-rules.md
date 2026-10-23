# 0070 — Key findings from fixed rules in spec/report/findings.yaml

## Context
Blueprint 11 asks for five to eight key-finding sentences from fixed rules, each with its number and a link to the evidence, never free-generated. P10 adds the spec kind for these rules. The owner listed the diagnostics the rules must cover: thin evidence, link ratios on fewer than three origins, zero-denominator cells, high last development with tail 1.0, paid ultimate below incurred to date, anomaly rate per line, quality findings.

## Decision
- New spec kind `report` with one file, `spec/report/findings.yaml` (id RP01, status draft), read like the alias files: by fixed file name, not by ID. A rule has an ID (KFnn), title, scope (`run`, `segment` or `line`), priority, condition, template, evidence (report section, output files, spec IDs) and an optional `banner`.
- A condition is clauses `fact op value` joined by `and`; op is one of `< <= > >= == !=`; value is a number or another fact. No other syntax, and no code is evaluated. A rule whose facts are not all known does not fire; a template naming a fact that is not computed is an error. Placeholders are formatted by the kind of their fact (amount, ratio, factor, count, score, text) with CV06 rounding.
- Facts are computed in `report/facts.py` from the run. Thresholds are read from the code that owns them (THIN_EVIDENCE_ORIGINS, FEW_LINK_RATIOS and LATE_DEVELOPMENT_FACTOR of 0039, MAX_FLAG_RATE of MT08), so a rule never repeats a threshold. The diagnostics rules count the diagnostics the methods raised, so they agree with `diagnostics.csv` by construction.
- Anomaly rate per line = values flagged by MT08 over values scored, over its two variables (payments, case-reserve movements), for the lines MT08 scored. The rule fires above MT08's own 5 % warning level.
- Key findings show the run and segment sentences by priority, at most eight; the rest follow as "further findings" on the same page. Line sentences appear on the reserving page of their line. Thin evidence (KF01) is a banner: on the cover and at the top of every analytic page, and it says that differences between methods are not precision.
- Templates are written so that a number never needs a plural ("Origins where …: 5").
- Rules beyond the owner's list: reserve estimate per segment; loss-ratio rise or fall of at least 5 points between the last two origins; premium growth or shrinkage of at least 10 % between the last two calendar periods; Mack not run; modules skipped or limited; methods differing by at least 10 % of the selected ultimate on a line. The 5-point and the two 10 % levels are this item's choice; they sit in the spec, where the owner can change them.

## Consequences
- A new sentence needs a spec change and, if it reads a new fact, code in `facts.py`. Tests check that every rule has a firing and a quiet case and that every fact a rule names is computed for its scope on the tiny baseline.
- The spec stays `draft` until the owner reviews the wording.
