# PyInstaller spec, built natively on each OS (run tools/prepare_build.py first):
#   pyinstaller packaging/ticketdepot.spec                  -> macOS: dist/Ticketdepot.app
#   BT_ONEFILE=1 pyinstaller packaging/ticketdepot.spec     -> Windows: dist/Ticketdepot.exe
#   pyinstaller packaging/ticketdepot.spec                  -> Windows: dist/Ticketdepot/ (zip fallback)
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from ticketdepot import __version__  # noqa: E402

ONEFILE = os.environ.get("BT_ONEFILE") == "1"
MAC = sys.platform == "darwin"
ICON = str(ROOT / "build" / ("icon.icns" if MAC else "icon.ico"))

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "ticketdepot" / "ui"), "ticketdepot/ui"),
        (str(ROOT / "ticketdepot" / "data"), "ticketdepot/data"),
        (str(ROOT / "build" / "duckdb_extensions.zip"), "."),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    ],
    hiddenimports=["pystray._darwin" if MAC else "pystray._win32"],
    excludes=["tkinter", "webview", "pytest"],
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Ticketdepot", icon=ICON, console=False, upx=False)
else:
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name="Ticketdepot", icon=ICON, console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="Ticketdepot", upx=False)
    if MAC:
        app = BUNDLE(
            coll,
            name="Ticketdepot.app",
            icon=ICON,
            bundle_identifier="local.ticketdepot.app",
            version=__version__,
            info_plist={
                "CFBundleShortVersionString": __version__,
                "CFBundleVersion": __version__,
                "LSUIElement": True,  # lives in the menu bar, no Dock icon
                "NSHumanReadableCopyright": "AGPL-3.0",
            },
        )
