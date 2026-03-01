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

### 2026-03-01 20:36:30 Europe/Madrid | Worker (Sektor-spezifisches Freshness-Fenster im Scoring)
- Änderung:
  - Freshness-Filter im Scoring von globalem Zeitfenster auf sektor-spezifische Max-Age-Logik erweitert.
  - Für unterrepräsentierte Sektoren wurden längere Zeitfenster aktiviert:
    - `Sustainability`: 120h
    - `Biotechnologie`: 96h
    - `Cannabis`: 96h
    - `Frequenzen`: 96h
- Grund:
  - Trotz vorhandener Raw-Stories wurden diese Sektoren durch das harte globale 48h-Fenster vor dem Scoring überproportional aussortiert.
- Erwarteter Effekt:
  - Mehr scorbare Kandidaten in den betroffenen Sektoren und damit bessere Chance auf persistierte Dashboard-Einträge.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` zurücknehmen.

### 2026-03-01 20:45:45 Europe/Madrid | Worker (Freshness-Fallback für Zielsektoren)
- Änderung:
  - Scoring um kontrollierten Freshness-Fallback erweitert:
    - Wenn in einem Zielsektor im primären Frischefenster keine Stories verbleiben, werden ältere, aber noch akzeptable Stories aus erweitertem Fallback-Fenster nachgezogen.
  - Fallback-Sektoren/Fenster:
    - `Sustainability`: bis 720h
    - `Biotechnologie`: bis 336h
    - `Cannabis`: bis 336h
  - Neue Diagnoselogs ergänzt:
    - `Scoring freshness drops by sector`
    - `Scoring freshness fallback used`
- Grund:
  - Reale Logs zeigten: Stories wurden korrekt gefetcht, aber vollständig vor dem Scoring-Ergebnis durch Frischefilter entfernt (v. a. Sustainability).
- Erwarteter Effekt:
  - Sektoren verschwinden nicht mehr vollständig aus dem Scoring, wenn kurzfristig wenig sehr frische Treffer vorhanden sind.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` zurücknehmen.

### 2026-03-01 20:53:14 Europe/Madrid | Config (Sustainability Feedspot RSS Integration)
- Änderung:
  - Zusätzliche direkte Sustainability-RSS-Quellen aus der Feedspot-Liste integriert (23 neue `direct_feeds` Einträge).
  - Quellen wurden unter `Sustainability` mit Subtopics `Global Regulations` und `Energy Transition` ergänzt.
- Grund:
  - Gewünscht war eine deutlich breitere Research-Abdeckung über konkrete Sustainability-RSS-Quellen statt reiner Scoring-Optimierung.
- Erwarteter Effekt:
  - Höhere Quellendiversität und mehr Rohstories im Sustainability-Sektor aus spezialisierten Nachhaltigkeits-Feeds.
- Rollback-Hinweis:
  - Ergänzten Block in `config/sources.yml` (Feedspot Sustainability 01-23) entfernen.

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

### 2026-03-01 20:57:37 Europe/Madrid | Config (Feedspot Sustainability Top-100 RSS Integration)
- Änderung:
  - Feedspot Sustainability-Liste auf vollständige Top-100 erweitert.
  - In `config/sources.yml` wurden die bisherigen Feedspot-Einträge (`01-23`) durch `Feedspot Sustainability 01-100` ersetzt.
  - Alle 100 von Feedspot gelisteten RSS-URLs wurden als `direct_feeds` unter dem Sektor `Sustainability` eingetragen.
- Grund:
  - Anforderung war, nicht nur Scoring zu optimieren, sondern die Rohdaten-Basis für Sustainability maximal zu verbreitern.
- Erwarteter Effekt:
  - Deutlich höhere Source-Coverage im Fetch für Sustainability und damit mehr potenzielle Stories für Scoring/Insert.
- Hinweis:
  - Die Feedspot-Top-100 enthält laut gelisteter OPML mehrere URL-Duplikate (u. a. wiederholte `greenly.earth`-Feeds); diese wurden bewusst 1:1 übernommen, weil explizit "alle 100" gewünscht war.
