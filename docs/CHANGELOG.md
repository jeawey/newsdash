# Changelog

Alle relevanten Code- und Konfigurationsänderungen werden hier chronologisch dokumentiert.

## Format

Für jeden Eintrag:
- Datum/Zeit (Europe/Madrid)
- Bereich (`web`, `worker`, `config`, `infra`, `docs`)
- Änderung
- Grund
- Erwarteter Effekt
- Rollback-Hinweis

## 2026-03-01

### Worker
- Robustere Run-Sperre mit Datei-Lock (`flock`) ergänzt.
- Cleanup für orphaned/stale `running`-Jobs beim Start und vor Runs verschärft.
- Fetch-Laufzeit begrenzt (`FETCH_MAX_RUNTIME_SECONDS`) und Progress-Logs ergänzt.
- Feed-Fetch parallelisiert (ThreadPool), inklusive Caps je Feed und je Run.
- Übersetzung in die Persistenz-Phase verschoben (nur final ausgewählte Stories).

### Web
- Dashboard-Performance verbessert (DOM-Caching, reduzierte Animation-Last, SQL-Filter optimiert).
- Anzeige pro Kategorie begrenzt und „Mehr anzeigen“ ergänzt.

### Config
- Neue Runtime-Settings eingeführt:
  - `PIPELINE_LOCK_FILE`
  - `JOB_STALE_AFTER_MINUTES`
  - `FETCH_MAX_RUNTIME_SECONDS`
  - `FEED_FETCH_TIMEOUT_SECONDS`
  - `FETCH_MAX_WORKERS`
  - `MAX_ENTRIES_PER_FEED`
  - `MAX_RAW_STORIES_PER_RUN`

### 2026-03-01 14:22:00 Europe/Madrid | Web (UI/Theme)
- Änderung:
  - Theme-Toggle von Text auf Sonne/Mond-Icon umgestellt (inkl. passender ARIA-Labels je Modus).
  - White Mode visuell erweitert: zusätzlicher farbiger Blur-Orb im Hintergrund und stärkere Farbverläufe.
  - Buttons im White Mode farbiger gestaltet (Theme-Toggle, Topic-Buttons, aktive States, „Mehr anzeigen“).
  - Lesbarkeit im White Mode verbessert: `HOT`-Badge und Relevanz-Badges auf dunklere Textfarben angepasst.
  - Relevanz-Legende im White Mode kontraststärker gemacht (Legendentext, Faktorzeilen, Code-Badge, 1-10-Skala inkl. Labels).
- Grund:
  - White Mode war visuell zu neutral und in mehreren Bereichen (insbesondere Legende) schwer lesbar.
- Erwarteter Effekt:
  - Klarere Bedienung des Theme-Toggles, besserer Kontrast und insgesamt ansprechendere, konsistentere Light-Theme-Darstellung.
- Rollback-Hinweis:
  - Änderungen in `app/templates/index.html` und `app/static/styles.css` rückgängig machen (revert auf vorherigen Commit/Stand).

### 2026-03-01 13:50:05 Europe/Madrid | Dokumentationsprozess gestartet
- Details: Neue Doku-Dateien und log_entry.sh für standardisierte Änderungs- und Betriebsprotokolle
- Commit: ff94b80

### 2026-03-01 14:17:29 Europe/Madrid | Worker (Run-Stabilität + Performance + Balancing)
- Änderung:
  - Run-Lock final auf Datei-Lock (`flock`) umgestellt; DB-`running` dient nur noch als Status.
  - Orphan-/Stale-Cleanup für `running`-Einträge vor Run und beim Scheduler-Start verschärft.
  - `run_pipeline`-Fehlerbehandlung auf `BaseException` erweitert, damit Abbrüche zuverlässig als `failed` markiert werden.
  - Fetch-Pipeline parallelisiert (`ThreadPoolExecutor`) und mit harten Limits versehen:
    - `FETCH_MAX_RUNTIME_SECONDS`
    - `FEED_FETCH_TIMEOUT_SECONDS`
    - `FETCH_MAX_WORKERS`
    - `MAX_ENTRIES_PER_FEED`
    - `MAX_RAW_STORIES_PER_RUN`
  - Progress- und Timing-Logs ergänzt (`fetch/score/store`), damit Laufzustand transparent ist.
  - Übersetzung in Persistenzphase verschoben (nur final inserierte Stories), Translation-Timeout gesenkt.
  - Sektor-Balance nachgeschärft:
    - weniger Politics-Übersteuerung (strengerer Politics-Tie-Break)
    - Fallback bei unsicherer Klassifikation auf Query-Basis-Sektor statt pauschal Politics
    - Hamburg-Filter leicht entschärft (explizites „Hamburg“ wird bevorzugt)
    - Hard-Relevance-Gates in mehreren Sektoren von 2 auf 1 gelockert
    - zusätzliche deutsche Relevanzbegriffe für Biotechnologie/Sustainability/Frequenzen/Cannabis/Crypto.
- Grund:
  - Wiederkehrende Run-Blockaden und lange/inkonsistente Läufe sowie unausgewogene Verteilung zwischen Sektoren.
- Erwarteter Effekt:
  - Stabile automatische und manuelle Runs ohne dauerhafte Lock-Deadlocks, kürzere Laufzeiten und bessere sektorale Abdeckung.
- Rollback-Hinweis:
  - Betroffene Dateien auf vorherigen Stand zurücksetzen:
    - `worker/jobs.py`
    - `worker/fetcher.py`
    - `worker/store.py`
    - `worker/translate.py`
    - `app/settings.py`
