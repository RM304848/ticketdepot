# Änderungen

Was sich von Version zu Version ändert, in Worten für die, die die App benutzen.
Neues kommt unter **Unveröffentlicht**; vor dem Veröffentlichen wird daraus der
Abschnitt der neuen Version. Genau dieser Abschnitt steht dann als „Neu in …“ im
GitHub-Release (`packaging/release_notes.py`), ohne ihn bricht der Release ab.

## Unveröffentlicht

- **Mac:** Das Symbol in der Menüleiste ist jetzt ein schlichtes Ticket wie die
  anderen Symbole dort und passt sich hellem und dunklem Modus an. Darüber
  „Öffnen“ und „Beenden“.

## 0.1.5 – 2026-10-01

- **Zugbindung aufgehoben, obwohl der Zug aufgeholt hat:** Maßgeblich ist die
  Prognose (ab 20 min Verspätung am Ziel), nicht die spätere Ankunft. Bist du
  deshalb nicht gefahren, schiebt „Zugbindung war aufgehoben? In den Vorrat“ das
  Ticket trotzdem in den Vorrat – auch wenn der Zug in den Daten pünktlich ist
  oder ganz fehlt, und schon am Reisetag. Im Nachweis-PDF steht „Prognose ab
  20 min“ als deine eigene Angabe.
- **„Doch nicht gefahren? In den Vorrat“** bei „Kein Anspruch“: Wer „Ja“
  angegeben hatte, kann das Ticket nachträglich in den Vorrat legen, ohne die
  eingetragene Ankunft zu verlieren.
- **Nachweis-Bild:** Auf jeder Vorrat-Karte lässt sich ein Bild hinzufügen,
  z. B. der Screenshot der DB-Meldung „Zugbindung aufgehoben“. Es steht als
  eigene Seite „Eigener Nachweis“ am Ende des Nachweis-PDFs. PNG oder JPEG;
  Handyfotos werden richtig gedreht.
- **Dunkles Design:** Die ursprünglichen dunklen Farben sind zurück, neben dem
  hellen Design. Die App folgt dem Gerät; der Knopf ◐ / ☀ / ☾ oben rechts legt
  hell oder dunkel fest und merkt sich die Wahl.
- Beim ersten Start wird die Datenbank erweitert; deine Tickets und Antworten
  bleiben unverändert.

## 0.1.4 – 2026-10-01

- **Mehr Züge gefunden:** Weicht der Fahrplan leicht vom Ticket ab (z. B. 14:13
  statt 14:10), findet die App den Zug trotzdem. Bisher hieß es dann „keine
  Daten“. Die Verspätung zählt weiter gegen die Zeiten auf dem Ticket.
- **„Aus Downloads“** findet auch Tickets mit dem neuen bahn.de-Dateinamen
  `DB_Ticket_<Auftrag>.pdf`.
- **Helles Design** mit warmem Papierton; Türkis nur noch für Knöpfe, Links
  und Beträge.
- Bei „Nein“ steht jetzt direkt, dass statt Geld zurück auch später fahren
  möglich ist („oder später fahren bis …“).
- **Anschluss verpasst:** Die Frage lautet „Bist du trotzdem ans Ziel
  gefahren?“ mit „Ja, später angekommen“ / „Nein, Reise abgebrochen“. War der
  gebuchte Zug ohnehin ≥ 60 min zu spät, gibt es die Erstattung ohne
  Bedingung.
- Ist die eigene Frist der App verpasst, zeigt die Karte, bis wann die DB den
  Antrag laut bahn.de noch annimmt, statt „bald fällig“ mit einem Datum in der
  Vergangenheit.

## 0.1.3 – 2026-10-01

- **Ausfälle genauer:** Die App unterscheidet Zugausfall, Teilausfall (Zug
  endete früher oder begann später, mit Bahnhof) und Haltausfall (nur dein Halt
  entfiel). So steht es auf der Karte und im Nachweis-PDF.
- Erstattung nach Ausfall oder verpasstem Anschluss wird mit ihrer Bedingung
  gezeigt: nur, wenn du dadurch mindestens 60 min später angekommen wärst.
- **„Anschluss verpasst?“** bei Tickets mit Umstieg, wenn die Daten den
  Umstieg als geschafft zeigen. **„Zug fiel aus“**, wenn ein Zug ganz in den
  Daten fehlt. Beides gilt als deine eigene Angabe.
- Fährt ein Zug nach einer Fahrplanänderung früher ab als gebucht, ist die
  Zugbindung aufgehoben.

## 0.1.2 – 2026-09-30

- **Verspätungen prüfen geht wieder auf jedem Rechner:** Bisher schlug die
  Abfrage außerhalb des Entwicklungsrechners mit einem Zertifikatsfehler fehl.
- „Beenden“ steht jetzt oben rechts.

## 0.1.1 – 2026-09-30

- **„Beenden“-Knopf** auf der Seite. Die App hat kein Dock-Symbol; so lässt sie
  sich beenden, ohne das Symbol in Taskleiste bzw. Menüleiste zu suchen – nötig
  vor dem Löschen oder Aktualisieren.

## 0.1.0 – 2026-09-30

- Erste Version: Ticket-PDFs von bahn.de importieren, Verspätungen aus den
  DB-Echtzeitdaten holen, pro Fahrt eine Frage mit dem Betrag je Antwort, einer
  Frist und einem nächsten Schritt.
- Entschädigung und Erstattung mit Antragshilfe, Vorrat für später nutzbare
  Tickets mit Nachweis-PDF (Original-Ticket unverändert), Erinnerungen als
  Kalendereintrag, Streckensuche im Vorrat.
- Läuft lokal im Browser, für Windows und Mac.
