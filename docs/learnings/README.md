# Learnings / Lessons Learned

Wird vom **Fehlerkultur**-Prozess gespeist (`.claude/rules/error-handling.md`): Jeder gemachte
Fehler wird hier dokumentiert, damit er sich **nicht wiederholt**.

- **Log:** [`lessons-learned.md`](lessons-learned.md) — chronologisch, neueste oben.
- **Wann eintragen:** sobald ein Fehler erkannt + analysiert ist (automatisch, ohne Aufforderung).
- **Wohin die Gegenmaßnahme:** Verhalten → Rule/Memory · Entscheidung → ADR (`docs/decisions/`) ·
  Code → Test/Guard · harte Automation → Hook.

## Eintrags-Format
```markdown
## YYYY-MM-DD — <Kurztitel>
- **Was passiert ist:** …
- **Root Cause:** …
- **Impact:** …
- **Fix / Prävention:** … (welche Rule/ADR/Test/Hook wurde ergänzt)
```
