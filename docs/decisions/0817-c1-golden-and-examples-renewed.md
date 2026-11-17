# 0817 — C1: the golden copy and the example reports renewed; no value moved

## Context
Records 0815 and 0816 change the report model (scopes, tables by segment, four segment-scope findings) and the spec versions M07 0.1.1, M08 0.2.1, M09 0.1.1 and RP01 1.6.1, which are part of every run id.

## Golden (`just golden`, once; tiny baseline)
English: 66 leaves changed, 418 added, 162 removed; Turkish: 66, 421, 165 (the three extra added and removed leaves are `separators` of the charts). Groups, English:
- **Scope declarations**: 184 added leaves (`scopes` of the model, of the 8 pages that ran and of the reserving page).
- **Recovery charts renamed by segment**: 162 leaves removed and 162 added (`recoveries-<type>` to `recoveries-<type>-non_life`; LIFE has no recoveries and no chart); in the page body 6 changed leaves (ids, titles) and 3 added (`segment`), and the figure note (1).
- **Headlines of M07 and M09 cut by segment**: 21 changed and 36 added leaves (the company rows became the rows of LIFE and NON_LIFE). **M09 unit costs** and **M07 delays**: 13 changed and 28 added, 2 changed and 5 added. The values that change are company-level figures replaced by segment figures; the segment- and line-level tables (M07 by origin, M09 by line, tiles, reserving) have no changed leaf.
- **Page specs**: 2 changed leaves (M07 and M09 versions).
- **KF35**: 5 leaves, run to segment scope; the sentence now reads "NON_LIFE: ... 3.0% of claims paid" (0.9% when LIFE's paid was in the denominator).
- **Versions and ids**: 4 spec versions, the findings spec version, 2 evidence strings, the run id (in two places).
- **Outputs and lineage**: `measures.csv`, `lineage.csv` and `modules.json` (hash and size, 6 leaves) and 3 lineage counts, because the segment views add rows.
No ungrouped leaf. New tiny run ids: English `779e22b6b4b6e3a3` (was `2f208e5a0555408a`), Turkish `77baa3bd261c52f9` (was `647e87b0405b476c`).

## Examples (`refresh_examples.py --reports-only`, once, 45 s)
Only `report/report.html` and `report/manifest.json` of the three examples changed; the demo's profile file is byte-identical (the tool keeps it, record 0816). Run ids: demo `c6d0ee3c598ec090` (was `713ca5af937d4139`), baseline `779e22b6b4b6e3a3` (was `2f208e5a0555408a`; equal to the tiny golden id), messy_headers `4921edeee32f018d` (was `6e8aab673878c0cc`). The demo's M07, M08 and M09 pages have no figure over both segments; what is booked at company level is labelled.

## Consequences
`docs/guide.md` still names the three old run ids (outside this item's area); the owner or the next item updates them.
