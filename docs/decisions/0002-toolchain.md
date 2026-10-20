# 0002 — Toolchain

## Context
The blueprint (section 14.2) fixes a Python reference implementation. One agreed set of libraries keeps later work items consistent.

## Decision
Python 3.12 with uv for environments and locking. Runtime libraries:
- polars: fast columnar dataframes; fastexcel (calamine engine) reads Excel, xlsxwriter writes it.
- duckdb: embedded analytical database for large joins and aggregations, no server.
- numpy, scipy: numerical work and statistical distributions.
- scikit-learn: regression, clustering and anomaly detection for the methods library.
- rapidfuzz: fuzzy matching of column names against the alias dictionary.
- pydantic, pyyaml: validated configuration and specification files.
- typer, rich: command line and terminal tables.
- jinja2, plotly: report page and interactive charts.

Development: pytest, pytest-xdist, hypothesis, ruff (format and lint), pyright (basic), pre-commit, just. chainladder is a test-only reference for benchmark comparisons. types-pyyaml supplies type stubs.

## Consequences
- fastexcel and xlsxwriter are required companions of polars' Excel support, not extra choices.
- Adding any other library needs a new decision record and the owner's approval.
- chainladder never appears in runtime code.
