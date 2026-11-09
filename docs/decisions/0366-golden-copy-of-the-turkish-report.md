# 0366 — Golden copy of the Turkish report; the language is an input of the run id

## Context
Gate G5 (record 0365) failed on its criterion "golden test in both languages": `tests/report/golden/` held only the English run of the tiny baseline. The work item for this record assumed that the report language is not an input of the run id, so that one run id would serve both copies. That assumption was wrong. Record 0224 decided that the language enters the run id, and `RunSettings.language` is part of the settings record that the run id is computed from. The tiny baseline gives `fecc00f2e344bce0` in English and `0698a73e313af299` in Turkish (measured on 2026-11-09).

## Decision
1. The reading of 0224 stands. The language stays an input of the run id; the Turkish golden copy carries its own run id.
2. `tests/report/golden/baseline_tiny_tr.json` is the golden copy of the tiny baseline run with `RunSettings(language="tr")`, with the same structure and normalisation as `baseline_tiny.json`. `just golden` writes both files; `tests/report/test_golden.py` is parametrised over the two languages.
3. `test_run_ids_differ_by_language_and_each_is_stable` states that the two run ids of the same inputs differ and that each equals the id held in its golden copy (first row of the cover).
4. `test_the_turkish_golden_holds_the_turkish_labels_and_no_english_page_labels` checks that the Turkish copy holds a Turkish sentence for every finding rule of the English copy and the Turkish labels of the uncertainty, reserving, large-loss and survival parts, and none of their English labels. `tests/report/test_language.py` stays the second line.

## Consequences
- `just golden` added one file and changed no other; `just examples` left the run ids of the three examples unchanged (baseline `fecc00f2e344bce0`, messy_headers `68ce22e143a5d0fd`, demo `ab54e1cb5917e20e`).
- The fast suite runs the tiny baseline once more (Turkish), about 6 s.
