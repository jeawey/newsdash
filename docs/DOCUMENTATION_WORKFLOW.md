# Documentation Workflow

## Ziel

Jede Änderung und jeder operative Schritt wird dokumentiert, damit Ursachenanalyse und Rollback reproduzierbar sind.

## Verbindliche Regeln

1. Vor jeder relevanten Änderung:
- Ticket/Anlass in `docs/WORKLOG.md` als neuer Eintrag anlegen (oder per Script).

2. Nach jeder Codeänderung:
- `docs/CHANGELOG.md` aktualisieren.
- Kurz festhalten: was geändert wurde, warum, erwarteter Effekt, ggf. Rollback.

3. Nach jedem operativen Eingriff (Deploy, Restart, Recovery, Manual Run):
- `docs/WORKLOG.md` mit Commands + Ergebnis ergänzen.

4. Bei Incident/Fehler:
- Im Worklog explizit `result: failed` markieren.
- Direkt darunter `next:` mit konkreter Recovery-Aktion.

## Minimalstandard pro Eintrag

- Zeitstempel
- Umgebung (local/vps/prod)
- ausgeführte Commands
- Ergebnis
- nächster Schritt

## Schnellstart

```bash
# Eintrag erzeugen (automatisch mit Zeitstempel/Commit/Status)
bash scripts/log_entry.sh worklog "Kurzer Titel" "Details zum Schritt"

# Changelog-Eintrag erzeugen
bash scripts/log_entry.sh changelog "Kurzer Titel" "Was wurde geändert und warum"
```
