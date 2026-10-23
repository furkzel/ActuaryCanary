# 0073 — The printable document is the browser's print of the page; the page is offline

## Context
Blueprint 11 asks for an interactive single-file page and a printable document with identical numbers. The toolchain (0002) has no PDF engine, and the owner reads the report offline.

## Decision
- No separate PDF engine in 1.0. A print stylesheet (A4, a page break before every section, light colours, collapsed blocks opened, navigation hidden, smaller type for wide tables) makes the browser's "print to PDF" the printable document. Both come from one page, so the numbers are identical.
- The page makes no network request: plotly is inlined once; there is no external script, stylesheet, font or image. The plotly bundle itself contains URL strings used only by map traces, which the report never draws; the test checks the page outside the bundle for any `http://` or `https://`, and the whole page for external `src` or `href`.
- `project.yaml` fields are shown as text, never as links.

## Consequences
- Checked with headless Edge: the page draws, and print to PDF gives 36 A4 pages for the tiny baseline. The PDF was not inspected page by page.
