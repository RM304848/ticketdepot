# Third-party notices

Ticketdepot is licensed under the GNU Affero General Public License v3.0 (see `LICENSE`).
The released binaries bundle the following components.

| Component | License | Source |
|---|---|---|
| PyMuPDF | GNU AGPL-3.0 | https://github.com/pymupdf/PyMuPDF |
| DuckDB (incl. the `httpfs` extension) | MIT | https://github.com/duckdb/duckdb |
| pypdf | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| truststore | MIT | https://github.com/sethmlarson/truststore |
| tzdata | Apache-2.0 | https://github.com/python/tzdata |
| Pillow | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| PyObjC (macOS, via pystray) | MIT | https://github.com/ronaldoussoren/pyobjc |
| six (via pystray) | MIT | https://github.com/benjaminp/six |
| CPython | PSF License | https://www.python.org |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | https://github.com/pyinstaller/pyinstaller |

pystray is loaded as a separate, replaceable Python module; its source and the full
source of this app are available in this repository, so the LGPL relinking terms are met.

## Data

- Delay data: DB IRIS timetable data from the dataset
  [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data),
  licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Only the
  trains of the user's own tickets are queried; results are stored locally.
- `ticketdepot/data/eva_to_station_name.json` is taken from the same dataset
  (`config/eva_to_station_name.json`), CC BY 4.0.

## Credits

The approach of reading historical delays from the dataset above follows the open-source
app [delay_bahn](https://github.com/sha2nkt/delay_bahn). No code from delay_bahn is included.

Ticketdepot is not affiliated with or endorsed by Deutsche Bahn AG. Rules are linked to
their official explanations on bahn.de; DB's decision is binding.
