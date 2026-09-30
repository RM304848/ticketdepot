#!/bin/sh
# Startet die App mit einer eigenen Testdatenbank (testdaten/appdata) auf eigenem Port und importiert
# die Testtickets; deine echten Daten und eine laufende echte App bleiben unberührt.
cd "$(dirname "$0")" && exec .venv/bin/python -m ticketdepot --data testdaten/appdata --port 8776 --import testdaten
