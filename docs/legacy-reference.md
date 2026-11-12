# Legacy reference

BambuBridge 0.2.0 is a rebuild. The pre-0.2.0 code (a single-printer Python prototype with a Tailwind
PWA) was removed from the working tree in the commit `refactor(repo): remove legacy bridge code`. Its last
state is commit **`3855184`**; everything below stays readable via git:

```bash
git show 3855184:<path>
```

| Removed path | Last commit | Value for the sub-projects |
|---|---|---|
| `app/mqtt_ingest.py` | `3855184` | LAN MQTT ingest and AMS tray parsing; field names and edge cases for the printer-events sub-project |
| `app/cloud_library.py` | `3855184` | Bambu cloud filament-library import and mapping to Spoolman; reference for the cloud provider |
| `analysis/ENDPOINTS.md` | `3855184` | Schema-only (redacted) record of observed Bambu cloud endpoints; starting point for the provider work |
| `scripts/mitm_bambu_addon.py` | `3855184` | mitmproxy add-on used to capture cloud traffic; reusable for re-verifying endpoints |
| `docs/bambu-spoolman-bridge-concept.md` | `3855184` | Original concept (transport model, Spoolman extra fields, tag lifecycle) |
| `docs/api-guideline.md`, `docs/database-guideline.md` | `3855184` | Old API and SQLite guidelines; superseded by the new ADRs |
| `docs/filament-cloud-api-analysis-spec.md`, `docs/capture-runbook.md` | `3855184` | How the cloud API was analysed and captured |
| `docs/filament-preset-db-concept.md` | `3855184` | Preset-generation concept |
| `docs/esp32-slot-selector-concept.md` | `3855184` | ESP32 slot-selector idea |
| `docs/no-devmode-capability-matrix.md` | `3855184` | What is possible without printer Developer Mode |
| `docs/review-findings-backlog.md`, `docs/HANDOVER.md`, `docs/TODO-api-guideline-adoption.md` | `3855184` | Old review backlog and hand-over notes |

Unverified claims in these documents (for example cloud endpoints marked as hypotheses) must be
re-verified before they are relied on (rule R1).
