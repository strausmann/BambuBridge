# PR-Review-Findings (Gemini / Copilot) — vollständig abarbeiten

Lädt automatisch für jede (menschliche oder Claude-)Instanz.

## Grundsatz
Jeder PR wird von KI-Reviewern (Gemini Code Assist, GitHub Copilot) kommentiert. **Jedes Finding
MUSS einen Status bekommen** — keines bleibt unbeantwortet:
- **Behoben** → Fix committen und im Finding-Thread kurz vermerken (was/wo, ggf. Commit-SHA).
- **False Positive / bewusst nicht umgesetzt** → im Finding-Thread **mit Begründung** antworten,
  warum es nicht zutrifft bzw. nicht umgesetzt wird.

Stilles Übergehen ist verboten (vgl. R0 Fehlerkultur).

## Vorgehen (auch für Claude-Agents)
1. Vor dem Merge **alle** Review-Threads holen:
   - `gh pr view <n> --repo <owner>/<repo> --comments`
   - Inline-Findings: `gh api repos/<owner>/<repo>/pulls/<n>/comments`
2. Findings nach Severity ordnen; echte Bugs/Security zuerst.
3. Pro Finding: **fixen** oder **als False Positive begründen** — und **antworten**.
4. Erst **mergen**, wenn jedes Finding einen Status hat (behoben / abgelehnt-mit-Begründung) **und**
   CI grün ist.

## Auf ein Inline-Finding antworten
```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments/<comment_id>/replies -f body="<Antwort>"
```
Für allgemeine PR-Kommentare: `gh pr comment <n> --repo <owner>/<repo> --body "<text>"`.
