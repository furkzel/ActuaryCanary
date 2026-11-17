"""Reference tables (records 0443, 0444): the format, every check, q and mu, the hashes in the
manifest and in the run id, the generator's two synthetic tables, and no table in the package."""

import hashlib
import json
import math
from pathlib import Path

import polars as pl
import pytest

import actuarycanary
from actuarycanary.life.tables import FOLDER, read_table, read_tables, to_force, to_probability
from actuarycanary.manifest.run import run_id, write_manifest

SIDECAR = "name: Test table\ndecrement: DEATH\nsource: built in code\nlicence: CC0\n"
FIVE_AGES = (
    "age,rate_kind,rate\n40,q,0.001\n41,q,0.0011\n42,q,0.00121\n43,q,0.00133\n44,q,0.00146\n"
)


def _write(folder: Path, name: str, csv: str, sidecar: str | None = SIDECAR) -> Path:
    tables = folder / FOLDER
    tables.mkdir(parents=True, exist_ok=True)
    path = tables / f"{name}.csv"
    path.write_text(csv, encoding="utf-8")
    if sidecar is not None:
        (tables / f"{name}.yaml").write_text(sidecar, encoding="utf-8")
    return path


def test_a_valid_table_is_read_with_its_metadata_and_hash(tmp_path: Path) -> None:
    path = _write(tmp_path, "mortality", FIVE_AGES)
    table, problems = read_table(path)
    assert problems == [] and table is not None
    assert (table.name, table.decrement, table.key, table.rate_kind) == (
        "Test table",
        "DEATH",
        "age",
        "q",
    )
    assert (table.source, table.licence, table.rows) == ("built in code", "CC0", 5)
    assert table.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert table.frame["age"].to_list() == [40, 41, 42, 43, 44]


def test_the_rate_kind_may_be_given_in_the_sidecar(tmp_path: Path) -> None:
    csv = "policy_year,rate\n1,0.1\n2,0.08\n"
    table, problems = read_table(_write(tmp_path, "lapse", csv, SIDECAR + "rate_kind: q\n"))
    assert problems == [] and table is not None and table.key == "policy_year"


@pytest.mark.parametrize(
    ("csv", "sidecar", "reason"),
    [
        (FIVE_AGES, None, "no sidecar mortality.yaml"),
        (FIVE_AGES, "name: x\ndecrement: DEATH\nsource: s\n", "mortality.yaml has no licence"),
        (FIVE_AGES, SIDECAR.replace("DEATH", "FIRE"), "decrement FIRE is not one of"),
        (FIVE_AGES, "- a list\n", "is not a mapping"),
        ("age,rate\n40,0.1\n", SIDECAR, "rate_kind (none) is not q, mu or m"),
        ("age,rate_kind,rate\n40,q,0.1\n41,mu,0.1\n", SIDECAR, "one value for the whole file"),
        ("age,rate_kind,rate\n40,x,0.1\n", SIDECAR, "rate_kind x is not q, mu or m"),
        ("rate_kind,rate\nq,0.1\n", SIDECAR, "exactly one key column"),
        ("age,policy_year,rate_kind,rate\n1,1,q,0.1\n", SIDECAR, "exactly one key column"),
        ("age,rate_kind\n40,q\n", SIDECAR, "no rate column"),
        ("age,rate_kind,rate\n40.5,q,0.1\n", SIDECAR, "fractional"),
        ("age,rate_kind,rate\n121,q,0.1\n", SIDECAR, "age outside 0 to 120"),
        ("age,rate_kind,rate\n40,q,1.0\n", SIDECAR, "outside 0 <= q < 1"),
        ("age,rate_kind,rate\n40,q,-0.1\n", SIDECAR, "outside 0 <= q < 1"),
        ("age,rate_kind,rate\n40,mu,-0.1\n", SIDECAR, "a mu is negative"),
        ("age,rate_kind,rate\n40,q,\n", SIDECAR, "rates are empty"),
        ("age,rate_kind,rate\n40,q,0.1\n40,q,0.2\n", SIDECAR, "age repeat"),
        ("age,rate_kind,rate\n40,q,0.1\n42,q,0.2\n", SIDECAR, "gaps"),
        ("age,sex,rate_kind,rate\n40,F,q,0.1\n", SIDECAR, "sex is not FEMALE or MALE"),
        ("age,rate_kind,rate\n", SIDECAR, "no rows"),
    ],
)
def test_a_table_that_fails_a_check_is_not_used(tmp_path, csv, sidecar, reason) -> None:
    table, problems = read_table(_write(tmp_path, "mortality", csv, sidecar))
    assert table is None
    assert any(reason in p for p in problems), problems