- Rollback-Hinweis:
  - Block `Feedspot Sustainability 01-100` in `config/sources.yml` entfernen oder auf vorherigen 23er-Stand zurücksetzen.

### 2026-03-01 21:15:40 Europe/Madrid | Config (Feedspot Cannabis Top-100 RSS Integration)
- Änderung:
  - Vollständige Feedspot-Liste `Top 100 Marijuana RSS Feeds` als `direct_feeds` unter `Cannabis` eingetragen.
  - Neue Einträge in `config/sources.yml`: `Feedspot Cannabis 01-100`.
  - Subtopic-Zuordnung für die neuen Feeds vorgenommen (`Legalization Tracker`, `Medical Cannabis`, `Industrial Hemp`, `Industry & Retail`, `Spain Germany Policy`, `Social Signal Watch`).
- Grund:
  - Anforderung war, alle 100 Cannabis-RSS-Feeds aus der präsentierten Feedspot-Seite in die Quellenkonfiguration zu übernehmen.
- Erwarteter Effekt:
  - Deutlich breitere Rohdatenabdeckung im Cannabis-Sektor bereits auf Fetch-Ebene (vor Scoring).
- Hinweis:
  - Bestehende Cannabis-Standardquellen (`Marijuana Moment`, `MJBizDaily`, `Reddit Trees`) bleiben zusätzlich aktiv.
- Rollback-Hinweis:
  - Block `Feedspot Cannabis 01-100` in `config/sources.yml` entfernen.

### 2026-03-01 21:22:03 Europe/Madrid | Config (Feedspot Kenya RSS Integration)
- Änderung:
  - 46 per MCP extrahierte Kenya-RSS-Links aus der Feedspot-Seite in `direct_feeds` eingetragen.
  - Neue Einträge in `config/sources.yml`: `Feedspot Kenya 01-46` unter `sector: "Kenya"`.
  - Einträge auf vorhandene Kenya-Subtopics verteilt (`Politics`, `Agriculture & Mount Kenya`, `Startup Ecosystem`, `Infrastructure & Public Projects`, `Business & Markets`, `Social Signal Watch`).
- Grund:
  - Anforderung war, die extrahierten Kenya-Feed-URLs direkt als Quellen im Fetcher zu hinterlegen.
- Erwarteter Effekt:
  - Breitere Kenya-Coverage bereits im Fetch und mehr Kenya-Rohstories vor dem Scoring.
- Hinweis:
  - Bestehende Kenya-Basisquellen (`Nation Africa`, `Business Daily Africa`, `Reddit Kenya`) bleiben zusätzlich aktiv.
- Rollback-Hinweis:
  - Block `Feedspot Kenya 01-46` in `config/sources.yml` entfernen.

### 2026-03-01 21:30:22 Europe/Madrid | Config (Feedspot Biotechnologie RSS Integration)
- Änderung:
  - 41 per MCP extrahierte Biotechnologie-RSS-Links aus Feedspot in `direct_feeds` eingetragen.
  - Neue Einträge in `config/sources.yml`: `Feedspot Biotech 01-41` unter `sector: "Biotechnologie"`.
  - Einträge auf bestehende Biotech-Subtopics verteilt (`Biotech Breakthroughs`, `Regulatory & Safety`, `Biotech Devices`, `Effective Microorganisms`, `Biotech Funding & M&A`, `Social Signal Watch`).
- Grund:
  - Anforderung war, die extrahierten Biotechnologie-RSS-Quellen direkt in `sources` zu ergänzen.
- Erwarteter Effekt:
  - Deutlich breitere Biotechnologie-Quellenabdeckung im Fetch vor dem Scoring.
- Hinweis:
  - Bereits vorhandene Biotechnologie-Basisquellen bleiben aktiv; dadurch gibt es bewusst teilweise URL-Überschneidungen.
- Rollback-Hinweis:
  - Block `Feedspot Biotech 01-41` in `config/sources.yml` entfernen.

