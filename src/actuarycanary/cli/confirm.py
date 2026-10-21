"""Terminal confirmation of recognised sheets: one table per sheet; accept, edit or skip.

Edits are typed as short commands: ``3=claim_id`` maps column 3 to a field, ``3=-`` leaves
column 3 unused, ``concept=claims`` maps the sheet again as another concept, ``concept=-``
skips the sheet. An empty line ends editing.
"""

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table

from actuarycanary.io.excel import RawTable
from actuarycanary.recognition.columns import Layer
from actuarycanary.recognition.dictionary import Dictionary
from actuarycanary.recognition.tables import TableRecognition, with_concept, with_field

_LAYER_STYLE = {
    Layer.CANONICAL: "green",
    Layer.DICTIONARY: "green",
    Layer.FUZZY: "yellow",
    Layer.VALUES: "yellow",
    Layer.SAVED: "green",
    Layer.USER: "cyan",
    Layer.PERSONAL: "magenta",
    Layer.NONE: "dim",
}


def mapping_table(rec: TableRecognition) -> Table:
    title = f"{escape(rec.label)}, header row {rec.header_row}"
    if rec.rows_above:
        title += f" ({rec.rows_above} row(s) above skipped)"
    table = Table(title=title, title_justify="left", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("Source column", overflow="fold")
    table.add_column("Canonical field", overflow="fold")
    table.add_column("Layer")
    table.add_column("Conf.", justify="right")
    table.add_column("Evidence", overflow="fold")
    for n, m in enumerate(rec.mappings, start=1):
        target = f"dropped: personal ({m.personal})" if m.personal else m.field or "-"
        style = _LAYER_STYLE[m.layer]
        table.add_row(
            str(n),
            escape(repr(m.source)),
            escape(target),
            f"[{style}]{m.layer}[/{style}]",
            f"{m.confidence:.2f}" if m.field else "",
            escape(m.evidence),
        )
    return table


def _describe(rec: TableRecognition, dictionary: Dictionary) -> list[str]:
    lines: list[str] = []
    chosen = next((c for c in rec.candidates if c.concept == rec.concept), None)
    concept = rec.concept or "none (sheet skipped)"
    lines.append(
        f"Concept: [bold]{concept}[/bold]" + (f", {escape(chosen.detail())}" if chosen else "")
    )
    others = [c for c in rec.candidates if c.concept != rec.concept]
    if others:
        lines.append("Other candidates: " + escape("; ".join(c.describe() for c in others)))
    missing = rec.missing(dictionary)
    if missing:
        lines.append(f"[red]Required fields not found: {', '.join(missing)}[/red]")
    return lines


def show(console: Console, rec: TableRecognition, dictionary: Dictionary) -> None:
    console.print(mapping_table(rec))
    for line in _describe(rec, dictionary):
        console.print(line, soft_wrap=True)


def _edit(
    console: Console, rec: TableRecognition, table: RawTable, dictionary: Dictionary
) -> TableRecognition:
    fields = (
        ", ".join(f.name for f in dictionary.concepts[rec.concept].fields) if rec.concept else ""
    )
    console.print(
        "Edit: [bold]n=field[/bold] maps column n, [bold]n=-[/bold] leaves it unused, "
        "[bold]concept=name[/bold] or [bold]concept=-[/bold]; empty line to finish."
    )
    while True:
        if rec.concept:
            console.print(f"Fields of {rec.concept}: {fields}", soft_wrap=True)
        command = Prompt.ask("Change", default="", show_default=False, console=console).strip()
        if not command:
            return rec
        key, _, value = command.partition("=")
        key, value = key.strip(), value.strip()
        try:
            if key == "concept":
                rec = with_concept(rec, None if value in ("", "-") else value, table, dictionary)
                fields = (
                    ", ".join(f.name for f in dictionary.concepts[rec.concept].fields)
                    if rec.concept
                    else ""
                )
            elif key.isdigit() and 1 <= int(key) <= len(rec.headers):
                header = rec.mappings[int(key) - 1].source
                rec = with_field(rec, header, None if value in ("", "-") else value, dictionary)
            else:
                console.print(f"[red]Not understood: {escape(repr(command))}[/red]")
                continue
        except ValueError as error:
            console.print(f"[red]{escape(str(error))}[/red]")
            continue
        show(console, rec, dictionary)


def confirm_tables(
    console: Console, pending: list[tuple[TableRecognition, RawTable]], dictionary: Dictionary
) -> list[TableRecognition]:
    """Ask about each sheet; return it accepted, edited or skipped (concept None)."""
    console.print(
        f"[bold]{len(pending)} sheet(s) have a layout without a saved mapping profile.[/bold] "
        "Confirmed mappings are saved and reused without asking."
    )
    answers: list[TableRecognition] = []
    for rec, table in pending:
        show(console, rec, dictionary)
        choice = Prompt.ask(
            "Accept, edit or skip", choices=["a", "e", "s"], default="a", console=console
        )
        if choice == "e":
            rec = _edit(console, rec, table, dictionary)
        elif choice == "s":
            rec = with_concept(rec, None, table, dictionary)
        answers.append(rec)
    return answers
