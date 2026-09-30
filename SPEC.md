# Spec: Ticketdepot — UI simplification, rules engine, proof PDF, packaging

Revised 2026-09-30 after validation against the repo. Supersedes the earlier handover.

## Context

Local Python app, UI in the browser on `127.0.0.1`. No cloud, no hosting, no running costs — keep it that way. It imports DB ticket PDFs, fetches actual arrival data (DB IRIS real-time data via the Hugging Face dataset `piebro/deutsche-bahn-data`, the same source the open-source app **delay_bahn** uses) and recommends actions for delays. UI language is German.

Keep the existing stack and structure (`ticketdepot/` package, `http.server`, SQLite store, plain HTML/CSS/JS without build step). Fetched delay results are already persisted per journey in SQLite; that is the local cache — do not mirror the parquet files.

Allowed new dependencies: `pypdf`, `pystray` (+ `Pillow` for its icon), `pyinstaller` (build only). Ask before adding anything else.

## Guiding principle

Each ticket card shows only what the user needs to **decide**, not everything the app **knows**. One question, euro amounts per answer, one deadline, one action. Everything else goes behind `Details ›`.

---

## 0. Structural changes (do these first)

1. **Drop pywebview.** The app always runs in the default browser (`server.py` + `webbrowser`). Remove `pywebview` from `requirements.txt`, the `--browser` flag and the `window.pywebview` code path in `app.js`.
   - Clipboard: `navigator.clipboard` (127.0.0.1 is a secure context). Remove the `pbcopy`/`clip` subprocess in `Api.copy`.
   - External links: plain `<a target="_blank" rel="noopener noreferrer">`. Remove `Api.open_url`.
   - Original ticket PDF: `GET /ticket/<order>.pdf` opens it in a browser tab. Remove `Api.open_pdf`.