### 2026-03-01 21:40:10 Europe/Madrid | Config (Feedspot Crypto Top-100 RSS Integration)
- Änderung:
  - Alle 100 per MCP extrahierten Crypto-RSS-Links aus der Feedspot-Seite in `direct_feeds` eingetragen.
  - Neue Einträge in `config/sources.yml`: `Feedspot Crypto 01-100` unter `sector: "Crypto"`.
  - Subtopic-Zuordnung für die neuen Quellen vorgenommen (`Crashes & Volatility`, `Altcoin Analysis`, `Policy & Market Impact`, `Exchanges & Infrastructure`, `Social Signal Watch`).
- Grund:
  - Anforderung war, die vollständige Feedspot Top-100 Crypto-Liste direkt in `sources` zu übernehmen.
- Erwarteter Effekt:
  - Signifikant breitere Rohdatenabdeckung im Crypto-Sektor vor dem Scoring.
- Hinweis:
  - Bestehende Crypto-Basisquellen (`CoinDesk`, `Cointelegraph`, `Reddit CryptoCurrency`) bleiben aktiv; dadurch sind einzelne URL-Duplikate (z. B. Cointelegraph) bewusst vorhanden.
- Rollback-Hinweis:
  - Block `Feedspot Crypto 01-100` in `config/sources.yml` entfernen.

### 2026-03-01 21:49:08 Europe/Madrid | Config (Feedspot AI Top-100 RSS Integration)
- Änderung:
  - Alle 100 per MCP extrahierten AI-RSS-Links aus der Feedspot-Seite in `direct_feeds` eingetragen.
  - Neue Einträge in `config/sources.yml`: `Feedspot AI 01-100` unter `sector: "AI"`.
  - Subtopic-Zuordnung für die neuen Quellen vorgenommen (`Labs & Models`, `Policy & Regulation`, `AI in Enterprise`, `AI Product Launches`, `Open Source & Research`, `Social Signal Watch`).
- Grund:
  - Anforderung war, die vollständige Feedspot Top-100 AI-Liste direkt in `sources` zu übernehmen.
- Erwarteter Effekt:
  - Signifikant breitere Rohdatenabdeckung im AI-Sektor vor dem Scoring.
- Hinweis:
  - Bestehende AI-Basisquellen bleiben aktiv; einzelne URL-Duplikate (z. B. MarkTechPost) sind dadurch bewusst vorhanden.
- Rollback-Hinweis:
  - Block `Feedspot AI 01-100` in `config/sources.yml` entfernen.


### 2026-03-01 21:27:18 Europe/Madrid | Config (Feedspot Best RSS Top-100 Integration)
- Änderung:
  - Alle 100 per MCP extrahierten RSS-Links aus `https://rss.feedspot.com/best_rss_feeds/` in `config/sources.yml` ergänzt.
  - Neue Einträge als `Feedspot Best 001-100` unter `direct_feeds` hinzugefügt.
  - Einordnung in bestehende Pipeline unter `sector: "Politics"` und `subtopic: "Global Power Moves"`.
- Grund:
  - Anforderung war, die vollständigen 100 allgemeinen Feedspot-Feeds direkt in `sources` aufzunehmen.
- Erwarteter Effekt:
  - Breitere globale Fetch-Abdeckung über viele Themenkategorien hinweg.
- Rollback-Hinweis:
  - Block `Feedspot Best 001-100` in `config/sources.yml` entfernen.

### 2026-03-01 21:34:05 CET | Config (Mallorca Zeitung RSS Sections Integration)
- Änderung:
  - Alle 63 auf `https://www.mallorcazeitung.es/rss.html` gelisteten RSS-Section-Feeds in `config/sources.yml` ergänzt.
  - Neue Einträge als `Mallorca Zeitung RSS 001-063` unter `direct_feeds` hinzugefügt.
  - Einordnung unter `sector: "Mallorca"` mit `subtopic: "Social Signal Watch"`.
