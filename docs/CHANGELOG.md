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

### 2026-03-01 15:25:14 Europe/Madrid | Worker/Web (Scoring-Qualität, Feed-Nutzung, Stabilität)
- Änderung:
  - Scoring auf mehrstufiges Modell erweitert:
    - gewichtete Sektor-Signale auf `title + summary` (statt title-only),
    - additiver Constructive-Lens (kein harter Gatekeeper),
    - Noise-Penalties gegen generische/low-signal Meldungen,
    - Vergleichs- und Kohärenzanteil weiterhin aktiv.
  - Scoring-Explain-Logging ergänzt (`Score explain ...` inkl. Teil-Scores und Treffertermen).
  - Neues Setting eingeführt:
    - `SCORING_EXPLAIN_LOG_LIMIT`
  - Fetch-Budgetierung zwischen Query-Feeds und Direct-Feeds fest verdrahtet (fairere Nutzung der vielen RSS-Feeds):
    - `MIN_DIRECT_FEED_RAW_STORIES`
    - `DIRECT_FEED_RAW_SHARE`
  - Top-Stories im Web diversifiziert (Soft-Cap je Sektor statt reine Score-Monokultur).
  - Politics-Qualitätsfilter verschärft:
    - High-Signal-Filter bereits im Fetch für Politics,
    - zusätzlicher Hard-Gate im Store für persistierte Politics-Stories.
  - `ObjectDeletedError` in stündlichen Runs behoben:
    - persistierte Insert-IDs werden robust via `flush()` erfasst und nach Pruning sauber re-queryt,
    - defensiver Fallback im Breaking-Digest bei gelöschten ORM-Instanzen.
- Grund:
  - Zu viele low-signal/random Politics-Meldungen im Dashboard, unzureichende Nutzung direkter RSS-Feeds bei hohen Volumina, sowie Laufabbrüche durch gelöschte ORM-Instanzen.
- Erwarteter Effekt:
  - Höhere thematische Qualität im Ranking, bessere Ausnutzung direkter Feeds, stabilere stündliche Runs ohne `ObjectDeletedError`, nachvollziehbares Scoring-Tuning über Explain-Logs.
- Rollback-Hinweis:
  - Betroffene Dateien auf vorherigen Stand zurücksetzen:
    - `worker/scoring.py`
    - `worker/fetcher.py`
    - `worker/store.py`
    - `worker/jobs.py`
    - `app/main.py`
    - `app/settings.py`

### 2026-03-01 15:28:09 Europe/Madrid | Worker (Sektor-Fairness im Fetch)
- Änderung:
  - Sektorbasierte Budget-Limits im Fetch eingeführt (pro Kind `query`/`direct`), statt reiner First-Come-Aufnahme.
  - Mindestkontingente für unterrepräsentierte Zielsektoren aktiviert:
    - Query: `Sustainability`, `Biotechnologie`, `Cannabis`
    - Direct: `Sustainability`, `Biotechnologie`, `Cannabis`
  - Maximalanteil für dominante Direct-Sektoren ergänzt:
    - `Politics` capped via Share-Limit im Direct-Budget.
  - Verteilungs-Logs pro Sektor ergänzt:
    - `Fetch sector split (query)`
    - `Fetch sector split (direct)`
- Grund:
  - Trotz großer Feed-Menge wurden relevante Zielsektoren durch dominante Politics-Volumina im Rohdaten-Budget verdrängt.
- Erwarteter Effekt:
  - Stabilere Rohdaten-Abdeckung für Sustainability/Biotechnologie/Cannabis und bessere Chance auf sichtbare Dashboard-Items in diesen Sektoren.
- Rollback-Hinweis:
  - Änderungen in `worker/fetcher.py` zurücknehmen.

