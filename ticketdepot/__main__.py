"""Start the app: local server on 127.0.0.1, the UI in the default browser, and a
tray / menu-bar icon to reopen or quit.

A second launch finds the running instance (fixed port 8775, or the port written
to the data folder when 8775 was taken) and just opens the browser to it.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8775  # fixed, so bookmarks and browser storage survive restarts


def main() -> None:
    parser = argparse.ArgumentParser(prog="ticketdepot")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="keinen Browser öffnen")
    parser.add_argument("--no-tray", action="store_true", help="ohne Tray-Symbol (Strg+C beendet)")
    parser.add_argument("--data", help="eigener Datenordner, z. B. testdaten/appdata für Testtickets")
    parser.add_argument("--import", dest="import_dir", help="beim Start alle PDFs aus diesem Ordner importieren")
    args = parser.parse_args()
    if args.data:
        os.environ["TICKETDEPOT_DATA"] = str(Path(args.data).resolve())

    from .store import data_dir

    port_file = data_dir() / "port"
    for port in dict.fromkeys((args.port, _read_port(port_file))):
        if port and _running(port):
            if not args.no_open:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            print(f"Ticketdepot läuft bereits auf http://127.0.0.1:{port}/")
            return

    from .api import Api
    from .server import Server

    api = Api()
    if args.import_dir:
        print(api.import_folder(args.import_dir)["message"])
    try:
        server = Server(api, args.port)
    except OSError:
        server = Server(api, 0)  # the fixed port is taken by something else
    port_file.write_text(str(server.port))
    print(f"Ticketdepot läuft auf {server.url}")
    if not args.no_open:
        webbrowser.open(server.url)

    try:
        if args.no_tray:
            raise RuntimeError("no tray")
        _run_with_tray(server)
    except (ImportError, RuntimeError, NotImplementedError, ValueError) as e:
        # no tray available (or not wanted): serve in the foreground until Ctrl+C
        if not args.no_tray:
            print(f"Kein Tray-Symbol ({e}); beenden mit Strg+C.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        server.server_close()
        if _read_port(port_file) == server.port:
            port_file.unlink(missing_ok=True)


def _run_with_tray(server) -> None:
    import pystray

    threading.Thread(target=server.serve_forever, daemon=True).start()

    def quit_app(*_):
        icon.stop()
        server.shutdown()

    server.on_quit = quit_app  # "Beenden" in the page does the same as in the tray menu
    icon = pystray.Icon(
        "Ticketdepot",
        tray_image(64),
        "Ticketdepot",
        menu=pystray.Menu(
            pystray.MenuItem("Öffnen", lambda: webbrowser.open(server.url), default=True),
            pystray.MenuItem("Beenden", quit_app),
        ),
    )
    icon.run()  # blocks; on macOS it has to own the main thread


def tray_image(size: int):
    """A ticket glyph on teal, drawn at runtime (also used for the app icons)."""
    from PIL import Image, ImageDraw

    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * s, 2 * s, 62 * s, 62 * s), radius=14 * s, fill=(0, 128, 128, 255))
    d.rounded_rectangle((12 * s, 20 * s, 52 * s, 44 * s), radius=4 * s, fill=(255, 255, 255, 255))
    for cx in (12 * s, 52 * s):  # the notches of a ticket
        d.ellipse((cx - 4 * s, 28 * s, cx + 4 * s, 36 * s), fill=(0, 128, 128, 255))
    d.line((38 * s, 22 * s, 38 * s, 42 * s), fill=(0, 128, 128, 255), width=max(1, round(2 * s)))
    return img


def _read_port(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as resp:
            return json.load(resp).get("app") == "ticketdepot"
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    main()
