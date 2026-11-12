# Review-Findings → Lösungen (Begründungsquelle der GitHub-Issues)

> Aus dem Code- + Architektur-Review (zwei Entwickler-Agenten, Branch `claude/dazzling-sagan-vdro2v`).
> Jede Zeile entspricht einem GitHub-Issue (Zuordnung am Ende dieses Dokuments); das Dokument bleibt
> als Begründungsquelle bestehen. Jede Zeile = ein „Issue" mit konkreter Lösung. Bezug: `docs/api-guideline.md`, `docs/database-guideline.md`,
> `docs/no-devmode-capability-matrix.md`.

Legende: 🔴 must-fix · 🟠 should-fix · 🟡 nice-to-have · Status: [ ] offen / [~] geplant / [x] erledigt

## 🔴 Kritisch

- **BR-1 [x] Keine Auth auf druckersteuernder API.** Lösung: `X-API-Key`-Dependency (Guideline §8),
  Key aus `security.api_key`/`BRIDGE_API_KEY`, auf allen mutierenden Routen; Deployment-Profile
  HomeLab vs. Werkstatt. Default: ohne Key = Warnung + nur hinter Proxy.
  → erledigt: `require_api_key` auf allen POST-Routen, Error-Envelope `{detail,error_code}`
  (`APIError` + Handler), Startup-Warnung bei fehlendem Key, `security:` in `config.example.yaml`.
  Tests: `tests/test_app_lifespan_auth.py`.
- **BR-2 [ ] Ungelockter Cross-Thread-Zugriff** auf `live_trays`, `_last_cali`, `_pending_assign`,
  `_staged_slot`, `ams_identity` (MQTT-Thread vs. FastAPI-Threadpool → „dict changed size").
  Lösung: ein `state_lock` um **alle** Zugriffe; Iterationen über Kopien.
- **BR-3 [ ] In-Memory-State geht bei Neustart verloren** (`_pending`, `_pending_assign`,
  `_staged_slot`). Lösung: in SQLite persistieren — `onboarding_pending`, `slot_assign`, `kv`
  (DB-Guideline §3). `live_trays`/`_last_cali` bleiben flüchtig (Cache).
- **BR-4 [ ] `_staged_slot` global (ein Slot)** → Mehrnutzer/Retry überschreibt. Lösung:
  session-/clientbezogen in `kv` (`staged_slot:<session>`); RMW unter Lock.
- **BR-5 [x] `bridge = Bridge()` beim Import** (braucht config.yaml, bricht uvicorn/Tests) +
  veraltetes `@app.on_event`. Lösung: Lazy-Init im **FastAPI `lifespan`**.
  → erledigt: `bridge` wird im `lifespan` erzeugt (Import braucht keine config.yaml mehr),
  `@app.on_event` entfernt, sauberes Shutdown via `Bridge.stop()`/`BambuPrinterMQTT.stop()`.
  Tests: `tests/test_app_lifespan_auth.py`.
- **BR-6 [ ] Doku überzeichnet „implementiert"** für Cloud-Push/k-Set (hängt an unbestätigtem
  Endpoint / evtl. Dev-Mode). Lösung: in den Docs als „blockiert/gated, ungetestet" labeln
  (Capability-Matrix referenzieren).

## 🟠 Wichtig

- **BR-7 [ ] Spoolman zu „chatty"** (`find_spool_by_extra` = Full-Scan N+1; mehrere G/PUTs pro
  Tray-Push auch ohne Änderung). Lösung: Spoolman-Filter-Query bzw. einmal-Index; `active_tray`/
  `location` nur bei Änderung schreiben (wie `_last_cali`-Muster).
- **BR-8 [ ] `set_extra` GET-modify-PUT racy** (last-writer-wins auf gesamtes `extra`). Lösung:
  pro-Spool serialisieren; nur geänderte Keys schreiben.
- **BR-9 [ ] `tray_now`-Mapping** verfehlt Virtual-Tray (255) + 0x80-Bereich (Extern/2.-Extruder)
  → falsche Zuordnung. Lösung: Firmware-Ranges spiegeln (`DevExtruderSystem.cpp`); im Write-Pfad
  (`set_k`/`unload`) Virtual-Tray-Sonderfall beachten (`get_tray_id_by_ams_id_and_slot_id`).