- Grund:
  - Anforderung war, sämtliche RSS-Feeds der Mallorca-Zeitung-Seite in die Sources zu übernehmen.
- Erwarteter Effekt:
  - Deutlich höhere Mallorca-Quellenabdeckung im Fetch, inkl. lokaler und thematischer Unterrubriken.
- Rollback-Hinweis:
  - Block `Mallorca Zeitung RSS 001-063` in `config/sources.yml` entfernen.

### 2026-03-01 21:37:40 CET | Config (Diario de Mallorca RSS Integration)
- Änderung:
  - Alle 312 auf `https://www.diariodemallorca.es/rss.html` gelisteten RSS-Endpoints in `config/sources.yml` ergänzt.
  - Neue Einträge als `Diario de Mallorca RSS 001-312` unter `direct_feeds` hinzugefügt.
  - Einordnung unter `sector: "Mallorca"` mit `subtopic: "Social Signal Watch"`.
- Grund:
  - Anforderung war, alle per MCP extrahierten RSS-Links der Seite in die Sources zu übernehmen.
- Erwarteter Effekt:
  - Stark erhöhte Mallorca-Quellenabdeckung durch sections/microsites/blog-Feeds.
- Rollback-Hinweis:
  - Block `Diario de Mallorca RSS 001-312` in `config/sources.yml` entfernen.


### 2026-03-01 21:50:39 CET | Worker (Freshness + Sector Floors + Store Drop Visibility)
- Änderung:
  - `worker/scoring.py`:
    - sektor-spezifische Freshness-Fenster deutlich erweitert (`AI`, `Crypto`, `Sustainability`, `Biotechnologie`, `Cannabis`, `Frequenzen`, `Hamburg`, `Mallorca`, `Kenya`, `Politics`).
    - Fallback-Fenster für unterversorgte Sektoren erweitert (inkl. `Kenya`, `Hamburg`, `Mallorca`, `Frequenzen`, `AI`, `Crypto`).
    - neuer Mindestbestand je Sektor in der Scoring-Pipeline (`_SECTOR_MIN_SCORABLE_ITEMS`), der ältere Fallback-Kandidaten auch dann nachzieht, wenn ein Sektor zwar vorhanden ist, aber zu dünn besetzt ist.
  - `worker/store.py`:
    - Persistenz-Entscheidungen je Sektor nach Drop-Gründen instrumentiert (`hard_relevance_gate`, `min_story_score`, `duplicate_*`, `domain_cap`, `removed_stale_existing`, `pruned_by_sector_cap`).
    - neue Logzeile pro Sektor: `Store sector outcome [...] inserted=... drops=...`.
- Grund:
  - Fetch lieferte bereits hohe Volumina, aber viele Sektoren wurden durch Freshness und undurchsichtige Persistenz-Filter ausgedünnt.
