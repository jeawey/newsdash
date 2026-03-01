# Worklog

Operatives Journal für Deployments, manuelle Runs, Recovery-Schritte und Beobachtungen.
Jeder Schritt sollte hier landen, damit Fehleranalysen und Rückverfolgung schnell möglich sind.

## Eintrags-Template

```md
## YYYY-MM-DD HH:MM:SS Europe/Madrid | <type>
- actor: <name>
- environment: <local|vps|prod>
- summary: <kurzbeschreibung>
- commands:
  - `<command 1>`
  - `<command 2>`
- result: <ok|failed|partial>
- notes: <wichtigste Beobachtung>
- next: <nächster Schritt>
```

## 2026-03-01

### Initialisierung
- Das Worklog wurde eingeführt, um jeden operativen Schritt nachvollziehbar zu machen.

## 2026-03-01 13:50:05 Europe/Madrid | step
- actor: florianstrobel
- environment: local
- summary: Dokumentationssystem eingeführt
- result: pending
- notes: CHANGELOG, WORKLOG, Workflow und Logging-Skript ergänzt
- git_head: ff94b80
- git_status:
```text
 M README.md
 M app/settings.py
 M worker/fetcher.py
 M worker/jobs.py
 M worker/store.py
 M worker/translate.py
?? docs/CHANGELOG.md
?? docs/DOCUMENTATION_WORKFLOW.md
?? docs/WORKLOG.md
?? scripts/log_entry.sh
```
