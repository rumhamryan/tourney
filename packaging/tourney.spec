# Build with scripts/build_windows.ps1 on Windows x64.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

project_root = Path(SPECPATH).parent
# Keep OR-Tools' dynamically loaded .libs DLLs in their package directory.
# Its Python imports are discovered normally, without collecting unused solvers.
solver_data = collect_data_files("ortools")
solver_binaries = collect_dynamic_libs("ortools")

analysis = Analysis(
    [str(project_root / "src" / "main_menu.py")],
    pathex=[str(project_root / "src")],
    binaries=solver_binaries,
    datas=solver_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="Tourney",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
)