2. **Remove the combined Vorrat export**: `vorrat_pdf.write_vorrat_pdf`, the iCloud/OneDrive auto-export, `settings.json` export settings, `vorrat_info`, `export_vorrat`, `reveal_export`, `_after_change` export hook and the `Vorrat aufs Handy` button. Replaced by the per-ticket proof PDF (section 4).
3. **License: AGPL-3.0.** PyMuPDF is AGPL and ships inside the binaries. Add `LICENSE` (AGPL-3.0 full text), state it in the README and the About dialog. Add `THIRD_PARTY_NOTICES.md` listing PyMuPDF (AGPL-3.0), DuckDB (MIT), pypdf (BSD-3), pystray (LGPL-3.0), Pillow (MIT-CMU), and the dataset `piebro/deutsche-bahn-data` (CC BY 4.0 — attribution required). Credit delay_bahn (https://github.com/sha2nkt/delay_bahn) as inspiration; no code is copied from it, so its license does not apply — keep it that way.
4. **Localhost security** (other websites in the same browser can send requests to 127.0.0.1):
   - Reject every request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` (blocks DNS rebinding).
   - Per-launch random token (`secrets.token_urlsafe`). The server injects it into `index.html` (e.g. `<meta name="csrf">`); every `POST /api/*` must send it as header `X-Ticketdepot-Token`, otherwise 403. Also reject POSTs whose `Origin` is present and not the app's own origin.
   - GET download routes (`/ticket/…`, `/proof/…`, `/ics/…`) only need the Host check.
5. **Port:** fixed `8775` so bookmarks, URL filter state and browser storage survive restarts. If 8775 is taken by something else, fall back to a free port. Single instance: before binding, `GET http://127.0.0.1:8775/api/ping` (returns `{"app": "ticketdepot"}`); if our app answers, just open the browser to it and exit. On fallback ports, write the port to `<data dir>/port` so a second launch finds it.

## 1. Data model

Replace the `usage` field. New/changed columns on `journeys` (SQLite `ALTER TABLE ADD COLUMN`, guarded by `PRAGMA user_version`):

| Field | Values | Meaning |
|---|---|---|
| `ridden` | `''` · `ja` · `nein` | The one question on the card |
| `choice` | `''` · `erstattung` · `vorrat` | Only after `nein` when both options exist (delay ≥ 60 min or cancelled/missed) |
| `vorrat_used_on` | ISO date or NULL | Set by `Ticket genutzt` on a Vorrat card |
| `manual_arrival` | existing | Only asked when the booked train didn't get the user there (see 2.3) |
| `claim_status` | existing: `''` · `beantragt` · `ausgezahlt` · `abgelehnt` · `verzichtet` | |
| `controlled`, `notes` | existing | Private notes, only in Details, never in any export |

Migration of existing `usage` values: `gefahren` → `ridden=ja`; `anderer_zug` → `ridden=ja` (keep `manual_arrival`); `nicht_gefahren` → `ridden=nein`, and `choice=erstattung` if `claim_status` is `beantragt`/`ausgezahlt`, else `choice=''` (card will ask); `spaeter` → `ridden=nein`, `choice=vorrat`, `vorrat_used_on` = migration date. Drop the old column afterwards (or leave it unused).

## 2. Ticket card

### 2.1 Collapsed card (default)

- Header: `Fr 14.08. · Düsseldorf → Frankfurt · +63 min` (delay badge red; `Ausfall` / `Anschluss verpasst` instead of minutes when applicable).
- One question as two large buttons, each with the result of that answer:
  `Bist du gefahren?` → `[ Ja → 7,50 € ]` `[ Nein → 29,99 € zurück ]`
  - Ja side: compensation amount; `Kein Anspruch` if < 60 min or < 4 €; `Ankunft eintragen` if cancelled/missed.
  - Nein side: `X € zurück` if ≥ 60 min or cancelled/missed; `später fahren bis 14.08.2027` if 20–59 min.
- Deadline line: `Frist: 14.11.2026` + `Details ›`.

### 2.2 States after answering

| Situation | Card shows |
|---|---|
| Delay < 20 min, not cancelled/missed | `Kein Handlungsbedarf` — no question (both answers give nothing) |
| `ja`, compensation ≥ 4 € | `Entschädigung beantragen` (existing claim dialog) + `Nachweis kopieren` + force-majeure line (2.5) |
| `ja`, < 60 min or < 4 € | `Kein Anspruch (unter 4 €)` / `Kein Anspruch (unter 60 min)` + rule link → done |
| `ja`, cancelled/missed, no arrival | `Wann bist du angekommen?` + datetime field |
| `nein`, ≥ 60 min or cancelled/missed, no choice | Side by side: `Geld zurück: 29,99 €` [Erstattung beantragen] vs. `Später fahren: gültig bis 14.08.2027` [In den Vorrat] + rule link |
| `nein` + `erstattung` | `Erstattung beantragen` (claim dialog, refund variant) |
| `nein` + `vorrat`, or `nein` at 20–59 min | Vorrat: `PDF herunterladen`, `In Kalender`, `Ticket genutzt` |
| `vorrat_used_on` set, or Vorrat expired | done (`Später genutzt` / `Vorrat abgelaufen`) |
| `claim_status = beantragt` | `Beantragt am …` + buttons `Ausgezahlt` / `Abgelehnt` |
| `ausgezahlt` / `abgelehnt` / `verzichtet` | done |

The user can always change the answer via `Antwort ändern` in Details.

### 2.3 Actual arrival

The app knows when the booked train arrived (IRIS). It only asks for the user's own arrival when the booked train did not get them there:
- cancelled train, or missed connection (automatic, shown as the question in the table above);
- user took a different train: link `Anders angekommen?` under the Ja answer reveals the field.

Otherwise the field is not shown at all (Details shows the IRIS arrival read-only).

### 2.4 Behind `Details ›`

Order number, fare type, price and fare basis, IRIS proof text + `abgerufen am`, `Zugbindung aufgehoben` badge, all applicable rule sources (section 7), `Antwort ändern`, `Kontrolliert?` (private note; if `ja` combined with `nein`, show a muted hint), free-text note, `Löschen` (red).

### 2.5 Force majeure

Wherever a **compensation** amount is shown (not refund, not reuse): one muted line `Ausnahme möglich bei höherer Gewalt (z. B. Naturkatastrophe, Polizeieinsatz)` + `Regel bei bahn.de ↗`. Basis: EU Regulation 2021/782 (Art. 19 Abs. 10). Text lives in the rules module. Note: bahn.de states that an ordinary storm ("gewöhnliches Unwetter") does **not** count; exceptions are major natural disasters and third-party causes (persons on the track, cable theft, police operations).

### 2.6 Bug to fix

`_by_usage` lists "Nicht gefahren" twice (refund and Vorrat). They are alternatives → the choice in 2.2.

## 3. Rules engine (`ticketdepot/rules.py`)

All thresholds, percentages, texts and source URLs live here with `LAST_VERIFIED = "2026-09-30"`. UI and PDF never hardcode policy text, percentages or thresholds — they get them from the API view.

1. **Travel date** = departure date of the journey (first leg). All deadlines and validity dates count from it. (ICE 619 departs 14.08. 23:28 and arrives 15.08. 01:17 → travel date 14.08.)
2. **Compensation (ridden):** delay at destination ≥ 60 min → 25 %, ≥ 120 min → 50 % of the fare basis. Round half up to cents.
   - Return ticket: basis = the leg's share (price / number of journeys; 59,98 € → 29,99 €).
3. **Minimum payout:** below 4,00 € → `Kein Anspruch (unter 4 €)`.
4. **Refund (not ridden):** expected delay ≥ 60 min (or cancelled/missed) → refund of the unused journey's basis.
5. **Reuse / Vorrat:** expected delay ≥ 20 min (or cancelled/missed) lifts train binding; usable for a later connection up to **one year after the travel date** (last valid day = travel date + 1 year). Not for heavily discounted tickets (Deutschland-Ticket, Länder-Tickets). Source verified: https://www.bahn.de/faq/zugbindung-aufgehoben-bedeutung ("bis zu einem Jahr nach ursprünglichem Reisedatum"). Update the stale comment and README that say bahn.de names no limit.
6. **Refund and reuse are mutually exclusive** → choice in 2.2.
7. **Claim deadline:** the app shows 3 months after the travel date (`CLAIM_DEADLINE_MONTHS`), for both compensation and refund, as an early reminder. bahn.de states 12 months (`DB_CLAIM_LIMIT_MONTHS`, shown in Details and in the calendar description).
8. **Lead times** (constants): `CLAIM_LEAD_DAYS = 21`, `VORRAT_LEAD_DAYS = 30`. An item is "Frist bald" from `deadline − lead` on; calendar events use the same date (section 6).
9. **Delay bands** (for filters), lower bound inclusive, upper exclusive: `20–59`, `60–119`, `≥ 120`. Each band carries a short explanation for both answers, e.g. `60–119 min`: `Gefahren → 25 % · Nicht gefahren → Geld zurück oder später fahren`.
10. Every rule has `source_url` (section 7).

## 4. Proof PDF ("Nachweis-PDF")

One PDF per Vorrat ticket, shown on the phone at a ticket check, possibly offline months later. DB accepts online tickets as a PDF on a mobile device (verified: https://www.bahn.de/faq/ist-mein-online-ticket-auch-gueltig-wenn-es-als-pdf-auf-dem-laptop-vorgezeigt-wird). Output is always a PDF.

**Structure:** the original ticket PDF, **unchanged**, with the proof page appended as an **incremental update** (`pypdf`, `PdfWriter(clone_from=original, incremental=True)`, then add the page). The original file's bytes are then a literal prefix of the output. Never re-render, rasterize, recompress, subset fonts or re-encode anything of the original (DB uses signed Aztec codes). Use PyMuPDF only to draw the proof page into a separate one-page PDF, then append that page with pypdf.

**Proof page** (phone-sized, black on white, readable in 5 seconds):
- Large: `Zugbindung aufgehoben · gültig bis 14.08.2027` and `+63 min` (or `Zug ausgefallen` / `Anschluss verpasst`)
- Below: train number, date, route, planned vs. actual arrival, order number
- Footer: `Quelle: DB-Echtzeitdaten (IRIS) via piebro/deutsche-bahn-data (CC BY 4.0), abgerufen am <date>`
- Factual wording, no certificate style. Never claim the ticket was unused. `Kontrolliert?` and notes never appear.

**Delivery:** `PDF herunterladen` per Vorrat ticket → `GET /proof/<journey id>.pdf` with `Content-Disposition: attachment`.
Filename: `DB_<YYYY-MM-DD>_<Train>_gueltig-bis-<YYYY-MM-DD>.pdf`, e.g. `DB_2026-08-14_ICE619_gueltig-bis-2027-08-14.pdf` (train without space; multi-leg: first train).
Hint next to the button: `Tipp: Auf dem Handy in Dateien/Drive speichern, nicht nur im Chat lassen.`
No QR codes, LAN serving, Web Share or cloud transfer.

## 5. Dashboard, tabs, filters

**Tiles (three):** `Offen` (€ of claims the user can file now: compensation ≥ 4 € after `ja`, refund after `erstattung`, not yet `beantragt`), `Brauchen deine Angabe` (count), `Frist bald` (claims and Vorrat items past their lead date).

**Tabs:** `Zu tun`, `Vorrat`, `Beantragt`, `Anstehend`, `Alle`. `Vorrat` sorted by expiry, soonest first.

**Route lookup in `Vorrat`:** always visible in the Vorrat tab when it has tickets (not behind the `Filter` toggle); fields `Von` / `Nach` with autocomplete from stations of imported tickets; matching is case/umlaut-insensitive on the station name prefix (`Düsseldorf` matches `Düsseldorf Hbf`, `Frankfurt` matches `Frankfurt(Main)Hbf`). Compare against the journey's origin and final destination. Direction matters.

**Chips inside `Alle`:** `Entschädigung möglich`, `Erstattung möglich`, `Wiederverwendbar`, `Kein Anspruch`, `Beantragt`, `Ausgezahlt`. A chip matches the journey's current outcome; an unanswered journey matches every outcome one of its answers leads to (unanswered ICE 619 matches Entschädigung, Erstattung and Wiederverwendbar).

**Delay:** band chips `20–59 min`, `60–119 min`, `≥ 120 min` (tooltip = band explanation from rules), plus a separate chip `Ausfall / Anschluss verpasst`. Trips < 20 min are in no band.

**Deadline:** chip `Frist bald`.

**Search:** one field over train number, station, order number and note.

Filters combine with AND, live in URL query parameters, and sit behind a `Filter` toggle until there are more than 10 tickets. When any filter is active: result count + `Filter zurücksetzen`.

## 6. Calendar export

For every Vorrat ticket and every open claim: `In Kalender` → `.ics` download (primary) and `Google Kalender` link (secondary, `calendar.google.com/calendar/render?action=TEMPLATE`).

- `.ics` as plain text, no new dependency: RFC 5545, CRLF, folding at 75 octets, UTF-8.
- **The event is the reminder** (Google ignores `VALARM` on import): all-day event on the action date, not the expiry date.
  - Claim: `deadline − 21 days`, title `Entschädigung beantragen – Frist 14.11.2026 (ICE 619)` (or `Erstattung beantragen – …`).
  - Vorrat: `expiry − 30 days`, title `DB-Ticket nutzen – gültig bis 14.08.2027: Düsseldorf → Frankfurt (ICE 619)`.
- `VALARM` at 09:00 on the event day (`TRIGGER:PT9H`) for Apple/Outlook.
- Description: route, train, travel date, order number, the real deadline/expiry, `Nachweis-PDF: <filename>` (filename only, no localhost URL).
- Stable `UID`: `<order>-<journey idx>-<claim|vorrat>@ticketdepot.local`. Re-import updates the event where the calendar supports it; not guaranteed everywhere.
- Bulk: `Alle Fristen in Kalender` on the dashboard → one `.ics` with all open items.

## 7. Official sources

- Every rule in `rules.py` has `source_url` pointing to the specific bahn.de page. UI shows `Regel bei bahn.de ↗` (U+2197, no emoji variant) next to each recommendation, `target="_blank" rel="noopener noreferrer"`. Details lists all sources for the ticket.
- All verified on 2026-09-30 (see `RULES` in `rules.py`): Zugbindung/one year, compensation 25/50 % and 4 € minimum (same FAQ page), refund when not travelling (`/service/informationen-buchung/fahrgastrechte/rechtliche-regelungen`), claim deadline (FAQ: 12 months), force majeure (FAQ, Art. 19 Abs. 10), PDF on mobile device.
- `tools/check_links.py`: requests every `source_url` with a browser User-Agent (`HEAD`, fall back to `GET`); reports OK / broken (404, 410, DNS) / `manuell prüfen` (403, 429, timeouts). Manual run only.

## 8. Visual design: "Shades of Teal", one dark theme

Single dark theme; ignore `prefers-color-scheme`; remove the light variables. Remove the red "DB" logo box; use a neutral icon (e.g. a simple ticket glyph) and the name "Ticketdepot".

All colors are CSS custom properties in **one `:root` block** in `style.css`; no hex anywhere else (including JS and `#fff` in toasts).

Palette (https://www.color-hex.com/color-palette/4666):

| Token | Hex | Use |
|---|---|---|
| `--teal-100` | `#b2d8d8` | Large numbers on tiles, emphasis text |
| `--teal-300` | `#66b2b2` | Links, active tab underline, focus rings, small accent text |
| `--teal-500` | `#008080` | Primary button fill, white text |
| `--teal-700` | `#006666` | Primary hover/pressed, selected chips, white text |
| `--teal-900` | `#004c4c` | Selected card tint, active filter bar background |

Neutrals and semantic colors (same `:root` block):

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#0e1717` | Page background |
| `--surface` | `#142121` | Cards, tiles |
| `--surface-2` | `#1b2b2b` | Inputs, hover |
| `--line` | `#294040` | Borders |
| `--text` | `#e6f0f0` | Body text |
| `--muted` | `#9bb3b3` | Secondary text |
| `--white` | `#ffffff` | Text on teal fills |
| `--amber` | `#f2b554` | Needs input, deadlines |
| `--red` | `#ff8a80` | Delay badge, `Löschen` |

Teal = action / money available. Teal-500 and darker only as fills with white text, never as text on the dark background. The proof PDF keeps black on white.

## 9. Packaging and release

- Entry point: start server on 127.0.0.1 (section 0.5), open browser, run `pystray` icon with `Öffnen` and `Beenden`. On macOS `pystray` must own the main thread → server in a background thread. Set `LSUIElement` so the app lives in the menu bar only.
- User data: `%APPDATA%\Ticketdepot` / `~/Library/Application Support/Ticketdepot` (already in `store.py`). Never write next to the executable.
- Version: `ticketdepot/__init__.py` `__version__`, shown in the UI footer; CI fails if it does not match the tag.
- **DuckDB `httpfs`:** `delays.py` runs `INSTALL httpfs`, which downloads an extension at runtime. In CI, install it into a folder, bundle it (`--add-data`) and at runtime `SET extension_directory` to the bundled path, so a clean or firewalled machine works.
- PyInstaller, built natively per OS. Windows: `--onefile --windowed` with icon; also attach a zipped `--onedir` build as fallback (antivirus false positives on unsigned onefile exes are common). macOS: arm64 `.app` → `.dmg` via `hdiutil`.
- `.github/workflows/release.yml`: on tag `v*`; jobs `windows-latest`, `macos-latest`: install deps, run tests, build, upload; create the Release with `Ticketdepot-<version>-windows.exe`, `Ticketdepot-<version>-windows.zip`, `Ticketdepot-<version>-macos-arm64.dmg`.
- Public repo. Before the first push, verify nothing private is committed (`tests/fixtures/private/`, `*.sqlite`, `testdaten/appdata/` are git-ignored).
- Unsigned: README + release notes explain first launch — Windows `Weitere Informationen → Trotzdem ausführen`; macOS `Systemeinstellungen → Datenschutz & Sicherheit → Trotzdem öffnen`.
- About dialog: version, AGPL-3.0, data attribution (CC BY 4.0), credit to delay_bahn, `LAST_VERIFIED` date of the rules.

## 10. Acceptance tests

| Ticket | Delay | Ja | Nein | Vorrat until | Claim deadline |
|---|---|---|---|---|---|
| ICE 619, Düsseldorf Hbf → Frankfurt(Main)Hbf, 14.08.2026 (Rückfahrt of Sparpreis Hin/Rück 59,98 €, basis 29,99 €), order 900000000808 | +63 min | 7,50 € | 29,99 € zurück | 14.08.2027 | 14.11.2026 |
| ICE 2466, Hamm(Westf)Hbf → Köln Hbf, 14.08.2026, Super Sparpreis 12,99 €, order 900000000909 | +75 min | Kein Anspruch (3,25 € < 4 €) | 12,99 € zurück | 14.08.2027 | 14.11.2026 |

Both are in `testdaten/` (`Ticketdepot-Test.command`).

Automated (pytest, pass `now` explicitly, no network):
- Rules: thresholds 19/20, 59/60, 119/120 min; 4 € minimum (3,99 / 4,00); return-ticket basis; travel date = departure date (ICE 619 deadline 14.11.2026, not 15.11.).
- Both test tickets produce exactly the table values; ICE 2466 still shows the question.
- Migration maps all old `usage` values as in section 1.
- Proof PDF: the original file bytes are a prefix of the output; output has original page count + 1; filename as specified; no `Kontrolliert`/note text in the proof page.
- Route lookup `Düsseldorf → Frankfurt` finds ICE 619 (in Vorrat); `Frankfurt → Düsseldorf` finds nothing.
- Chip `Kein Anspruch` includes ICE 2466 after `ja`.
- Band `60–119` returns both tickets; `20–59` and `≥ 120` none; delay 60 → `60–119`, 120 → `≥ 120`; cancelled train → only `Ausfall / Anschluss verpasst`.
- `.ics` for ICE 619 Vorrat: all-day event on 15.07.2027, alarm 09:00 that day, CRLF, lines ≤ 75 octets, stable UID; claim event on 24.10.2026.
- Security: POST without token → 403; wrong `Host` → 403.
- Grep: no hex color outside the `:root` block of `style.css`; no `DB` logo element.
- Empty state (no tickets) renders.

Manual:
- Proof PDF from the real ticket in `tests/fixtures/private/`: barcode scans with a phone (test tickets have no barcode).
- `.ics` imports into Apple Calendar and Google Calendar on the right date.
- Every recommendation for the two test tickets shows a working `Regel bei bahn.de ↗`; `check_links.py` reports nothing broken.
- Force-majeure line under ICE 619 `Ja → 7,50 €`, not under refund or reuse.
- Tag `v0.1.0` → Release with `.exe`, `.zip`, `.dmg`; on a clean machine without Python each launches, opens the browser, fetches a delay, keeps tickets across quit/relaunch, quits via tray; a second launch opens the running instance.

## Build order

1. Structural changes (section 0) + data model migration
2. Rules module + tests
3. Card + dashboard + palette
4. Proof PDF + calendar
5. Filters
6. Packaging + CI
