# Tracking: API-Guideline-Adoption

> Checkliste zum GitHub-Issue [#28](https://github.com/strausmann/BambuBridge/issues/28) (F-01, Milestone 0.2.0).
> Das Issue führt den Fortschritt; diese Datei bleibt als Detail-Checkliste bestehen.

**Quelle der Wahrheit:** [`docs/api-guideline.md`](./api-guideline.md)

## Ziel
Verbindlicher API-Standard, damit bei Teilentwicklungen keine neuen Namen/Annahmen/Endpoints/
Felder mehr entstehen — für Bridge **und** Clients (PWA, ESP32).

## Adoptions-Checkliste
- [ ] **Versionierung:** alle Routen unter `/api/v1` (Audit-Mapping in Guideline §12)
- [ ] **Auth:** `X-API-Key` auf allen mutierenden Routen (`security.api_key` / `BRIDGE_API_KEY`)
- [ ] **Error-Envelope:** `{detail, error_code}` durchgängig
- [ ] **Feld-Glossar (§5)** in Code + Clients durchsetzen (keine Synonyme)
- [ ] **Spoolman-Extra-Fields (§10)** vereinheitlichen (`tag`, `active_tray`, `cali_idx`, `k_value`, …)
- [ ] **Config-Schema (§11)** + `config.example.yaml` synchron halten
- [ ] **README-Routen-Tabelle** aus der echten Routenliste pflegen (Drift beheben)
- [ ] Clients (PWA/ESP32) auf v1-Pfade umstellen

## Bezug zu den Review-Findings (🔴)
- Fehlende **Auth** auf druckersteuernder API → §8.
- Fehlende **Versionierung/Envelope-Konsistenz** → §2/§4.
- **README ↔ Routen-Drift** → §13.
(Code-/Architektur-Review: siehe Branch-History `claude/dazzling-sagan-vdro2v`.)

## Pflege
PRs, die Endpoints/Felder/Configs ändern, müssen `docs/api-guideline.md` (+ README +
`config.example.yaml`) mit aktualisieren. Breaking Changes → neue API-Version + Deprecation.
