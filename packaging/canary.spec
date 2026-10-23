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
    (str(root / "examples" / "baseline"), "examples/baseline"),
]
if (root / "examples" / "demo").is_dir():  # created by the documentation item
    datas.append((str(root / "examples" / "demo"), "examples/demo"))
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