- Erwarteter Effekt:
  - Mehr scorable Kandidaten in bislang unterversorgten Sektoren (vor allem `Kenya`, `Sustainability`, `Biotechnologie`, `Cannabis`, `Frequenzen`) und klare Transparenz, warum Stories im Store verworfen oder gepruned werden.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` und `worker/store.py` auf den vorherigen Stand zurücksetzen.


### 2026-03-01 21:56:50 CET | Worker (Store Gate Relax + Sector Score Floors)
- Änderung:
  - `worker/store.py`:
    - Hard-Relevance-Gate auf `Hamburg` und `Politics` begrenzt (für `Mallorca` und `Kenya` deaktiviert, um Over-Filtering zu reduzieren).
    - sektor-spezifische Mindestscore-Schwellen eingeführt (`_SECTOR_MIN_STORY_SCORE`) statt globalem Einheitswert:
      - `Biotechnologie=0.55`, `Sustainability=0.60`, `Frequenzen=0.55`, `Kenya=0.55`, `Cannabis=0.60`, `Mallorca=0.70`, `Hamburg=0.85`.
- Grund:
  - Aus den neuen Store-Drop-Logs: starke Drop-Last durch `hard_relevance_gate` (v. a. Mallorca/Kenya) und `min_story_score` in unterfüllten Sektoren.
- Erwarteter Effekt:
  - Mehr Netto-Inserts in bislang unterversorgten Sektoren ohne Politics/Hamburg-Qualitätsverlust.
- Rollback-Hinweis:
  - Änderungen in `worker/store.py` auf den vorherigen Stand zurücksetzen.

### 2026-03-01 22:02:20 CET | Tuning (Sector Cap + Gate Relax + Frequency/Hamburg Thresholds)
- Änderung:
  - `app/settings.py`:
    - `MAX_ITEMS_PER_SECTOR` Default von `16` auf `24` erhöht.
  - `worker/store.py`:
    - Hard-Relevance-Gate weiter gelockert: nur noch für `Politics` aktiv.
    - sektor-spezifische Mindestscore-Schwellen angepasst:
      - `Frequenzen` von `0.55` auf `0.45`
      - `Hamburg` von `0.85` auf `0.70`
- Grund:
  - Nach dem letzten Run waren sektorale Tagescaps und zu strenge Gates/Score-Schwellen die verbleibenden Bottlenecks.
- Erwarteter Effekt:
  - Mehr verfügbare Stories in unterfüllten Sektoren (`Frequenzen`, `Hamburg`, `Kenya`, `Mallorca`, `Biotechnologie`, `Cannabis`) bei weiterhin stabiler Politics-Qualität.
- Rollback-Hinweis:
  - Änderungen in `app/settings.py` und `worker/store.py` zurücksetzen.

### 2026-03-01 22:06:10 CET | Tuning (Balance Pass 2: Backfill + Domain Caps + Sector Targets)
- Änderung:
  - `worker/scoring.py`:
    - Freshness- und Fallback-Fenster für mehrere Sektoren weiter erweitert (u. a. `Kenya`, `Frequenzen`, `Sustainability`, `Biotechnologie`, `Cannabis`, `AI`, `Crypto`).
    - Mindestbestand je Sektor für Scoring-Backfill erhöht (`_SECTOR_MIN_SCORABLE_ITEMS`), damit unterversorgte Sektoren konsequenter mit älteren, noch relevanten Kandidaten aufgefüllt werden.
  - `worker/store.py`:
    - sektor-spezifische Mindestscore-Schwellen weiter feinjustiert (`AI`, `Crypto`, `Frequenzen`, `Kenya`, `Cannabis`).
    - Relaxed-Dedupe auf zusätzliche unterversorgte Sektoren erweitert (`Kenya`, `Sustainability`).
    - erweiterte Domain-Caps auf mehr Sektoren ausgedehnt und Erhöhung von `+2` auf `+4` gesetzt.
    - Mindest-Insert-Targets pro Sektor pro Run erhöht (`sector_minimum_targets`), um Breite systematisch aufzubauen.
- Grund:
  - Nach Pass 1 waren weiterhin `min_story_score`, `domain_cap` und zu dünner sektoraler Backfill die limitierenden Faktoren in mehreren Sektoren.
- Erwarteter Effekt:
  - Gleichmäßigere sektorale Verteilung mit höherem Netto-Inserts in `Kenya`, `Frequenzen`, `Cannabis`, `Biotechnologie`, `Sustainability` sowie stabiler Versorgung in `AI`/`Crypto`.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` und `worker/store.py` auf den vorherigen Stand zurücksetzen.

### 2026-03-01 22:10:35 CET | Final Tweaks (Cannabis/Frequenzen/AI Throughput)
- Änderung:
  - `worker/scoring.py`:
    - Freshness/Fallback für `Cannabis`, `Frequenzen`, `Kenya` weiter verlängert.
    - sektorale Backfill-Ziele erhöht (`_SECTOR_MIN_SCORABLE_ITEMS`), besonders für `Cannabis` und `Frequenzen`.
  - `worker/store.py`:
    - sektor-spezifische Mindestscores weiter gesenkt/angepasst (`AI`, `Sustainability`, `Frequenzen`, `Kenya`, `Cannabis`).
    - neue sektor-spezifische Social-Schwellen eingeführt (`_SECTOR_MIN_SOCIAL_STORY_SCORE`, `_SECTOR_MIN_SOCIAL_MENTIONS`).
    - sektorale Mindest-Insert-Targets erhöht (`AI`, `Sustainability`, `Cannabis`, `Frequenzen`, `Kenya`).
