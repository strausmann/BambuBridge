# Gemini Code Assist — style guide (BambuBridge)

When reviewing this repository, these are the **sources of truth** (in this order):

1. **ADRs** in `docs/decisions/` — highest authority.
2. `CLAUDE.md` (project rules) and `.github/SCOPES.md` (commit scopes).
3. `docs/brand/` for anything visual.

Hints for findings:
- Report concretely and **prioritised by severity**.
- Layout: `backend/` (Python, FastAPI, MQTT, SQL database) and `frontend/` (progressive web app).
  The pre-0.2.0 code is gone; `docs/legacy-reference.md` explains where to find it in git history.
- **Printer write paths are deliberately gated** (Developer Mode, explicit opt-in settings) — that is
  intended, not a bug.
- Never hardcode or log secrets, tokens, serial numbers or LAN access codes.
- Commit messages follow Conventional Commits with a mandatory scope and carry no emoji.
