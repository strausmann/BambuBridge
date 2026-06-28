# Architecture Decision Records (ADRs) — oberste Verbindlichkeit

Diese Regel lädt automatisch für jede (menschliche oder Claude-)Instanz in diesem Repo.

## Was ein ADR ist
Ein **Architecture Decision Record** dokumentiert eine bewusste, bindende Entscheidung im
Nygard-Format (**Context → Decision → Consequences**, plus „Options considered"). ADRs leben in
`docs/decisions/` (Format: `docs/decisions/_template.md`, Übersicht: `docs/decisions/README.md`).

## Autorität — ADRs gelten zuoberst
Bei Konflikten gilt diese Rangfolge:
1. **Akzeptierte ADRs** (`docs/decisions/`, Status `Accepted`) — **höchste Gültigkeit**
2. Guidelines (`docs/api-guideline.md`, `docs/database-guideline.md`)
3. README / Code-Konventionen / bestehender Code

Widerspricht eine Guideline oder der Code einem akzeptierten ADR, ist **das ein Fehler** — zu
beheben, oder es braucht einen **neuen, supersedenden ADR**. **Niemand — Mensch oder Claude-Agent —
darf einen akzeptierten ADR still übergehen.** Eine Guideline ist die *operative Umsetzung* der
ADR-Entscheidung, nicht deren Ersatz.

## Erstellen
1. `docs/decisions/_template.md` → `docs/decisions/NNNN-kurz-slug.md` (fortlaufend, nullgepolstert).
2. Felder ausfüllen: **Status** (`Proposed`), **Date**, **Deciders**, **Context**, **Decision**
   (positiver Aussagesatz „Wir werden …"), **Options considered** (gewählte Option + Alternativen
   mit Pro/Contra), **Consequences**, **References** (Issues/PRs, Guideline-Stellen `file:line`).
3. Neue Zeile in die Index-Tabelle in `docs/decisions/README.md` eintragen.

Status-Werte: `Proposed` · `Accepted` · `Deprecated` · `Superseded by NNNN`.

## Verwalten / Ändern
- Ein ADR wird **nach Annahme inhaltlich nicht mehr editiert.** Eine Änderung = **neuer** ADR, der
  den alten **supersedet**; der alte erhält Status `Superseded by NNNN`.
- Betrifft die Entscheidung Endpoints/Felder/DB/Config, im **selben PR** die zugehörige Guideline +
  README + `config.example.yaml` nachziehen.

## Verbindlich für Claude-Agents
- **Vor** jeder Spec/jedem Plan/jeder Implementierung die relevanten akzeptierten ADRs lesen und
  einhalten.
- Die Review-Agents (`network-`, `developer-`, `research-`, `security-reviewer`) prüfen Specs &
  Pläne **gegen die ADRs** und markieren jede Abweichung als **blockierend** (`NEEDS-CHANGES`).
- Eine neue Richtungsentscheidung wird **nicht still** umgesetzt, sondern zuerst als ADR
  (`Proposed`) vorgeschlagen und erst nach Annahme umgesetzt.
