# Erscheinungsbild der BambuBridge

Verbindlich für alle, die an der Oberfläche, an Icons, an der README oder an Release-Grafiken arbeiten – Menschen wie AI-Agents.

**Stand:** 2026-11-12, vom Betreiber gewählt: Bildzeichen **Drehscheibe**, Primärfarbe **Brückenblau**.

## Bildzeichen

Die Drehscheibe: eine Spulennabe in der Mitte, vier Knoten ringsum (Drucker, Spulenverwaltung, Etikettendruck, Webhooks). Sie steht für die Aufgabe der Bridge: Ereignisse annehmen und an angebundene Systeme verteilen.

| Datei | Verwendung |
|---|---|
| `logos/drehscheibe-light-mark.svg` | Bildzeichen auf hellem Grund, App-Icon, Favicon |
| `logos/drehscheibe-dark-mark.svg` | Bildzeichen auf dunklem Grund |
| `logos/drehscheibe-light-lockup.svg` | Bildzeichen mit Wortmarke, heller Grund (README, Anmeldeseite) |
| `logos/drehscheibe-dark-lockup.svg` | Bildzeichen mit Wortmarke, dunkler Grund |

- Das Bildzeichen ist ein abgerundetes Quadrat mit eigener Fläche; es braucht keinen zusätzlichen Rand und funktioniert ab 16 px.
- Die Wortmarke „bambubridge“ ist in Kleinbuchstaben aus Linien gezeichnet; sie braucht keine Schriftdatei. Nicht durch gesetzten Text ersetzen.
- PNG-Größen (Favicon, PWA-Icons 192/512, maskable) werden beim Build aus den SVGs erzeugt, nicht von Hand gepflegt.

## Farben

Quelle der Wahrheit: [`tokens.css`](tokens.css) (Tailwind 4); `frontend/src/design/tokens.css` beginnt mit einer wortgleichen Kopie (ein Test hält beide gleich). Aufbau wie im Label Printer Hub und in Kept: Skalen als `@theme`, semantische Rollen als `@theme inline`, Light als Standard, Dark per System und per `data-theme`.

| Rolle | Light | Dark | Verwendung |
|---|---|---|---|
| `primary` | `#006E99` | `#4FB9EB` | Hauptaktionen, aktive Navigation, Bildzeichen |
| `accent` | `#A1376E` | `#F183B6` | sparsam: Hervorhebung, Regel-/Integrations-Kennzeichen |
| `bg` / `surface` / `sunken` | `#F3F7FB` / `#FBFEFF` / `#E9EDF1` | `#0D1218` / `#161C23` / `#1E252C` | Flächen |
| `ink` / `ink-2` / `ink-3` | `#20262C` / `#4B5259` / `#5F656D` | `#F0F4F7` / `#C3C8CE` / `#9FA5AC` | Text |
| `ok` / `warn` / `bad` / `info` | `#00704E` / `#8C5007` / `#B02B27` / `#006E99` | `#5ED8A9` / `#FCB26F` / `#FF958A` / `#83D1F9` | nur Zustände |

- Alle Textpaare erfüllen WCAG 2.2 AA (niedrigster Wert 4.87:1); Eingaberahmen ≥ 3:1. Der Kontrast-Test `frontend/src/design/tokens.test.ts` hält das für jedes Paar aus `TEXT_PAIRS` (`tokens.ts`) fest, hell und dunkel.
- Zustand nie nur über Farbe zeigen (zusätzlich Text oder Symbol).

## Abgrenzung zu Bambu Lab

Die BambuBridge ist kein Produkt von Bambu Lab und darf nicht so aussehen.

- **Kein** Bambus-Motiv, **kein** stilisiertes „B“ aus Streifen, **kein** Bambu-Lab-Logo, auch nicht in Screenshots als Deko.
- **Keine** grün-dominante Fläche. Bambu-Grün `#00AE42` ist tabu; Abstand der Primärfarbe ΔE2000 ≈ 49. Grün erscheint nur als Statusfarbe `ok` (bläulicher, Hue 165°).
- Den Namen „Bambu“ nur als Teil des Projektnamens bzw. zur sachlichen Beschreibung der unterstützten Geräte verwenden, nie so, dass eine Verbindung zu Bambu Lab nahegelegt wird.

## Schrift

Entschieden am 12.11.2026:

| Rolle | Schrift | Token |
|---|---|---|
| Überschriften | Space Grotesk (variabel, 300–700) | `--font-display` |
| Text und Bedienelemente | Inter (variabel, 100–900) | `--font-sans` |
| Code, Tokens, Kennungen | JetBrains Mono (variabel, 100–800) | `--font-mono` |

- Alle drei stehen unter der SIL Open Font License 1.1 und werden über `@fontsource-variable/*` 5.3.0 **lokal ausgeliefert** – kein CDN, kein Font-Host (CSP `default-src 'self'`). Gebündelt werden nur die Teilmengen `latin` und `latin-ext`; die Lizenztexte liegen im Build unter `licenses/`.
- Komponenten nennen nie einen Schriftnamen, nur die Tokens. Ein Wechsel der Schrift ist damit eine Änderung in `tokens.css` und `frontend/src/design/fonts.css`.
- Der Build-Test (`frontend/src/build.test.ts`) hält fest, dass keine fremde Adresse im Build steht; der Layout-Test (`frontend/harness/shell.spec.ts`) belegt, dass die Schriftdateien tatsächlich von der eigenen Adresse geladen werden.

## Akzentfarbe

Rosé ist bestätigt (12.11.2026). Der Akzent liegt hinter den Tokens `--color-accent-*` (Skala) und `--accent*` (Rollen) und wird sparsam eingesetzt: Hervorhebung, Regel-/Integrations-Kennzeichen, der Knoten im Bildzeichen. Hauptaktionen und die aktive Navigation bleiben beim Brückenblau.

## Weitere Dateien

- [`vorschau.html`](vorschau.html): Entwurfsvorschau mit allen vier ursprünglichen Logo-Vorschlägen, Farbskalen, Kontrastwerten und Beispielkomponenten. Historisches Arbeitsdokument; maßgeblich sind die Dateien oben.
