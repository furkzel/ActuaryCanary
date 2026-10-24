"""The documentation stays true: links resolve without a network, spec IDs exist, the worked
examples of the method notes are what the code gives today, and the examples hold together.

Run alone with `just docs-check`; it is part of `just check` through the fast suite.
"""

import functools
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from actuarycanary.spec.loader import find_spec_root
from docs.tools import worked_examples

ROOT = find_spec_root().parent
LINKED = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    *sorted((ROOT / "docs").rglob("*.md")),
]
# files whose mentions of spec IDs must exist in spec/ (decision records and the blueprint
# describe history and plans, so they may name IDs that were never built)
IDENTIFIED = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "guide.md",
    *sorted((ROOT / "docs" / "methods").glob("*.md")),
]
FENCE = re.compile(r"^(```|~~~).*?^\1", re.DOTALL | re.MULTILINE)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
SPEC_ID = re.compile(
    r"(?<![\w-])(?:(?:MT|CL|PR|EX|RC|RI|RS|RT|AE|DQ|CV|RP|KF|AL)\d{2}|M\d{2}|DV-[A-Z]{3}-\d{2})"
    r"(?![\w-])"
)
EXAMPLES = ["baseline", "messy_headers", "demo"]
FEEDS = ["claim_valuations", "claims", "policies", "premiums", "expenses", "market"]


def prose(path: Path) -> str:
    """The text of a document without fenced code, where links and IDs are not claims."""
    return FENCE.sub("", path.read_text(encoding="utf-8"))


def anchors(path: Path) -> set[str]:
    """The heading anchors GitHub makes: lower case, punctuation dropped, spaces to hyphens."""
    found: set[str] = set()
    for heading in HEADING.findall(prose(path)):
        text = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
        found.add(re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text)))
    return found


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("document", LINKED, ids=relative)
def test_every_link_resolves(document: Path) -> None:
    problems: list[str] = []
    for target in LINK.findall(prose(document)):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):  # http, https, mailto: not followed offline
            continue
        file_part, _, fragment = target.partition("#")
        resolved = document if not file_part else (document.parent / file_part).resolve()
        if not resolved.exists():
            problems.append(f"{target}: the file is missing")
        elif fragment and resolved.suffix == ".md" and fragment not in anchors(resolved):
            problems.append(f"{target}: no heading with the anchor #{fragment}")
    assert not problems, f"{relative(document)}: " + "; ".join(problems)


@functools.cache
def spec_ids() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "spec").rglob("*.yaml"):
        found |= set(re.findall(r"^\s*(?:-\s+)?id:\s*([\w-]+)\s*$", path.read_text("utf-8"), re.M))
    return found


def test_the_collection_of_spec_ids_finds_the_known_ones() -> None:
    known = spec_ids()
    assert {"MT02", "RP01", "KF01", "DV-CLV-15", "CV02", "M04", "AL01"} <= known


@pytest.mark.parametrize("document", IDENTIFIED, ids=relative)
def test_every_spec_id_mentioned_exists(document: Path) -> None:
    if not document.exists():
        pytest.skip("not written yet")
    missing = sorted({m for m in SPEC_ID.findall(prose(document)) if m not in spec_ids()})
    assert not missing, f"{relative(document)} names IDs that are not in spec/: {missing}"


@pytest.mark.parametrize("note", sorted(worked_examples.EXAMPLES))
def test_the_worked_example_is_what_the_code_gives(note: str) -> None:
    wanted = worked_examples.current(note)
    assert wanted is not None, f"{note}.md has no worked-example markers"
    stored = (ROOT / "docs" / "methods" / f"{note}.md").read_text(encoding="utf-8")
    assert stored == wanted, "run `just notes` and read the diff"


def test_every_tier_a_method_has_a_note() -> None:
    notes = {p.name for p in (ROOT / "docs" / "methods").glob("*.md")}
    for path in (ROOT / "spec" / "methods").glob("MT*.yaml"):
        if not yaml.safe_load(path.read_text(encoding="utf-8")).get("implemented", True):
            continue  # planned for a later version (decision 0200); its note comes when built
        assert f"{path.stem}.md" in notes, f"no note for {path.stem}"
    assert set(worked_examples.EXAMPLES) == {n.removesuffix(".md") for n in notes}


