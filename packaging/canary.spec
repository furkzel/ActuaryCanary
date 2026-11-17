# PyInstaller specification: one-folder build of the command-line program (decision 0090).
# Build from the repository root: `uv run pyinstaller packaging/canary.spec --noconfirm`.
# Everything the program reads at run time sits at the root of the bundle, where the lookups that
# walk up from their own file find it: project.yaml, spec/, synthetic/scenarios/, examples/.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is set by PyInstaller)

datas = [
    (str(root / "project.yaml"), "."),
    (str(root / "spec"), "spec"),
    (str(root / "synthetic" / "scenarios"), "synthetic/scenarios"),
]
# `canary demo` runs on examples/demo: its workbooks, not the example report beside them
demo_workbooks = sorted((root / "examples" / "demo").glob("*.xlsx"))
if not demo_workbooks:
    raise SystemExit("examples/demo has no workbooks: the program would have no demo data")
datas += [(str(workbook), "examples/demo") for workbook in demo_workbooks]
# the demo's confirmed ledger account-mapping profile lies beside its example report; the demo
# copies it into the profiles folder of the run, so that the program gives the run id of the
# committed report (records 0812 and 0816). Without it the program would propose the profile.
demo_profiles = sorted((root / "examples" / "demo" / "report").glob("ledger-*.yaml"))
if not demo_profiles:
    raise SystemExit("examples/demo/report has no ledger profile: the demo would only propose one")
datas += [(str(profile), "examples/demo/report") for profile in demo_profiles]
datas += collect_data_files("actuarycanary")  # report templates
datas += [(str(Path(__import__("plotly").__file__).parent / "package_data" / "plotly.min.js"),
           "plotly/package_data")]

analysis = Analysis(  # noqa: F821
    [str(root / "packaging" / "canary_entry.py")],
    pathex=[str(root / "src")],
    datas=datas,
    hiddenimports=["fastexcel"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "chainladder", "pandas", "numba", "llvmlite", "PIL", "sparse"],
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="canary",
    console=True,
)
COLLECT(exe, analysis.binaries, analysis.datas, name="canary")  # noqa: F821