def test_groups_are_checked_for_gaps_apart(tmp_path: Path) -> None:
    csv = "age,sex,rate_kind,rate\n40,FEMALE,q,0.1\n41,FEMALE,q,0.1\n45,MALE,q,0.1\n46,MALE,q,0.1\n"
    table, problems = read_table(_write(tmp_path, "mortality", csv))
    assert problems == [] and table is not None and table.groups == ("sex",)


def test_q_mu_and_back() -> None:
    q = pl.Series("rate", [0.0, 0.001, 0.5, 0.9])
    mu = to_force(q, "q")
    assert mu.to_list() == pytest.approx([0.0, -math.log(0.999), math.log(2.0), math.log(10.0)])
    assert to_probability(mu, "mu").to_list() == pytest.approx(q.to_list(), abs=1e-15)
    m = pl.Series("rate", [0.02])
    assert to_force(m, "m").to_list() == [0.02]  # m is taken as mu (CV11)
    assert to_probability(q, "q").to_list() == q.to_list()


def test_the_folder_lists_tables_used_and_not_used(tmp_path: Path) -> None:
    _write(tmp_path, "a_mortality", FIVE_AGES)
    _write(tmp_path, "b_broken", FIVE_AGES, sidecar=None)
    read = read_tables(tmp_path)
    assert [t.file for t in read.used] == ["a_mortality.csv"]
    assert read.not_used == (
        ("b_broken.csv", "no sidecar b_broken.yaml (name, decrement, source, licence)"),
    )
    record = read.manifest_record()
    assert record["used"][0]["file"] == "reference_tables/a_mortality.csv"
    assert record["used"][0]["sha256"] == read.used[0].sha256
    assert record["not_used"][0]["file"] == "reference_tables/b_broken.csv"
    assert read_tables(tmp_path / "nothing").found is False


def _manifest(out: Path, tables: dict | None) -> Path:
    return write_manifest(
        out,
        run="r",
        package_version="1",
        inputs=[],
        specs=[],
        settings={},
        outputs=[],
        findings=[],
        reference_tables=tables,
    )


def test_the_hashes_enter_the_manifest_and_the_run_id(tmp_path: Path) -> None:
    _write(tmp_path, "mortality", FIVE_AGES)
    read = read_tables(tmp_path)
    base = run_id([], [], {}, "1", [])
    with_table = run_id([], [], {}, "1", [read.run_id_record()])
    assert with_table != base
    _write(tmp_path, "mortality", FIVE_AGES.replace("0.001\n", "0.002\n"))
    assert run_id([], [], {}, "1", [read_tables(tmp_path).run_id_record()]) != with_table
    out = tmp_path / "run"
    out.mkdir()
    written = json.loads(_manifest(out, read.manifest_record()).read_text())
    assert written["reference_tables"]["used"][0]["sha256"] == read.used[0].sha256
    # a run without tables writes the manifest it wrote before: no key at all
    assert "reference_tables" not in json.loads(_manifest(out, None).read_text())


def test_a_run_without_tables_has_no_reference_tables_in_its_manifest(default_run) -> None:
    manifest = json.loads(default_run.manifest.read_text(encoding="utf-8"))
    assert "reference_tables" not in manifest
    assert all(m.get("concept") != FOLDER for m in manifest["mapping_profiles"])


def test_the_generator_tables_are_read_with_a_sidecar_beside_them(
    scenario_folder, tmp_path
) -> None:
    """The generator writes `reference_mortality.csv` (age, rate_kind q, rate) and
    `reference_lapse.csv` (product, policy_year, rate) without sidecars (it does not change in
    L1a): read as they are, they are not used; with a sidecar each is a valid table."""
    source = scenario_folder("life_book") / FOLDER
    plain = read_tables(source.parent)
    assert plain.used == () and {f for f, _ in plain.not_used} == {
        "reference_lapse.csv",
        "reference_mortality.csv",
    }
    tables = tmp_path / FOLDER
    tables.mkdir()
    for name in ("reference_mortality", "reference_lapse"):
        (tables / f"{name}.csv").write_bytes((source / f"{name}.csv").read_bytes())
    (tables / "reference_mortality.yaml").write_text(SIDECAR)
    lapse = SIDECAR.replace("DEATH", "LAPSE") + "rate_kind: q\n"
    (tables / "reference_lapse.yaml").write_text(lapse)
    read = read_tables(tmp_path)
    assert read.not_used == ()
    mortality, lapse_table = sorted(read.used, key=lambda t: t.decrement)
    assert (mortality.key, mortality.groups, mortality.rows) == (
        "age",
        (),
        111,
    )  # ages 0 to 110 (table_max_age)
    assert (lapse_table.key, lapse_table.groups) == ("policy_year", ("product",))


def test_no_reference_table_ships_with_the_package() -> None:
    package = Path(actuarycanary.__file__).parent
    shipped = [p for p in package.rglob("*") if p.suffix.lower() in (".csv", ".parquet")]
    assert [p for p in shipped if FOLDER in p.parts or "mortal" in p.name.lower()] == []