### 2026-03-01 15:41:41 Europe/Madrid | Worker (Scoring-Taxonomie erweitert)
- Änderung:
  - Keyword-Taxonomie in `worker/scoring.py` deutlich erweitert für:
    - `Sustainability`, `Biotechnologie`, `Cannabis`, `Kenya`, `Hamburg`, `Mallorca`, `AI`, `Crypto`, `Politics`.
  - Constructive-Lens um strategische Relevanzmarker ergänzt (z. B. `trade policy`, `export controls`, `procurement`, `infrastructure`), damit Impact-Gating nicht nur von Lens-Treffern abhängt.
  - Impact-Gating angepasst: Nutzung von `relevance_signal` statt reinem Lens-Score.
  - Subtopic-Boosts für operative regionale und vertikale Kernbereiche ergänzt (u. a. Vergaben, Infrastruktur, Regulations/Breakthroughs).
  - Explain-Logs um Subtopic-Beitrag erweitert.
- Grund:
  - Zu schwache thematische Abdeckung in Sustainability/Biotechnologie/Cannabis und unzureichende Berücksichtigung strategischer Themen in der Impact-Logik.
- Erwarteter Effekt:
  - Breitere, aber besser priorisierte Trefferlage; höhere Sichtbarkeit der Zielsektoren bei weiterhin globaler Abdeckung.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` zurücknehmen.

### 2026-03-01 20:11:19 Europe/Madrid | Worker (Fetch-Backfill respektiert Sektor-Caps)
- Änderung:
  - Backfill-Phase im Fetch korrigiert: Overflow-Stories werden beim Auffüllen jetzt erneut durch die sektoralen Limits/Floors geprüft (statt Caps implizit zu umgehen).
  - Finale Sektorverteilung im Fetch-Log ergänzt:
    - `Fetch sector split (final)`
- Grund:
  - Sektor-Caps wurden beim Backfill teilweise umgangen; dadurch konnte Politics trotz Limits wieder überproportional in den Rohdaten-Pool gelangen.
- Erwarteter Effekt:
  - Stabilere Einhaltung der Zielverteilung über den gesamten Fetch-Prozess und bessere Sichtbarkeit unterrepräsentierter Sektoren.
- Rollback-Hinweis:
  - Änderungen in `worker/fetcher.py` zurücknehmen.

### 2026-03-01 20:16:53 Europe/Madrid | Worker (Sektor-Diagnostik in Run-Logs)
- Änderung:
  - Zusätzliche Sektor-Diagnostik im Pipeline-Run:
    - `scored` pro Sektor
    - `inserted` pro Sektor
  - Logzeile ergänzt:
    - `Run <type> sector counts: scored={...} inserted={...}`
- Grund:
  - Zur schnellen Ursachenanalyse bei Unterdeckung einzelner Sektoren (z. B. Sustainability/Biotechnologie/Cannabis) muss klar sein, ob das Defizit im Scoring oder in der Persistenz entsteht.
- Erwarteter Effekt:
  - Präzisere, schnellere Fehlerlokalisierung ohne manuelle DB-Forensik.
- Rollback-Hinweis:
  - Änderungen in `worker/jobs.py` zurücknehmen.

### 2026-03-01 20:23:01 Europe/Madrid | Worker (Query-Expansion im Fetch für Zielsektoren)
- Änderung:
  - Fetcher erweitert um sektorabhängige Query-Expansion für unterversorgte Bereiche:
    - `Sustainability`
    - `Biotechnologie`
    - `Cannabis`
    - `Kenya`
  - Pro konfigurierter Query wird zusätzlich eine deterministisch ausgewählte Expansion ausgeführt (stabile Last, keine unkontrollierte Explosion).
  - Deduplizierung innerhalb des Query-Tasks über kanonische URL ergänzt, damit Doppel-Treffer aus Basis+Expansion nicht unnötig Budget verbrauchen.
- Grund:
  - Reines Ranking reicht nicht aus, wenn relevante Rohstories bereits beim Fetch nicht ausreichend hereinkommen.
- Erwarteter Effekt:
  - Größere thematische Recherche-Tiefe im Fetch und bessere Rohdatenabdeckung in den Zielsektoren vor dem Scoring.
- Rollback-Hinweis:
  - Änderungen in `worker/fetcher.py` zurücknehmen.

### 2026-03-01 20:25:32 Europe/Madrid | Worker (Query-Expansion auf alle Sektoren + Subtopics)
- Änderung:
  - Query-Expansion im Fetch auf alle relevanten Bereiche ausgedehnt:
    - globale Sektoren (`AI`, `Crypto`, `Sustainability`, `Biotechnologie`, `Cannabis`, `Frequenzen`, `Politics`, `Kenya`)
    - lokale Räume und Themen (`Hamburg`, `Mallorca`, `Kenya`) inkl. Subtopic-spezifischer Erweiterungen.
  - Neuer Subtopic-Expansion-Pool eingeführt (`_SUBTOPIC_QUERY_EXPANSIONS`), damit die Recherche direkt die thematische Taxonomie trifft.
  - Variantenlogik pro Query erweitert auf:
    - Basisquery + bis zu 2 deterministische Expansionen (sektor- und subtopic-basiert), dedupliziert.
- Grund:
  - Relevante Themen sollten nicht nur im Scoring höher gewichtet werden, sondern bereits im Fetch breiter und gezielter eingesammelt werden.
- Erwarteter Effekt:
  - Größere thematische Recherchebreite über alle Räume und Kategorien bei weiterhin kontrollierter Last.
- Rollback-Hinweis:
  - Änderungen in `worker/fetcher.py` zurücknehmen.

### 2026-03-01 20:29:31 Europe/Madrid | Worker (Fetch-Balancing verschärft: Query/Direct Share-Caps)
- Änderung:
  - Dominanz-Caps im Fetch nachgeschärft:
    - Direct: `Politics`-Max-Share von `0.45` auf `0.25` gesenkt.
    - Query: neue Max-Share-Caps eingeführt:
      - `Politics`: `0.18`
      - `Mallorca`: `0.22`
  - Query-Limitberechnung nutzt nun zusätzlich `max_share_caps`.
- Grund:
  - Trotz erweiterter Recherche wurden Raw-Stories weiterhin von `Politics`/`Mallorca` überdominiert; Zielsektoren bekamen relativ zu wenig Platz.
- Erwarteter Effekt:
  - Ausgewogenere Rohdaten-Verteilung und bessere Chance auf sichtbare Sustainability/Biotechnologie/Cannabis-Items im finalen Dashboard.
- Rollback-Hinweis:
  - Änderungen in `worker/fetcher.py` zurücknehmen.

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

### 2026-03-01 14:36:00 Europe/Madrid | Web (Theme-Fix Lesbarkeit)
- Änderung:
  - Theme-Toggle auf Font-Awesome-Icons (`fa-sun`/`fa-moon`) umgestellt.
  - Light-Mode-Kontrast weiter erhöht für `HOT`-Badge, Relevanz-Badges und Meta-Zeile mit „Relevanz …“.
  - Relevanz-Legende im Light Mode weiter nachgeschärft (Header, Fließtext, `strong`, Skalenzahlen und Label).
  - Header-Layout nachjustiert: Theme-Toggle auf gleiche Höhe wie „Top-Storys“/„Sektoren“ gesetzt und vertikal mit den Stat-Pills zentriert.
- Grund:
  - Gewünschte Textfarbänderungen waren visuell nicht deutlich genug bzw. betrafen bisher nicht alle relevanten Elemente.
- Erwarteter Effekt:
  - Klar sichtbare Icon-Umschaltung und deutlich bessere Lesbarkeit der Relevanz-bezogenen Texte im White Mode.
- Rollback-Hinweis:
  - Letzte Änderungen in `app/templates/index.html` und `app/static/styles.css` zurücknehmen.

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
