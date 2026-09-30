# Testtickets

Erzeugt mit `python tools/make_test_tickets.py`. Muster-PDFs mit fiktivem Namen und erfundenen Auftragsnummern; die Züge und Verspätungen sind echt (DB-IRIS-Daten).

Starten mit `Ticketdepot-Test.command` (Doppelklick) oder `python -m ticketdepot --data testdaten/appdata --import testdaten`: eigene Testdatenbank, die PDFs hier werden beim Start importiert, die Verspätungen danach automatisch abgerufen.

| Datei | Was du sehen solltest |
|---|---|
| `Ticket_900000000101_14.08.2026__TEST_01_puenktlich.pdf` | ICE 525 kam +3 min an → „Kein Handlungsbedarf“, keine Frage. |
| `Ticket_900000000202_14.08.2026__TEST_02_wiederverwendbar.pdf` | +33 min → Zugbindung aufgehoben. „Ja“ → kein Anspruch (unter 60 min); „Nein“ → direkt in den Vorrat bis 14.08.2027 (Reiter „Vorrat“, PDF herunterladen, In Kalender). Danach „Ticket genutzt“ → erledigt. |
| `Ticket_900000000303_14.08.2026__TEST_03_25prozent_oder_erstattung.pdf` | +93 min. „Ja“ → 25 % = 12,50 €. „Nein“ → Wahl: 49,99 € zurück oder später fahren. In Details „Kontrolliert: Ja“ bei „Nein“ → Hinweis. |
| `Ticket_900000000404_14.08.2026__TEST_04_50prozent.pdf` | +134 min. „Ja“ → 50 % = 17,50 €. „Entschädigung beantragen“ → „Antrag abgeschickt“ → Reiter „Beantragt“; dort „Ausgezahlt“ → erledigt. |
| `Ticket_900000000505_14.08.2026__TEST_05_ausfall.pdf` | ICE 24 fiel in Bonn aus → Band „Ausfall“. „Nein“ → 29,99 € zurück oder später fahren. „Ja“ → „Wann bist du angekommen?“ (z. B. 23:10 → +87 min → 25 %). |
| `Ticket_900000000606_14.08.2026__TEST_06_anschluss_verpasst.pdf` | ICE 517 +40 min in München, ICE 2822 fuhr pünktlich ab → Anschluss verpasst. „Ja“ → „Wann bist du angekommen?“, z. B. 19:10 → +68 min → 25 %. |
| `Ticket_900000000707_14.08.2026__TEST_07_umstieg_74min.pdf` | Umstieg klappt (ICE 549 fuhr selbst 57 min später ab), Ankunft Berlin +74 min. „Ja“ → 25 % = 11,50 €. |
| `Ticket_900000000808_14.08.2026__TEST_08_hin_und_rueck.pdf` | Zwei Karten, Basis je 29,99 € (halber Preis). Hinfahrt +3 → kein Handlungsbedarf. Rückfahrt ICE 619 +63 (Ankunft nach Mitternacht): „Ja“ → 7,50 €, „Nein“ → 29,99 € zurück oder später fahren bis 14.08.2027; Frist 14.11.2026. |
| `Ticket_900000000909_14.08.2026__TEST_09_unter_4_euro.pdf` | +75 min, aber 25 % von 12,99 € = 3,25 € → „Ja“ → Kein Anspruch (unter 4 €); „Nein“ → 12,99 € zurück. |
| `Ticket_900000001010_20.09.2026__TEST_10_september_rohdaten.pdf` | Abruf aus den Roh-IRIS-Daten, solange der Monat läuft (ca. 1 min). +5 min → „Kein Handlungsbedarf“. |
| `Ticket_900000001111_15.10.2026__TEST_11_zukunft.pdf` | Reise in der Zukunft → Reiter „Anstehend“, kein Abruf. |
