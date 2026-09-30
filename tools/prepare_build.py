"""Build inputs for PyInstaller (python tools/prepare_build.py), written to build/:

- icon.png / icon.ico / icon.icns, drawn from the same glyph as the tray icon;
- duckdb_extensions.zip: the httpfs extension for this platform, so the packaged
  app never has to download it on the user's machine. Zipped so PyInstaller does
  not re-sign it (that would break DuckDB's own signature on the file).
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from ticketdepot.__main__ import tray_image  # noqa: E402

BUILD = ROOT / "build"


def icons() -> None:
    BUILD.mkdir(exist_ok=True)
    img = tray_image(1024)
    img.save(BUILD / "icon.png")
    img.save(BUILD / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(BUILD / "icon.icns")


def duckdb_extensions() -> None:
    target = BUILD / "duckdb_extensions"
    con = duckdb.connect(config={"extension_directory": str(target)})
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")  # proves the bundled copy loads
    files = list(target.rglob("*.duckdb_extension"))
    assert files, "httpfs was not installed"
    with zipfile.ZipFile(BUILD / "duckdb_extensions.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(target))
    print("httpfs:", *files)


if __name__ == "__main__":
    icons()
    duckdb_extensions()
