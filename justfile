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
