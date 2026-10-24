# 0224 — The report in English or Turkish (`--lang`)

## Context
The report page had English labels and sentences written into the code and the templates. The owner decided: English stays the default, Turkish through `--lang tr`, insurance terms in common Turkish usage, the terminal stays English, and the language enters the run id.

## Decision
- **Resource.** `report/language.yaml` lists English text and Turkish text side by side (about 370 entries). The English text is also the key the code asks for, `t("Key findings")`, with `{name}` placeholders for what is filled in (`th` for text with markup, whose values are escaped). English is returned as written, so the English page and the golden copy do not change; a text without a Turkish entry stays English. The language is a context variable set by `language.using(...)` around the model and the page, so no function needs a parameter.
- **RP01 1.1.0.** Every rule has `title_tr` and `template_tr` beside its English text, with the same facts; a test compares the placeholders. `facts_named` checks both.
- **Names from the specifications.** Module, measure, method and specification titles use their `title_tr`. The six module questions and the disclaimer are in the resource.
- **Numbers.** Turkish uses 1.234,5 and %12,3 (sign before the percent sign), "puan" for points; the rounding is CV06 as before. Plotly figures get `separators: ",."`.
- **Setting.** `RunSettings.language` ("en" or "tr"), `canary run --lang`, part of the run id and the manifest settings. Only `report.html` changes; CSV, JSON and the terminal stay English.
- **Not translated, on purpose:** text that is data or computed from the run and not a label: messages of data rules, quality findings and diagnostics, the reasons of anomaly flags and of modules that did not run, notes of measures, and the wording of the specifications (rule texts, method definitions and assumptions, which have no Turkish text). They are named in the test, which finds every English sentence on the Turkish page and requires it to be one of them. Translating them is a task of its own: they need Turkish text in the specifications.

## Consequences
- The golden test and the examples use English; a new fast test checks the resource, the numbers and RP01, a slow one renders the Turkish page of the baseline and finds no label left in English.
- Turkish wording is by the author of this record and UNVERIFIED by a Turkish-speaking actuary; it needs the owner's reading, in particular: muallak hasar karşılığı (case reserve), zincir merdiven (chain ladder), kaynak yılı (origin), bağlantı oranı (link ratio), nihai hasar (ultimate).
