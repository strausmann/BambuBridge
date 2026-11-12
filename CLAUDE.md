# CLAUDE.md — Verbindliche Regeln für dieses Repo

Diese Datei wird von jeder AI-Instanz, die in diesem Repository arbeitet, gelesen.
Die folgenden Regeln sind **bindend (keine Ausnahmen)**.

## Hard rules

### R0 — Fehlerkultur (oberste Regel)
- Jeder Fehler wird **automatisch** analysiert (Root Cause), in `docs/learnings/lessons-learned.md`
  dokumentiert und mit einer konkreten Gegenmaßnahme gegen Wiederholung versehen (Rule / ADR /
  Test / Hook). Fehler werden offen benannt, nicht kaschiert. Details: `.claude/rules/error-handling.md`.

### R1 — Erst verifizieren, dann schlussfolgern; Öffentliches nur belegt
- **Vollständig analysieren/verifizieren, bevor eine Schlussfolgerung formuliert wird.** Alle
  relevanten Belege end-to-end prüfen (neuester Release-Tag **und** dessen gepinnte
  Abhängigkeiten, Build-/`Last-Modified`-Daten, Merge-/Fix-Daten, der tatsächliche Code bzw. das
  Artefakt) — keine Schlüsse aus Annahmen.
- **Doppelt für alles Öffentliche/Ausgehende** (GitHub Issues/PRs/Kommentare, Upstream-Reports):
  nur vollständig belegte Aussagen posten. Keine halb-verifizierte Schlussfolgerung zur Freigabe
  vorlegen und darauf bauen, dass der Nutzer die Lücken findet — die Prüfung gehört **davor**.

### R2 — Keine AI-Kennzeichnung in der Versionsverwaltung
- Niemals `Co-Authored-By`, `Claude-Session`, „Generated with Claude Code" oder sonstige
  AI-Selbstkennzeichnung in Commits, Pushes, PRs oder Issue-/PR-Texten. Sachliche, schlichte
  Messages.

### R3 — Superpowers immer nutzen
- Das Superpowers-Skill-Set ist installiert und wird **standardmäßig** verwendet (Brainstorming,
  Planung, TDD-Workflow etc.), wo es passt.

### R4 — Issue-getrieben, ein Issue je Feature/Bug
- Jede Änderung beginnt als GitHub-Issue (Templates in `.github/ISSUE_TEMPLATE/`).
  **Ein Issue → ein Branch → ein PR.** Branch-Präfixe: `feat/ fix/ docs/ refactor/ chore/`.

### R5 — Specs & Pläne vor Umsetzung von den Review-Agents prüfen lassen
- Vor der Finalisierung einer Spec/eines Plans schauen die Projekt-Agents
  (`.claude/agents/`: network-, developer-, research-, security-reviewer) darüber — im Zweifel
  2–3 Reviews —, damit keine Abweichung von den Guidelines entsteht.

### R6 — Conventional Commits + semantic-release
- Commits: `type(scope): subject`, **Scope verpflichtend** (`.github/SCOPES.md`). Versionierung
  übernimmt semantic-release; keine manuellen Versions-/CHANGELOG-Edits.

### R7 — ADRs zuoberst, Guidelines als operative Single Source of Truth
- **ADRs (`docs/decisions/`) haben die oberste Gültigkeit** — Details und Verfahren in
  `.claude/rules/adr.md`. Rangfolge bei Konflikten: **ADR > Guideline > Code/README**.
- `docs/api-guideline.md` und `docs/database-guideline.md` sind die bindende, operative
  Umsetzung der ADR-Entscheidungen. **Richtungswechsel/neue Features** dürfen Guidelines/ADRs
  erweitern — aber bewusst (neuer/supersedender ADR **+** Guideline-Update im selben PR), nie
  durch stilles Abweichen. Endpoint-/Feld-/Config-Änderung ⇒ Guideline + README +
  `config.example.yaml` zusammen aktualisieren.

### R8 — Erscheinungsbild aus `docs/brand/`
- Logo, Icons und Farben kommen ausschließlich aus [`docs/brand/`](docs/brand/README.md)
  (Bildzeichen „Drehscheibe“, Tokens in `docs/brand/tokens.css`). Keine Farben frei erfinden,
  keine Bambu-Lab-Markenelemente, kein Bambu-Grün. Abweichungen nur über eine Änderung an
  `docs/brand/` mit Begründung.
