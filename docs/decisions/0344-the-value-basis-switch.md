# 0344 — The report switches between the value bases the run computed

## Context
Blueprint 14.3: changing a basis in the report takes under five seconds; record 0084 moved this criterion to version 1.1 and asked for a measurement once the report takes a basis from the page. P27: the report carries precomputed results for the bases the run computed and switches without a new run; measure the switch time and the file size, and stop at 8 MB on the demo.

## Decision
- A run computes one reinsurance basis, one currency view and one basis of the triangles. What it computes on two value bases is the reserve: nominal, and, when a curve is named, discounted (CV10, M12). The page carries both and switches between them: the selected unpaid tiles, the selected unpaid per line, the blocks of the uncertainty page and the sensitivity tables are tagged `data-basis`; the switch at the top sets an attribute on the page, CSS hides the other basis and the charts of the shown blocks are resized. Nothing is recomputed. The page opens on the basis the run was asked for (`--value`). The inflation-adjusted figures of MT07 stay side by side with the nominal ones in their table; a basis of the triangles, gross, net or ceded, or another currency is a new run, and the page says so.
- Without a curve the switch shows one basis, disabled, and how to get the other.
- Printing prints the basis shown and names it.
- Size: the demo page is 5.21 MB with both bases (5.07 MB before this item); the plotly bundle is most of it.
- Switch time: the page measures itself when opened with `#measure-switch` (three rounds over the bases, each switch until the page is laid out again, written to `data-switch-ms` of the html element). A slow test opens the demo page with headless Edge or Chrome and asserts every switch under five seconds; it skips when no browser is found or the browser gives no page.

## Consequences
- In the environment of this item the browser could not be started from the test runner (the headless browser returned no page), so the switch time is **not measured** (UNVERIFIED); the owner can run `uv run pytest tests/report/test_demo_report_slow.py -q` on a desktop. A switch only toggles an attribute and resizes at most a handful of charts, so it is expected to take milliseconds, but that is an expectation, not a measurement.
