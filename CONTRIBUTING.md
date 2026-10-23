# Contributing

Thank you for helping. The repository is organised so that the specification is read first and the code second; this page is what you need to make a change that fits.

## Setup

```
uv tool install rust-just    # once, if `just` is missing
just setup                   # uv sync and the pre-commit hook
just check                   # must pass before you push
```

`just` lists every recipe. The ones you will use: `check` (format, lint, types, fast tests including the docs check), `test-all` (also the slow tests), `fmt`, `synth` (a synthetic scenario with ground truth), `bench` (timing of a run), `golden` (rewrite the golden report copy after an intended change), `notes` (rewrite the worked examples of the method notes), `examples` (regenerate the example reports), `docs-check` (the documentation tests alone).

## Where things live

| Folder | Content |
| --- | --- |
| `spec/` | One specification per rule, measure, method, module and convention: the source of truth |
| `src/actuarycanary/` | The implementation; one subpackage per component |
| `tests/` | Tests, mirroring the package; `fixtures/hand/` and `benchmarks/` hold the hand-worked and benchmark references |
| `synthetic/scenarios/` | Parameters of the synthetic insurers, with a fixed seed |
| `examples/` | Sample datasets and the reports they produce |
| `docs/` | `guide.md`, `methods/` (one note per method), `decisions/` (one record per choice), `blueprint.md` |

## Rules

- **Specification first.** Change `spec/` before code. A business rule lives in exactly one spec file, and tests name the spec ID they prove. A spec without a test is not done.
- **Decision records.** Write one short numbered record in `docs/decisions/` for every real choice (context, decision, consequences). Records are superseded, never edited. Take the next free number after looking at the folder.
- **Names come from the domain** (`earned_premium`, `case_reserve`), small pure functions, no magic numbers: a threshold or default lives in a spec or a named constant with a reason.
- **Branches.** Work on a branch named `s/<ID>-<slug>` and open a pull request describing what changed and why. The maintainer merges; never push to `main`.
- **Commits.** Small, with a clear subject and a body that says why. Plain messages: no trailers and no generated-by lines.
- **Language.** Code, comments, commits and documents in English. Turkish appears only as labels in the dictionaries and the glossary.
- **Data.** Synthetic data only; never commit personal data, company data or anything from an employer. Spreadsheets are committed only under `tests/fixtures/` and `examples/`.
- **Dependencies.** Add none without a decision record and the maintainer's approval. The toolchain is fixed in [decision 0002](docs/decisions/0002-toolchain.md).
- **Honesty.** Say "verified" only for what you ran; otherwise write UNVERIFIED.

## Tests

- The fast suite (`just test`) stays under 30 seconds and each fast test under 0.5 s; anything slower is marked `@pytest.mark.slow`. Hypothesis uses the 25-example `dev` profile locally.
- Build fixtures in code. Only reader tests open spreadsheets, and spreadsheets are read once and cached as parquet keyed by SHA-256 in `.cache/`.
- A method enters the platform with a written spec, a hand-worked fixture, a ground-truth test on synthetic data and, where one exists, a match against a published benchmark triangle.

## Documentation

The docs are part of the change. `just check` runs a docs test that fails when a link in a document does not resolve (checked offline), when a document names a specification ID that does not exist in `spec/`, when a method note's worked example differs from what the code gives, or when an example's report does not match its manifest.

- Changed a method or its numbers? Run `just notes` and read the diff of `docs/methods/`.
- Changed anything the examples show? Run `just examples` (the demo takes about a minute; it rewrites `examples/demo/` and the report of every example) and read the diff. The tiny examples are refreshed together with the test fixtures by `just synth-fixtures`.
- Changed a report page or a number in the report? Run `just golden` and read its diff as well.
- Update `CHANGELOG.md` for anything a user would notice.

## Handover

[HANDOVER.md](HANDOVER.md) is the only status document: what is done, what is next, what was not verified. Update its State and Next lines and add one Log line when you finish an item; detail belongs in commit messages and decision records, not in extra report files.
