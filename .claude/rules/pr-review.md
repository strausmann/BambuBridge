# PR review findings (Gemini / Copilot) — work through all of them

This rule loads automatically for every (human or Claude) contributor.

## Principle
Every PR is commented on by AI reviewers (Gemini Code Assist, GitHub Copilot). **Every finding MUST get
a status** — none stays unanswered:
- **Fixed** → commit the fix and note it briefly in the finding thread (what/where, commit SHA if useful).
- **False positive / deliberately not applied** → reply in the finding thread **with reasoning**.

Silently ignoring a finding is forbidden (see R0 error culture).

## Procedure (also for Claude agents)
1. Before merging, fetch **all** review threads:
   - `gh pr view <n> --repo <owner>/<repo> --comments`
   - inline findings: `gh api repos/<owner>/<repo>/pulls/<n>/comments`
2. Order findings by severity; real bugs and security issues first.
3. For each finding: **fix** it or **justify it as a false positive** — and **reply**.
4. **Merge** only when every finding has a status (fixed / rejected with reasoning) **and** CI is green.

## Replying to an inline finding
```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments/<comment_id>/replies -f body="<reply>"
```
For general PR comments: `gh pr comment <n> --repo <owner>/<repo> --body "<text>"`.
