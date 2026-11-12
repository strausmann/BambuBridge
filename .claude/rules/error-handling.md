# Error culture — top rule (automatic post-mortem)

This rule loads automatically for every (human or Claude) contributor and applies **always and first**.

## Principle
Mistakes are allowed — **making the same mistake twice is not.** As soon as a mistake happens (wrong
assumption, broken command, wrong conclusion, misbehaviour, regression), proceed **automatically and
without being asked**:

1. **Analyse** — find the **root cause** (not just the symptom). What exactly happened, why, and which
   assumption or action triggered it?
2. **Document** — add an entry to `docs/learnings/lessons-learned.md` (format: `docs/learnings/README.md`):
   what happened · root cause · impact · fix/prevention.
3. **Prevent recurrence** — establish a **concrete measure**, depending on the kind of mistake:
   - Behaviour/process mistake → new or extended **rule** (`.claude/rules/`) and, if useful, a memory note.
   - Decision/architecture mistake → **ADR** (`docs/decisions/`, see `.claude/rules/adr.md`).
   - Code/regression mistake → a **test** or guard that catches the case in future.
   - Tooling/automation that must bite → a **hook** in `settings.json`.

## Attitude
- **Name mistakes openly**, including your own. "That was wrong, cause X, measure Y" beats silent correction.
- This rule has **priority**: even when a task is urgent, a recognised mistake is analysed, documented
  and secured before work simply continues.
- It is closely tied to rule R1 (verify before concluding) — many mistakes come from insufficient
  up-front verification.
