"""Print the specification index: every spec ID, its titles and status, read from spec/."""

import sys

from rich.console import Console
from rich.table import Table

from actuarycanary.spec.loader import index_rows, load_specs


def main() -> None:
    rows = index_rows(load_specs())
    table = Table(title=f"Specifications ({len(rows)})")
    for column in ("Kind", "ID", "Version", "Status"):
        table.add_column(column, no_wrap=True)
    for column in ("Title", "Başlık"):
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    # Turkish titles need UTF-8; legacy Windows code pages cannot encode them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    console = Console(legacy_windows=False)
    if not console.is_terminal:
        console.width = 160  # piped output: keep titles whole
    console.print(table)


if __name__ == "__main__":
    main()
