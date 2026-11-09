# 0705 — The language file, one language control, the routing, and the tests

## Context
Every screen needs English and Turkish text kept in one file in the style of `report/language.yaml`; a missing Turkish text must fail a test. No headless browser is part of the toolchain.

## Decision
- **`ui/strings.yaml`** holds entries of `id`, `en`, `tr`. The report file is keyed by the English text; the page also needs the text in script, so the key is an id (`start.title`). The server renders the page with the texts of one language and embeds the same table for the script. Tests fail for an entry without a Turkish text, for a placeholder in only one language, for an id the page or the script asks for that the file lacks, for an id nothing uses, for a value of a list (bases, periods, layers, stages, severities) without a text, for an error code of the server without a text, and for an English label left on the Turkish page. Entries equal in both languages are listed by name (a product name, "Net", "Nominal", "IBNR").
- **Text of the pipeline is not translated**, as in 0224: data-rule messages, the evidence of a mapping, the error of a failed run (the terminal's own text), the reason a sheet was not recognised.
- **One language control.** The two links in the header (English, Türkçe) reload the page in that language, and the form's "Language of the page and report" starts with the same value; it is the `--lang` of the run, so a Turkish page makes a Turkish report unless the person changes the field. The terminal stays English.
- **Routing** is the part of the address after `#` (`#start`, `#mapping`, `#run`, `#result?out=&run=`, `#past`), so the back button and a reload work. A page opened while a run is going shows the run. The form is remembered in the tab (`sessionStorage`, optional) so that switching language keeps it.
- **Accessibility:** landmarks, a skip link, a label for every control (a test), tables with column and row headers, a live region that announces a change of screen and the result of an action, visible focus, keyboard-only operation with native controls and a native `dialog` for the folder chooser, dark text on a light page (colours of the report; no dark theme in this prototype), layouts for laptop and phone width, no external font.
- **Tests without a browser.** The template is rendered in both languages and parsed with `html.parser`; the script is read for the ids it reaches and the routes it calls. The server is started in-process on a random port. By hand, outside the repository, the page was driven in headless Microsoft Edge through its debugging protocol for the whole path (start, mapping edit and save, run, result, report frame, back button, past runs); screenshots at laptop and phone width were looked at. That is not part of the test suite and was done on this machine only.

## Consequences
- The page was not checked in Firefox or Safari, nor by a screen reader (UNVERIFIED).