@pytest.mark.parametrize("example", EXAMPLES)
def test_an_example_has_its_six_files_and_a_report_that_matches_its_manifest(
    example: str,
) -> None:
    folder = ROOT / "examples" / example
    for feed in FEEDS:
        assert (folder / f"{feed}.xlsx").is_file(), f"{example}: {feed}.xlsx is missing"
    manifest = json.loads((folder / "report" / "manifest.json").read_text(encoding="utf-8"))
    report = (folder / "report" / "report.html").read_bytes()
    output = next(o for o in manifest["outputs"] if o["name"] == "report.html")
    assert hashlib.sha256(report).hexdigest() == output["sha256"]
    assert manifest["run_id"].encode() in report


def test_the_demo_shows_no_thin_evidence_and_the_tiny_example_does() -> None:
    """The demo has at least eight origin years (decision 0039); the four-year examples warn."""
    scenario = yaml.safe_load(
        (ROOT / "synthetic" / "scenarios" / "demo.yaml").read_text(encoding="utf-8")
    )
    assert scenario["extends"] == "baseline" and "demo" in scenario["sizes"]
    warning = "origin periods: thin evidence"
    demo = (ROOT / "examples" / "demo" / "report" / "report.html").read_text(encoding="utf-8")
    baseline = (ROOT / "examples" / "baseline" / "report" / "report.html").read_text("utf-8")
    assert warning not in demo
    assert warning in baseline


def test_the_licence_file_and_the_metadata_agree() -> None:
    metadata = yaml.safe_load((ROOT / "project.yaml").read_text(encoding="utf-8"))
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert metadata["licence"] == "MIT" and text.startswith("MIT License")
    assert "MIT" in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("example", EXAMPLES)
def test_the_guide_names_the_run_id_of_each_example(example: str) -> None:
    manifest = json.loads(
        (ROOT / "examples" / example / "report" / "manifest.json").read_text("utf-8")
    )
    guide = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    assert f"`{manifest['run_id']}`" in guide, f"update the run id of {example} in the guide"


CODE_SPAN = re.compile(r"`([^`\n]+)`")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
CANARY_COMMAND = re.compile(r"(?<![\w/.-])canary\s+([a-z][\w-]*)")
CLI_DOCUMENTS = [ROOT / "README.md", ROOT / "docs" / "guide.md"]


@functools.cache
def cli_options() -> dict[str, set[str]]:
    """The commands of the CLI and the long options of each, from the program itself."""
    from typer.main import get_command

    from actuarycanary.cli import app

    group = get_command(app)
    commands = getattr(group, "commands", {})
    return {
        name: {
            opt
            for param in command.params
            for opt in (*param.opts, *getattr(param, "secondary_opts", []))
            if opt.startswith("--")
        }
        for name, command in commands.items()
    }


def code_lines(path: Path) -> list[str]:
    """The lines of fenced code and the inline code spans: where a command is shown."""
    text = path.read_text(encoding="utf-8")
    fenced = [line for match in FENCE.finditer(text) for line in match.group(0).splitlines()]
    return fenced + CODE_SPAN.findall(FENCE.sub("", text))


def test_the_cli_collection_finds_the_known_commands_and_options() -> None:
    found = cli_options()
    assert {"run", "demo", "info"} <= set(found)
    assert {"--basis", "--yes", "--assumptions"} <= found["run"]
    assert {"--open", "--no-open", "--out"} <= found["demo"]


@pytest.mark.parametrize("document", CLI_DOCUMENTS, ids=relative)
def test_every_canary_command_the_documents_show_exists(document: Path) -> None:
    commands = cli_options()
    problems: list[str] = []
    for line in code_lines(document):
        for command in CANARY_COMMAND.findall(line):
            if command not in commands:
                problems.append(f"`{line.strip()}`: canary has no command {command}")
                continue
            unknown = [o for o in OPTION.findall(line) if o not in commands[command]]
            if unknown:
                problems.append(f"`{line.strip()}`: {command} has no option {unknown}")
    assert not problems, f"{relative(document)}: " + "; ".join(problems)


@pytest.mark.parametrize("document", CLI_DOCUMENTS, ids=relative)
def test_every_option_the_documents_mention_exists_in_the_cli(document: Path) -> None:
    known = {opt for options in cli_options().values() for opt in options} | {"--version", "--help"}
    mentioned = set(OPTION.findall(document.read_text(encoding="utf-8")))
    # options of other tools named in the text (for example `uv sync --group build`) go here
    other_tools = {"--group"}
    assert not (mentioned - known - other_tools), sorted(mentioned - known - other_tools)
