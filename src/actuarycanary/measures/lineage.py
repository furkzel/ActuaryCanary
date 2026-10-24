"""The two lineage formats of a run and the conversion between them (decision 0222).

Format 1 is `lineage.csv` alone: one line per value, file and sheet, with the spreadsheet
rows behind it as ranges (`2-40;45`). Many values stand on nearly the same rows, so on a
large input the file reaches hundreds of megabytes.

Format 2 splits the rows from the values. A row of a source sheet belongs to the same values
whatever else is true of it, so the rows are cut into *atoms*: the sets of rows of one file
and sheet that are cited by exactly the same values. `lineage_atoms.csv` lists each atom once
with its row ranges; `lineage.csv` names, per value, the atoms (as ranges of atom numbers)
whose union is its rows. Nothing is lost: `to_format1` rebuilds format 1 line for line.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from actuarycanary.measures.model import MeasureInputs, MeasureResult
from actuarycanary.measures.output import LINEAGE_COLUMNS, UNIT, _ranges, lineage_units

FORMAT_1 = 1
FORMAT_2 = 2
FORMATS = (FORMAT_1, FORMAT_2)
DEFAULT_FORMAT = FORMAT_2
LINEAGE_NAME = "lineage.csv"
ATOMS_NAME = "lineage_atoms.csv"
VALUE_KEYS = ("measure", "version", "view", "row", "concept")
LINEAGE_COLUMNS_2 = (*VALUE_KEYS, "atoms", "count")
ATOM_COLUMNS = ("atom", "concept", "file", "sheet", "rows", "count")


@dataclass(frozen=True)
class Lineage:
    """The lineage of a run in one of the formats; `atoms` is None in format 1."""

    format: int
    values: pl.DataFrame
    atoms: pl.DataFrame | None = None

    def files(self) -> dict[str, str]:
        """File name -> CSV text, in the order they are written."""
        files = {LINEAGE_NAME: self.values.write_csv()}
        if self.atoms is not None:
            files[ATOMS_NAME] = self.atoms.write_csv()
        return files

    def summary(self) -> dict[str, int]:
        """What the report says about the lineage, the same for either format: the number of
        values traced to rows and of source rows cited (a row cited twice counts twice)."""
        cited = self.values["count"].cast(pl.Int64).sum() if self.values.height else 0
        return {
            "format": self.format,
            "traced_values": self.values.select(*VALUE_KEYS[:3], "row").unique().height,
            "lines": self.values.height,
            "rows_cited": int(cited),
        }


def _empty_1() -> pl.DataFrame:
    return pl.DataFrame(schema={c: pl.String for c in LINEAGE_COLUMNS})


def _empty_2() -> Lineage:
    return Lineage(
        FORMAT_2,
        pl.DataFrame(schema={c: pl.String for c in LINEAGE_COLUMNS_2}),
        pl.DataFrame(schema={c: pl.String for c in ATOM_COLUMNS}),
    )


def build_lineage(
    results: Sequence[MeasureResult], inputs: MeasureInputs, format: int = DEFAULT_FORMAT
) -> Lineage:
    """The lineage of `results` in `format`."""
    if format not in FORMATS:
        raise ValueError(f"unknown lineage format {format}; known: {', '.join(map(str, FORMATS))}")
    units = lineage_units(results, inputs)
    if format == FORMAT_1:
        return Lineage(FORMAT_1, units.drop(UNIT))
    return _atomise(units)


def _row_runs(parts: pl.DataFrame) -> pl.DataFrame:
    """Every spreadsheet row of the range strings of `parts` (columns `part`, `rows`)."""
    runs = (
        parts.select("part", pl.col("rows").str.split(";").alias("run"))
        .explode("run")
        .with_columns(pl.col("run").str.split("-").alias("ends"))
    )
    return runs.select(
        "part",
        pl.int_ranges(
            pl.col("ends").list.first().cast(pl.Int32),
            pl.col("ends").list.last().cast(pl.Int32) + 1,
            dtype=pl.Int32,
        ).alias("row"),
    ).explode("row")


def _atomise(units: pl.DataFrame) -> Lineage:
    """Format 1 lines (with their unit) as format 2."""
    if units.height == 0:
        return _empty_2()
    block_keys = ["concept", "file", "sheet"]
    # a part is one distinct row set of one file and sheet, as format 1 writes it
    parts = (
        units.select(*block_keys, "rows")
        .unique()
        .sort(*block_keys, "rows", nulls_last=False)
        .with_row_index("part")
        .with_columns(pl.col("part").cast(pl.Int32))
    )
    atom_tables: list[pl.DataFrame] = []
    part_atoms: list[pl.DataFrame] = []
    first_atom = 0
    for block in parts.partition_by(block_keys, maintain_order=True):
        pairs = _row_runs(block)
        # the atom of a row: the parts that contain it, written out so that equal sets compare equal
        signature = pairs.group_by("row").agg(
            pl.col("part").sort().cast(pl.String).str.join(",").alias("signature")
        )
        atoms = (
            signature.group_by("signature")
            .agg(pl.col("row").min().alias("first"))
            .sort("first")
            .with_row_index("local")
        )
        numbered = signature.join(atoms.select("signature", "local"), on="signature")
        ranges = _ranges(
            numbered.select(pl.col("local"), pl.col("row").cast(pl.Int64).alias("source_row")),
            ["local"],
        )
        head = block.row(0, named=True)
        atom_tables.append(
            ranges.select(
                (pl.col("local").cast(pl.Int64) + first_atom).alias("atom"),
                pl.lit(head["concept"]).alias("concept"),
                pl.lit(head["file"]).alias("file"),
                pl.lit(head["sheet"]).alias("sheet"),
                "rows",
                "count",
            )
        )
        part_atoms.append(
            atoms.select((pl.col("local").cast(pl.Int64) + first_atom).alias("atom"), "signature")
            .with_columns(pl.col("signature").str.split(","))
            .explode("signature")
            .select(pl.col("signature").cast(pl.Int32).alias("part"), "atom")
        )
        first_atom += atoms.height
    atom_table = pl.concat(atom_tables)
    # the atoms of every part, then of every value (the union over its files and sheets)
    cited = units.join(parts, on=[*block_keys, "rows"], how="left", nulls_equal=True).join(
        pl.concat(part_atoms), on="part"
    )
    keys = [UNIT, "row"]
    per_value = _ranges(
        cited.select(*keys, pl.col("atom").alias("source_row")).sort(*keys, "source_row"), keys
    ).rename({"rows": "atoms"})
    meta = (
        units.group_by(keys, maintain_order=True)
        .agg(
            *[pl.col(c).first() for c in VALUE_KEYS if c != "row"],
            pl.col("count").cast(pl.Int64).sum().alias("count"),
        )
        .select(*keys, "measure", "version", "view", "concept", "count")
    )
    values = meta.join(per_value.drop("count"), on=keys, how="left").select(
        *VALUE_KEYS, "atoms", "count"
    )
    return Lineage(FORMAT_2, values, atom_table.select(*ATOM_COLUMNS))


def to_format1(lineage: Lineage) -> pl.DataFrame:
    """The format 1 table of `lineage`; for format 2, rebuilt from the atoms."""
    if lineage.format == FORMAT_1 or lineage.atoms is None:
        return lineage.values
    values = lineage.values.with_row_index("line")
    if values.height == 0:
        return _empty_1()
    atoms = lineage.atoms.with_columns(pl.col("atom").cast(pl.Int64))
    members = (
        values.select("line", pl.col("atoms").str.split(";").alias("run"))
        .explode("run")
        .with_columns(pl.col("run").str.split("-").alias("ends"))
        .select(
            "line",
            pl.int_ranges(
                pl.col("ends").list.first().cast(pl.Int64),
                pl.col("ends").list.last().cast(pl.Int64) + 1,
            ).alias("atom"),
        )
        .explode("atom")
    )
    cited = (
        members.join(atoms.select("atom", "file", "sheet", "rows"), on="atom")
        .select("line", "file", "sheet", pl.col("rows").str.split(";").alias("run"))
        .explode("run")
        .with_columns(pl.col("run").str.split("-").alias("ends"))
        .select(
            "line",
            "file",
            "sheet",
            pl.int_ranges(
                pl.col("ends").list.first().cast(pl.Int64),
                pl.col("ends").list.last().cast(pl.Int64) + 1,
            ).alias("source_row"),
        )
        .explode("source_row")
    )
    rebuilt = _ranges(cited, ["line", "file", "sheet"])
    return (
        rebuilt.join(values.select("line", *VALUE_KEYS), on="line")
        .sort("line", "file", "sheet", nulls_last=False)
        .select(*LINEAGE_COLUMNS)
    )


def read_lineage(folder: Path) -> Lineage:
    """The lineage files of a run folder, in whichever format they are (`lineage_atoms.csv`
    is there in format 2 only)."""
    values = pl.read_csv(folder / LINEAGE_NAME, infer_schema_length=0)
    atoms_path = folder / ATOMS_NAME
    if atoms_path.exists():
        return Lineage(FORMAT_2, values, pl.read_csv(atoms_path, infer_schema_length=0))
    return Lineage(FORMAT_1, values)