- Grund:
  - Letzte Engpässe lagen primär bei `min_story_score` und Social-Filtern in `AI/Cannabis/Frequenzen`.
- Erwarteter Effekt:
  - Höhere Netto-Inserts in `Cannabis` und `Frequenzen`, stabilere `AI`-Zufuhr bei gleichbleibender Gesamtqualität.
- Rollback-Hinweis:
  - Änderungen in `worker/scoring.py` und `worker/store.py` auf den vorherigen Stand zurücksetzen.

### 2026-03-01 22:24:40 CET | Final Tweaks (Capacity-Aware Store + Underfilled Sector Floors)
- Änderung:
  - `worker/store.py`:
    - Persistenz ist jetzt kapazitätsbewusst: pro Sektor werden nur noch Stories bis zur verbleibenden Tageskapazität (`MAX_ITEMS_PER_SECTOR - existing_rows`) eingefügt.
    - Sektoren, die bereits auf Tagescap sind, werden im Insert-Loop vollständig übersprungen (vermeidet Insert+Prune-Churn).
    - sektorale Mindestscore-Schwellen für unterfüllte Bereiche weiter gelockert:
      - `Hamburg`: `0.70 -> 0.60`
      - `Cannabis`: `0.45 -> 0.40`
      - `Frequenzen`: `0.30 -> 0.25`
- Grund:
  - Logs zeigten hohe Store-Zeit durch unnötige Inserts in bereits volle Sektoren sowie verbleibende Unterversorgung in `Hamburg`, `Cannabis` und `Frequenzen`.
- Erwarteter Effekt:
  - Deutlich weniger Store-Laufzeit/Churn bei vollen Sektoren und bessere Auffüllung der letzten offenen Slots in unterversorgten Sektoren.
- Rollback-Hinweis:
  - Änderungen in `worker/store.py` auf den vorherigen Stand zurücksetzen.

### 2026-03-01 22:27:20 CET | Hotfix (Frequenzen Score Floor)
- Änderung:
  - `worker/store.py`:
    - sektoraler Mindestscore für `Frequenzen` weiter gesenkt: `0.25 -> 0.20`.
- Grund:
  - Gewünscht zur besseren Auffüllung/Ergebnisdichte im Sektor `Frequenzen`.
- Erwarteter Effekt:
  - Mehr `Frequenzen`-Stories passieren die Store-Score-Hürde.
- Rollback-Hinweis:
  - Wert in `worker/store.py` wieder auf `0.25` setzen.

### 2026-03-01 22:33:10 CET | Final Tweaks (Frequenzen Social Thresholds)
- Änderung:
  - `worker/store.py`:
    - `Frequenzen` Social-Score-Schwelle gesenkt: `min_social_story_score 2.0 -> 1.8`.
    - `Frequenzen` Social-Mentions-Schwelle gesenkt: `min_social_mentions 2 -> 1`.
- Grund:
  - Letzter dominanter Drop-Grund in `Frequenzen` war `min_social_story_score`/`min_social_mentions`.
- Erwarteter Effekt:
  - Mehr `Frequenzen`-Stories passieren den Social-Filter und werden im Store berücksichtigt.
- Rollback-Hinweis:
  - Werte in `worker/store.py` auf `2.0` bzw. `2` zurücksetzen.

### 2026-03-01 22:45:00 CET | Web (HOT Badge nur nach Relevanz-Schwelle)
- Änderung:
  - `app/main.py`:
    - HOT-Badge-Markierung im Dashboard wurde von "neu in den letzten 6h" auf "Relevanz >= `HOURLY_BREAKING_THRESHOLD`" umgestellt.
    - Damit gilt HOT konsistent nur noch ab Score `7.0` (bzw. dem konfigurierten Threshold).
