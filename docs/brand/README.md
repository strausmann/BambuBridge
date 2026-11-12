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

Quelle der Wahrheit: [`tokens.css`](tokens.css) (Tailwind 4). Aufbau wie im Label Printer Hub und in Kept: Skalen als `@theme`, semantische Rollen als `@theme inline`, Light als Standard, Dark per System und per `data-theme`.

| Rolle | Light | Dark | Verwendung |
|---|---|---|---|
| `primary` | `#006E99` | `#4FB9EB` | Hauptaktionen, aktive Navigation, Bildzeichen |
| `accent` | `#A1376E` | `#F183B6` | sparsam: Hervorhebung, Regel-/Integrations-Kennzeichen |
| `bg` / `surface` / `sunken` | `#F3F7FB` / `#FBFEFF` / `#E9EDF1` | `#0D1218` / `#161C23` / `#1E252C` | Flächen |
| `ink` / `ink-2` / `ink-3` | `#20262C` / `#4B5259` / `#5F656D` | `#F0F4F7` / `#C3C8CE` / `#9FA5AC` | Text |
| `ok` / `warn` / `bad` / `info` | `#00704E` / `#8C5007` / `#B02B27` / `#006E99` | `#5ED8A9` / `#FCB26F` / `#FF958A` / `#83D1F9` | nur Zustände |

- Alle Textpaare erfüllen WCAG 2.2 AA (niedrigster Wert 4.87:1); Eingaberahmen ≥ 3:1. Ein Kontrast-Test wie im Printer Hub (`tokens.test.ts`) hält das fest.
- Zustand nie nur über Farbe zeigen (zusätzlich Text oder Symbol).

## Abgrenzung zu Bambu Lab

Die BambuBridge ist kein Produkt von Bambu Lab und darf nicht so aussehen.

- **Kein** Bambus-Motiv, **kein** stilisiertes „B“ aus Streifen, **kein** Bambu-Lab-Logo, auch nicht in Screenshots als Deko.
- **Keine** grün-dominante Fläche. Bambu-Grün `#00AE42` ist tabu; Abstand der Primärfarbe ΔE2000 ≈ 49. Grün erscheint nur als Statusfarbe `ok` (bläulicher, Hue 165°).
- Den Namen „Bambu“ nur als Teil des Projektnamens bzw. zur sachlichen Beschreibung der unterstützten Geräte verwenden, nie so, dass eine Verbindung zu Bambu Lab nahegelegt wird.

## Offen

- **Schrift:** Die Entwurfsvorschau nutzt Space Grotesk und Inter. Für die App gilt wie im Printer Hub: Schriften lokal ausliefern (`@fontsource`), kein CDN (CSP). Die endgültige Wahl fällt beim Bau der Oberfläche.
- **Akzentfarbe:** Rosé ist Entwurf; bestätigt ist bisher nur die Primärfarbe.

## Weitere Dateien

- [`vorschau.html`](vorschau.html): Entwurfsvorschau mit allen vier ursprünglichen Logo-Vorschlägen, Farbskalen, Kontrastwerten und Beispielkomponenten. Historisches Arbeitsdokument; maßgeblich sind die Dateien oben.
