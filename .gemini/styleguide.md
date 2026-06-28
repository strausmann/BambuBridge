# Gemini Code Assist — Style Guide (BambuBridge)

Beim Review dieses Repos gelten diese **Quellen der Wahrheit** (in dieser Rangfolge):

1. **ADRs** in `docs/decisions/` — oberste Verbindlichkeit.
2. `docs/api-guideline.md` — `/api/v1`, snake_case, Error-Envelope `{detail,error_code}`,
   `X-API-Key`-Auth auf mutierenden Routen, HTTPS via Proxy.
3. `docs/database-guideline.md` — SQLite (WAL, `user_version`-Migrationen, definierte Tabellen).
4. `CLAUDE.md` (Projektregeln) und `.github/SCOPES.md` (Commit-Scopes).

Hinweise für Findings:
- Konkret und **nach Severity** priorisiert melden.
- Stack: Python 3, FastAPI (lifespan), paho-mqtt, httpx, SQLite, Tailwind-PWA.
- **Drucker-Schreibpfade sind bewusst „gated"** (Dev-Mode, `allow_k_write`/`allow_unload`) — das ist
  Absicht, kein Bug.
- Keine Secrets/Tokens hardcoden oder loggen.