- Grund:
  - HOT sollte fachlich über Relevanz laufen, nicht über reinen Zeitstempel.
- Erwarteter Effekt:
  - Keine HOT-Badges mehr bei niedrigen Scores (z. B. ~2.x).
- Rollback-Hinweis:
  - In `app/main.py` die vorherige Zeitfenster-Logik (`latest_cutoff`) wiederherstellen.

### 2026-03-01 22:56:30 CET | Scoring/Store (Relevanz auf 1-10 Skala normalisiert)
- Änderung:
  - `worker/scoring.py`:
    - Finaler Story-Score wird nun auf eine echte `1-10` Skala normalisiert (`score = clamp(raw_score * 3.0, 1.0, 10.0)`).
    - Interne Rohwerte bleiben für Debug erhalten (`score_raw`), Ausgabe/DB nutzt den skalierten 1-10 Wert.
  - `worker/store.py`:
    - sektorale Mindestscore-Schwellen auf die neue 1-10 Skala umgerechnet.
    - sektorale Social-Score-Schwellen auf die neue 1-10 Skala umgerechnet.
- Grund:
  - Dashboard-Legende und HOT-Logik sollen mit derselben Relevanzskala arbeiten (1-10, HOT ab 7).
- Erwarteter Effekt:
  - Relevanzwerte im UI sind konsistent mit Legende und `HOURLY_BREAKING_THRESHOLD=7`.
- Rollback-Hinweis:
  - Score-Skalierung in `worker/scoring.py` entfernen und Schwellen in `worker/store.py` auf Vorwerte zurücksetzen.

### 2026-03-01 23:05:10 CET | Web (HOT Badge nur noch > 8.0)
- Änderung:
  - `app/settings.py`:
    - neue Konfiguration `HOT_BADGE_THRESHOLD` (Default `8.0`) eingeführt.
  - `app/main.py`:
    - HOT-Badge-Logik auf `story.score > HOT_BADGE_THRESHOLD` umgestellt (strictly greater).
- Grund:
  - Gewünscht: HOT nur für sehr hohe Relevanz, oberhalb von 8.
- Erwarteter Effekt:
  - Stories mit Score `<= 8.0` erhalten kein HOT-Badge mehr.
- Rollback-Hinweis:
  - HOT-Badge-Bedingung in `app/main.py` wieder auf den Breaking-Threshold zurückstellen.

### 2026-03-01 23:16:40 CET | Web/UI (Relevanz-Badge Gradient + HOT Dedupe)
- Änderung:
  - `app/templates/index.html`:
    - Relevanz-Dekoration nutzt jetzt die echte 1-10 Score-Skala direkt (kein altes 0-4.4 Rescaling mehr).
    - Pro Story wird zusätzlich `data-relevance-step` (`1..10`) gesetzt.
  - `app/static/styles.css`:
    - Relevanz-Badges folgen nun explizit den gleichen Farb-Gradient-Stufen wie die 1-10 Legende (1/2, 3/4, 5/6, 7/8, 9/10).
  - `app/main.py`:
    - HOT-Badge wird dedupliziert: inhaltlich ähnliche Stories werden geclustert, und pro Cluster erhält nur die Story mit dem höchsten Relevanz-Score das HOT-Badge.
- Grund:
  - Badge-Farben sollten konsistent zur Legende sein; HOT sollte nicht mehrfach für inhaltlich gleiche Meldungen erscheinen.
- Erwarteter Effekt:
  - Sichtbar konsistente Relevanzfarben auf allen Story-Badges.
  - Weniger HOT-Duplikate bei gleichartigen Meldungen aus verschiedenen Quellen.
- Rollback-Hinweis:
  - Änderungen in `app/main.py`, `app/templates/index.html` und `app/static/styles.css` auf den vorherigen Stand zurücksetzen.