- **BR-10 [ ] Job-Ende liest evtl. veraltetes `remain`** → Unterzählung. Lösung: bei Jobende
  `pushall` triggern bzw. auf den nächsten Tray-Push nach Ende buchen. „genau" → „remain-Delta-genau".
- **BR-11 [ ] MQTT-Schreibpfad ohne Verbindungsprüfung** (`publish_command` gibt trotzdem 200) +
  schwere Arbeit im MQTT-Callback (Keepalive-Risiko) + kein Watchdog/Token-Refresh. Lösung:
  `is_connected()`-Check → 503; Heavy-Work in Worker-Queue; Reconnect-Watchdog; Token-Ablauf
  (~3 Mon.) im UI/Log anzeigen.
- **BR-12 [ ] Importe ohne Idempotenz-Lock** (paralleler `cloud/import` → Duplikate). Lösung:
  Importe global serialisieren (Lock); Dedup über RFID/`cloud_id` beibehalten.
- **BR-13 [ ] `fetch_cloud_filaments` paginiert nicht** (nur erste Seite). Lösung: Offset-Schleife
  bis < `limit`.
- **BR-14 [ ] `material_family` naiv** (load-bearing für Kompatibilitätsschutz). Lösung: härten
  (Bekannte-Typen-Tabelle, CF/HT-Varianten, „Support for …" abfangen).

## 🟡 Nice-to-have

- **BR-15 [ ] `_last_cali`-Typannotation** falsch (`dict[str,int]` statt Tupel). Lösung: korrigieren.
- **BR-16 [ ] Leer-String-Extra `'""'`** statt Key löschen. Lösung: leere Extras entfernen.
- **BR-17 [ ] README ↔ Routen-Drift** (fehlende Routen, paho v1/v2-Latenz). Lösung: Routen-Tabelle
  aus echter Routenliste generieren; paho-Pin kommentieren.
- **BR-18 [ ] Tailwind Play-CDN** (offline unbrauchbar, Drittskript). Lösung: für Produktion
  Tailwind kompiliert ausliefern (Build-Stage).
- **BR-19 [ ] CORS** nicht gesetzt. Lösung: bei Cross-Origin explizit `allow_origins` (kein `*`).
- **BR-20 [ ] `get_version`-`ams_id` ↔ `print.ams.ams[].id`** Annahme. Lösung: am echten 2×-AMS
  verifizieren.

## Umsetzungs-Reihenfolge (ohne Drucker/Capture machbar zuerst)

1. **BR-5** (Lazy-Init/lifespan) — entsperrt sauberen Start/Tests.
2. **BR-1** (Auth) + **BR-2** (Locks) — Sicherheit/Stabilität.
3. **BR-3/BR-4** (State → SQLite, DB-Guideline) — Robustheit.
4. **BR-7/BR-8** (Spoolman-Schreiblast/Race).
5. **BR-6** (Doku-Ehrlichkeit) — laufend.
6. Drucker-/Capture-abhängig: **BR-9/BR-10/BR-11** (am echten 2×-AMS), Cloud-Endpoint/`put_setting`.

## Zuordnung zu GitHub-Issues

Der frühere Ordner `issues/` wurde am 2026-11-12 in echte GitHub-Issues überführt (Ordner entfernt). Die IDs `BR-xx`/`F-xx` in diesem und anderen Dokumenten sind die Ursprungs-IDs; die Spalte „Milestone“ nennt den Stand zur Überführung.

| ID | Issue | Milestone | Titel |
|---|---|---|---|
| BR-01 | [#8](https://github.com/strausmann/BambuBridge/issues/8) | 0.1.0 | fix(api): API ohne Authentifizierung — X-API-Key auf mutierenden Routen erzwingen |
| BR-02 | [#9](https://github.com/strausmann/BambuBridge/issues/9) | 0.1.x | fix(mqtt): ungelockter Cross-Thread-Zugriff auf geteilte Dicts |
| BR-03 | [#10](https://github.com/strausmann/BambuBridge/issues/10) | 0.1.x | fix(db): In-Memory-State überlebt Neustart nicht |
| BR-04 | [#11](https://github.com/strausmann/BambuBridge/issues/11) | Backlog | fix(esp32): _staged_slot ist global (ein Slot) |
| BR-05 | [#12](https://github.com/strausmann/BambuBridge/issues/12) | 0.1.0 | fix(api): Bridge() beim Import und veraltetes on_event — Lazy-Init im lifespan |
| BR-06 | [#13](https://github.com/strausmann/BambuBridge/issues/13) | 0.1.x | docs(docs): Doku überzeichnet „implementiert“ bei ungetesteten Pfaden |
| BR-07 | [#14](https://github.com/strausmann/BambuBridge/issues/14) | 0.1.x | perf(spoolman): Spoolman-Aufrufe zu chatty (N+1) |
| BR-08 | [#15](https://github.com/strausmann/BambuBridge/issues/15) | 0.1.x | fix(spoolman): set_extra (GET-modify-PUT) ist racy |
| BR-09 | [#16](https://github.com/strausmann/BambuBridge/issues/16) | Backlog | fix(consumption): tray_now-Mapping verfehlt Virtual-Tray und 0x80-Bereich |
| BR-10 | [#17](https://github.com/strausmann/BambuBridge/issues/17) | Backlog | fix(consumption): Job-Ende liest evtl. veraltetes remain |
| BR-11 | [#18](https://github.com/strausmann/BambuBridge/issues/18) | 0.1.x | fix(mqtt): MQTT-Schreibpfad und Robustheit (Verbindungsprüfung, Watchdog, Token-Ablauf) |
| BR-12 | [#19](https://github.com/strausmann/BambuBridge/issues/19) | 0.1.x | fix(cloud): Importe ohne Idempotenz-Lock (Duplikate bei parallelem Lauf) |
| BR-13 | [#20](https://github.com/strausmann/BambuBridge/issues/20) | Backlog | fix(cloud): Cloud-Fetch paginiert nicht |
| BR-14 | [#21](https://github.com/strausmann/BambuBridge/issues/21) | 0.1.x | fix(tags): material_family zu naiv (Kompatibilitätsschutz) |
| BR-15 | [#22](https://github.com/strausmann/BambuBridge/issues/22) | 0.1.x | chore(ams): _last_cali-Typannotation korrigieren |
| BR-16 | [#23](https://github.com/strausmann/BambuBridge/issues/23) | 0.1.x | chore(spoolman): Leer-String-Extra statt Key löschen |
| BR-17 | [#24](https://github.com/strausmann/BambuBridge/issues/24) | 0.1.x | docs(docs): README-Routentabelle driftet, paho-Pin absichern |
| BR-18 | [#25](https://github.com/strausmann/BambuBridge/issues/25) | Backlog | chore(ui): Tailwind vom Play-CDN auf kompilierten Build umstellen |
| BR-19 | [#26](https://github.com/strausmann/BambuBridge/issues/26) | Backlog | chore(api): CORS nicht konfiguriert |
| BR-20 | [#27](https://github.com/strausmann/BambuBridge/issues/27) | Backlog | chore(mqtt): get_version-ams_id gegen print.ams.id verifizieren |
| F-01 | [#28](https://github.com/strausmann/BambuBridge/issues/28) | 0.2.0 | feat(api): API-Guideline übernehmen (Prefix, Auth, Envelope) |
| F-02 | [#29](https://github.com/strausmann/BambuBridge/issues/29) | 0.2.0 | feat(db): SQLite-Datenmodell und Migrationen implementieren |
| F-03 | [#30](https://github.com/strausmann/BambuBridge/issues/30) | Backlog | feat(cloud): Cloud-Endpoints per mitmproxy bestätigen |
| F-04 | [#31](https://github.com/strausmann/BambuBridge/issues/31) | Backlog | feat(mqtt): Druckerverhalten ohne Developer-Mode (2×AMS) verifizieren |
| F-05 | [#32](https://github.com/strausmann/BambuBridge/issues/32) | Backlog | feat(cloud): Cloud-Library-Import scharfschalten |
| F-06 | [#33](https://github.com/strausmann/BambuBridge/issues/33) | Backlog | feat(presets): Preset-Push (Drittanbieter-Profile ins Bambu-Konto) |
| F-07 | [#34](https://github.com/strausmann/BambuBridge/issues/34) | Backlog | feat(esp32): ESP32-2432S028 Slot-Selektor (Firmware) |
| F-08 | [#35](https://github.com/strausmann/BambuBridge/issues/35) | Backlog | feat(ui): PWA Slot-Bind-Flow (Web-UI) |

Milestones: `0.1.0` (ausgeliefert), `0.1.x` (Fehlerbehebungen, Patch), `0.2.0` (Features, Minor), `Backlog` (durch die Neuausrichtung neu zu bewerten, siehe jeweils den Hinweis im Issue).
