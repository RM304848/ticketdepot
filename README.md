# Ticketdepot

Lokale App (Windows + macOS) für eigene DB-Tickets: Sie liest Ticket-PDFs ein, holt für genau diese Züge die tatsächliche Ankunft und sagt pro Fahrt, was dir zusteht – mit einer Frage, den Euro-Beträgen je Antwort, einer Frist und einer Aktion.

Kein Server im Netz, kein Konto, keine Kosten. Die App läuft auf deinem Rechner (`127.0.0.1`), die Oberfläche öffnet sich im Browser, die Daten liegen in einer SQLite-Datei.

## Installieren

Unter [Releases](../../releases) die Datei für dein System laden:

- **Windows:** `Ticketdepot-<version>-windows.exe` starten. Blockiert der Virenscanner die .exe, die `.zip` entpacken und `Ticketdepot.exe` darin starten.
- **macOS (Apple Silicon):** `Ticketdepot-<version>-macos-arm64.dmg` öffnen, Ticketdepot nach „Programme“ ziehen.

Die App ist nicht signiert, deshalb warnt das System beim ersten Start:

- **Windows:** „Der Computer wurde durch Windows geschützt“ → **Weitere Informationen** → **Trotzdem ausführen**.
- **macOS:** Start wird blockiert → **Systemeinstellungen → Datenschutz & Sicherheit** → unten **Trotzdem öffnen**.

Beenden über **Beenden** unten auf der Seite oder das Symbol in der Taskleiste bzw. Menüleiste. Die App hat kein Dock-Symbol – vor dem Löschen oder Aktualisieren so beenden. Ein zweiter Start öffnet nur den Browser zur laufenden App. Daten: `%APPDATA%\Ticketdepot` bzw. `~/Library/Application Support/Ticketdepot` – sie bleiben bei Updates erhalten.

## Was die App pro Fahrt entscheidet

| Verspätung am Ziel | Ja, gefahren | Nein, nicht gefahren |
|---|---|---|
| < 20 min | Kein Handlungsbedarf (keine Frage) | |
| 20–59 min | Kein Anspruch | Später fahren (Zugbindung aufgehoben), bis 1 Jahr nach Reisedatum |
| 60–119 min | 25 % Entschädigung | Geld zurück **oder** später fahren |
| ≥ 120 min | 50 % Entschädigung | Geld zurück **oder** später fahren |
| Ausfall / Anschluss verpasst | hängt von deiner Ankunft ab („Wann bist du angekommen?“) | Geld zurück **oder** später fahren |

- Hin- und Rückfahrt zu einem Preis: Basis ist der halbe Preis. Entschädigungen unter 4 € zahlt die DB nicht aus.
- Fristen zählen ab Reisedatum (Abfahrt). Die App setzt für Anträge **3 Monate** (bahn.de nennt 12 Monate); Vorrat-Tickets gelten 1 Jahr.
- „Bald fällig“: Anträge 21 Tage vor der Frist, Vorrat-Tickets 30 Tage vor Ablauf. Am selben Tag liegt der Kalendereintrag.
- Grundlage ist die *erwartete* Verspätung; die App sieht die *tatsächliche* als Näherung.
- Alle Regeln, Schwellen, Texte und die offiziellen bahn.de-Seiten stehen in [`ticketdepot/rules.py`](ticketdepot/rules.py) (`LAST_VERIFIED`). `python tools/check_links.py` prüft die Links.

**Vorrat:** Für ein Ticket, das du später nutzen willst, gibt es ein **Nachweis-PDF**: das Original-Ticket unverändert (Barcode bleibt gültig) plus eine Seite mit Verspätung, Gültigkeit und Quelle. Aufs Handy legen (Dateien/Drive) und bei der Kontrolle zeigen. Dazu **In Kalender** (.ics oder Google Kalender).

## Woher die Verspätungen kommen

Aus dem öffentlichen Datensatz [piebro/deutsche-bahn-data](https://huggingface.co/datasets/piebro/deutsche-bahn-data) (DB-IRIS-Echtzeitdaten, CC BY 4.0). Der Ansatz folgt der Open-Source-App [delay_bahn](https://github.com/sha2nkt/delay_bahn). Abgefragt werden nur die Züge deiner Tickets, per HTTP-Range-Request direkt aus den Parquet-Dateien; das Ergebnis wird lokal gespeichert.

- **Abgeschlossene Monate:** Monatsdatei, ca. 5–20 s pro Fahrt, endgültig.
- **Laufender Monat:** rohe IRIS-Antworten des Reisetags, 30–60 s pro Fahrt, nach 2 Tagen endgültig.
- Grenzen: nur Bahnhöfe in Deutschland; U-Bahn, Tram und Bus sind nicht erfasst.

## Entwickeln

Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m ticketdepot                  # oder Doppelklick auf Ticketdepot.command / Ticketdepot.bat
```

Optionen: `--port`, `--no-open`, `--no-tray`, `--data <ordner>`, `--import <ordner>`. `Ticketdepot-Test.command` startet mit den Testtickets aus `testdaten/` in einer eigenen Datenbank auf Port 8776.

Tests: `.venv/bin/python -m pytest`. Echte Tickets für Parser-Tests gehören nach `tests/fixtures/private/` (von git ignoriert).

| Datei | Zweck |
|---|---|
| `ticketdepot/rules.py` | Fahrgastrechte → `Verdict` (eine Frage, Beträge, Frist, Aktion); alle Regeln und Quellen |
| `ticketdepot/ticket_pdf.py` | DB-Ticket-PDF → `Ticket` |
| `ticketdepot/delays.py` | tatsächliche Zeiten pro Teilstrecke (Monatsdatei oder Roh-IRIS) |
| `ticketdepot/proof_pdf.py` | Nachweis-PDF: Original-Ticket + angehängte Nachweisseite (inkrementelles Update) |
| `ticketdepot/calendar_ics.py` | Kalendereinträge (.ics, Google-Kalender-Link) |
| `ticketdepot/store.py` | SQLite im Benutzerordner, mit Schema-Migration |
| `ticketdepot/api.py`, `server.py` | API für die Oberfläche; nur `127.0.0.1`, Host-Prüfung und Token pro Start |
| `ticketdepot/__main__.py` | Start: Server, Browser, Tray-Symbol, nur eine Instanz |
| `ticketdepot/ui/` | Oberfläche (HTML/CSS/JS ohne Build-Schritt), Farben nur in `:root` von `style.css` |

## Release

`__version__` in `ticketdepot/__init__.py` erhöhen, dann Tag pushen:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Die GitHub Action [`release.yml`](.github/workflows/release.yml) testet, baut auf Windows und macOS (PyInstaller, `packaging/ticketdepot.spec`), startet die gebaute App einmal zur Probe und legt ein Release mit `.exe`, `.zip` und `.dmg` an. Ohne Release (nur zum Testen der Builds): in GitHub unter **Actions → release → Run workflow**; die Dateien liegen dann als Artefakte am Lauf. Die Windows-.exe entsteht nur dort, weil PyInstaller nicht cross-kompiliert. Lokal (für das eigene System): `python tools/prepare_build.py && pyinstaller packaging/ticketdepot.spec`.

## Lizenz

GNU AGPL-3.0 ([LICENSE](LICENSE)), weil PyMuPDF mitgeliefert wird. Weitere Komponenten und Daten: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Kein Angebot der Deutschen Bahn. Verbindlich ist, was die DB entscheidet.
