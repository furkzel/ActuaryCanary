# Contributing

- Read [HANDOVER.md](HANDOVER.md) first; it is the only status document.
- Specification first: change `spec/` before code. One rule lives in one spec file, and tests name the spec ID they prove.
- Write one numbered decision record in `docs/decisions/` for every real choice. Records are superseded, never edited.
- Work on a branch named `s/<ID>-<slug>` and open a pull request; the owner merges. Never push to `main`.
- Code, comments, commits and documents are in English. Use synthetic data only; never commit personal data.
- Run `just check` before pushing. The fast suite must stay under 30 seconds and each fast test under 0.5 s; mark slower tests `@pytest.mark.slow`.
- Build test fixtures in code. Only reader tests open spreadsheets.
- Add no dependency without a decision record and approval.
- Say "verified" only for what you ran; otherwise write UNVERIFIED.
