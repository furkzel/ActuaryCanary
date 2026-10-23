set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

setup:
    uv sync
    uv run pre-commit install

fmt:
    uv run ruff format .

lint:
    uv run ruff check .

types:
    uv run pyright

test:
    uv run pytest -m "not slow" -n auto -q

test-all:
    uv run pytest -n auto -q

check:
    uv run ruff format --check .
    uv run ruff check .
    uv run pyright
    uv run pytest -m "not slow" -n auto -q

run *args:
    uv run canary {{args}}

spec-index:
    uv run python -m actuarycanary.spec

# write a synthetic scenario with ground truth, e.g. `just synth baseline tiny`
synth scenario="baseline" size="tiny":
    uv run python -m actuarycanary.synthetic write {{scenario}} {{size}}

# refresh the committed tiny fixtures and examples
synth-fixtures:
    uv run python -m actuarycanary.synthetic fixtures

# time the pipeline on a folder, cold (empty reader cache) and warm, with the time of each step
bench folder="data/synthetic/baseline/medium":
    uv run python -m actuarycanary.bench {{folder}}

# rewrite the golden copy of the report numbers after an intended change, then review its diff
golden $ACTUARYCANARY_UPDATE_GOLDEN="1":
    uv run pytest tests/report/test_golden.py -q
