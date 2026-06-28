# Lessons Learned

Neueste zuerst. Format & Prozess: siehe [`README.md`](README.md) und `.claude/rules/error-handling.md`.

## 2026-06-28 — Schlussfolgerung öffentlich gepostet vor vollständiger Verifikation
- **Was passiert ist:** Die Aussage „Pangolin nutzt ein veraltetes IronRDP" wurde als
  Schlussfolgerung präsentiert und öffentlich im Issue kommentiert, **bevor** der aktuelle Release
  (1.19.4) konkret geprüft war (erst auf Nachfrage verifiziert).
- **Root Cause:** Teil-verifizierte Annahme wurde wie eine belegte Tatsache behandelt; Verlass
  darauf, dass der Nutzer Lücken findet.
- **Impact:** Glück, dass es stimmte; Reputationsrisiko bei öffentlichem Post.
- **Fix / Prävention:** Rule **R1** (`CLAUDE.md`) + Memory `verify-before-concluding` — vollständig
  verifizieren, bevor geschlussfolgert/gepostet wird.

## 2026-06-28 — `apt-get autoremove -y` entfernte BIOS-Grub-Pakete
- **Was passiert ist:** Beim Entfernen eines Diagnose-Tools entfernte `autoremove` zusätzlich
  `grub-pc`/`grub-pc-bin`/`grub-gfxpayload-lists`.
- **Root Cause:** Breiter `autoremove -y` ohne Vorabsicht auf die Entfernungsliste.
- **Impact:** Keiner (VM bootet UEFI; BIOS-Grub funktionslos) — aber potenziell riskant auf
  BIOS-Systemen.
- **Fix / Prävention:** Pakete **gezielt** entfernen; vor `autoremove` die Liste prüfen
  (ohne `-y` bzw. `--dry-run`), besonders bei boot-/kernel-nahen Paketen.

## 2026-06-28 — VNC-Display :0 belegt (Annahme „frei")
- **Was passiert ist:** TigerVNC wurde auf Display `:0` gestartet und scheiterte
  („server already running"), weil die GNOME-Wayland-Konsole (`Xwayland :0`) `:0` belegt.
- **Root Cause:** Display-Nummer ohne Prüfung der bestehenden Sessions/Sockets gewählt.
- **Impact:** Restart-Schleife, Zeitverlust.
- **Fix / Prävention:** Vor Ressourcenbelegung (Displays, Ports) bestehende Belegung enumerieren;
  hier gelöst durch Display `:2` + festen `-rfbport 5900`.

## 2026-06-28 — grd RDP-Credentials aus `runuser` persistieren nicht
- **Was passiert ist:** `grdctl rdp set-credentials` von außerhalb der grafischen Session schrieb
  **nichts** in den GNOME-Keyring → RDP-Auth gegen leeres Passwort scheiterte (irreführend als
  „CredSSP/MIC"-Fehler).
- **Root Cause:** libsecret/Keyring-Schreibzugriff braucht die aktive grafische User-Session.
- **Impact:** Lange Fehlersuche Richtung „Protokoll-Bug", obwohl es Credential-Storage war.
- **Fix / Prävention:** grd-Credentials **in der Desktop-Session** des Users setzen; Erkenntnis im
  Issue #3272 dokumentiert.
