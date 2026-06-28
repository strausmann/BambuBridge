# Fehlerkultur — oberste Regel (automatischer Post-Mortem)

Diese Regel lädt automatisch für jede (menschliche oder Claude-)Instanz und gilt **immer und zuoberst**.

## Grundsatz
Fehler sind erlaubt — **denselben Fehler zweimal zu machen, nicht.** Sobald ein Fehler passiert
(falsche Annahme, kaputter Befehl, falsche Schlussfolgerung, Fehlverhalten, Regressionen), wird
**automatisch und ohne Aufforderung** so vorgegangen:

1. **Analysieren** — die **Root Cause** ermitteln (nicht nur das Symptom). Was genau ist passiert,
   warum, und was war die auslösende Annahme/Handlung?
2. **Dokumentieren** — einen Eintrag in `docs/learnings/lessons-learned.md` ergänzen
   (Format siehe `docs/learnings/README.md`): Was passiert ist · Root Cause · Impact ·
   Fix/Prävention.
3. **Wiederholung verhindern** — eine **konkrete Maßnahme** etablieren, je nach Art:
   - Verhaltens-/Prozessfehler → neue/erweiterte **Rule** (`.claude/rules/`) + ggf. **Memory**.
   - Entscheidungs-/Architekturfehler → **ADR** (`docs/decisions/`, siehe `.claude/rules/adr.md`).
   - Code-/Regressionsfehler → **Test** oder Guard, der den Fall künftig abfängt.
   - Tooling/Automation, das hart greifen muss → **Hook** in `settings.json`.

## Haltung
- **Fehler offen benennen**, nicht kaschieren — auch eigene. Lieber transparent „das war falsch,
  Ursache X, Maßnahme Y" als stillschweigend korrigieren.
- Diese Regel hat **Vorrang**: Auch wenn eine Aufgabe drängt, wird ein erkannter Fehler erst
  analysiert + dokumentiert + abgesichert, bevor einfach weitergemacht wird.
- Bezieht sich eng auf [[verify-before-concluding]] — viele Fehler entstehen aus unzureichender
  Vorab-Prüfung.