### 2026-03-01 23:27:30 CET | Store (Content-Cluster Dedupe für Live-Feed)
- Änderung:
  - `app/settings.py`:
    - neue Konfiguration `MAX_SIMILAR_STORIES_PER_CLUSTER` (Default `2`).
  - `worker/store.py`:
    - neue inhaltliche Cluster-Key-Logik auf Basis von Titel+Summary.
    - pro Sektor wird beim Persistieren die Anzahl ähnlicher Meldungen pro Cluster gezählt.
    - wenn Cluster-Limit erreicht ist, wird Story mit Drop-Reason `duplicate_content_cluster` verworfen.
- Grund:
  - Gleiches Thema aus vielen Quellen sollte nicht mehrfach live erscheinen.
- Erwarteter Effekt:
  - Pro inhaltlichem Thema landen nur die besten 1-2 Stories im Live-Feed (default: 2).
- Rollback-Hinweis:
  - Cluster-Check in `worker/store.py` entfernen bzw. `MAX_SIMILAR_STORIES_PER_CLUSTER` erhöhen.

### 2026-03-01 23:35:20 CET | Ingestion/Store (HTML-Artefakte aus Titeln/Summaries entfernt)
- Änderung:
  - `worker/utils.py`:
    - `strip_html()` robuster gemacht (erst entity-decode, dann Tag-Strip, anschließend normalize).
  - `worker/fetcher.py`:
    - Feed-Titel werden beim Einlesen konsequent über `strip_html()` bereinigt.
  - `worker/store.py`:
    - Titel und Summary werden nach Übersetzung vor Persistierung zusätzlich per `strip_html()` bereinigt (Failsafe).
- Grund:
  - Verhindert sichtbare HTML-Artefakte wie `<a href=...>` im Dashboard.
- Erwarteter Effekt:
  - Keine HTML-Tags/Anchor-Reste mehr in Überschriften oder Zusammenfassungen.
- Rollback-Hinweis:
  - Änderungen in `worker/utils.py`, `worker/fetcher.py` und `worker/store.py` zurücksetzen.

### 2026-03-01 23:42:10 CET | Web/API (Feedspot-Quellnamen auf Publisher normalisiert)
- Änderung:
  - `app/main.py`:
    - neue Source-Name-Normalisierung für API/Template-Ausgabe.
    - Feedspot-Präfixe wie `Feedspot Sustainability 09 (...)` werden entfernt.
    - wenn nötig Fallback auf sauberen Publisher-Namen aus Domain (inkl. Overrides wie `nytimes.com -> The New York Times`).
- Grund:
  - Im UI sollen Publishernamen erscheinen, nicht Feedspot-Label.
- Erwarteter Effekt:
  - Metazeile zeigt konsistent Herausgeber wie `Mallorca Zeitung`, `The New York Times` statt `Feedspot ...`.
- Rollback-Hinweis:
  - Source-Name-Normalisierung in `app/main.py` entfernen.

### 2026-03-01 23:49:40 CET | Web/API (Countries/DE-RSSV Präfixe auf Publisher reduziert)
- Änderung:
  - `app/main.py`:
    - zusätzliche Source-Name-Normalisierung für Wrapper wie `Countries/...` und `DE RSSV ...`.
    - entfernt Länder-/Katalogpräfixe und Feed-Suffixe (`: ...`, ` - ...`, ` > ...`) zugunsten des Publishernamens.
    - Alias-Mapping ergänzt (u. a. `NYT -> The New York Times`, `EL PAIS -> EL PAÍS`).
- Grund:
  - UI soll echte Herausgeber anzeigen, nicht Katalog-/Wrapperbezeichner.
- Erwarteter Effekt:
  - z. B. `Countries/Spain: EL PAÍS: ...` -> `EL PAÍS`, `Countries/United States: NYT > ...` -> `The New York Times`.
- Rollback-Hinweis:
  - Zusatzlogik in `_normalize_source_name` zurücksetzen.
