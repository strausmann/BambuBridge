# Lessons Learned

Neueste zuerst. Format & Prozess: siehe [`README.md`](README.md) und `.claude/rules/error-handling.md`.

## 2026-06-29 — grd-RDP-Credentials: TPM-Re-Seal überlebt Reboot nicht (offene Frage geklärt)
- **Was passiert ist:** Trotz korrektem `tss`-Gruppen-Fix (User ist in `tss`, `/dev/tpmrm0` =
  `crw-rw---- tss tss`) scheiterte das RDP-Login weiterhin. Journal zeigt **ausschließlich**
  `Esys_ContextLoad failed: tpm:parameter(1):integrity check failed` über mehrere Boots
  (PIDs 1298→1253→1125). Datei-Zeitleiste war der Beweis: Blob `rdp-credentials.priv` **23:54
  versiegelt**, Reboot **23:56**, danach `integrity check failed` — der frisch versiegelte Blob war
  nach genau einem Reboot kaputt.
- **Root Cause:** Der **swtpm-State dieser KVM-VM wird host-/libvirt-seitig nicht über Reboots
  persistiert** → der Owner-Hierarchy-Seed (und damit der Primary/SRK, gegen den grd versiegelt)
  ändert sich bei jedem Boot → jeder TPM-versiegelte Blob validiert nach dem nächsten Reboot nicht
  mehr. Damit ist die im 2026-06-28-Eintrag offen gelassene Frage beantwortet: **Re-Seal allein hilft
  dauerhaft nicht.** Verschärfend: bei funktionierender TPM-Kommunikation, aber kaputtem Blob fällt
  grd **nicht** auf GKeyFile zurück (Fallback greift nur bei `tcti:IO failure` in der TPM-Init), also
  bleibt es hängen statt auszuweichen.
- **Impact:** RDP nach jedem Reboot unbrauchbar; Re-Seal als „Fix" war trügerisch (hält nur bis zum
  nächsten Boot). Vergleich „Windows-11-VM läuft" ist kein Gegenbeweis — jede Domain hat ihren
  **eigenen** swtpm-State, und Windows-RDP versiegelt kein eigenständiges Passwort am TPM
  (Auth via Konto/NTLM-Kerberos).
- **Fix / Prävention:** Entscheidung getroffen — **vTPM aus der libvirt-Domain entfernen**, damit
  grd-TPM-Init mit `tcti:IO failure` ausfällt und stabil auf `credentials.ini` (GKeyFile,
  encrypted-at-rest) zurückfällt, der Reboots übersteht. Host (VM aus): `<tpm>`-Block aus
  `virsh edit <domain>` löschen. Guest danach: stale `rdp-credentials.priv`* entfernen,
  `grdctl --system rdp set-credentials <user> <pw>`, grd neu starten, `grdctl --system status` muss
  sauber sein. **Diagnose-Regel ergänzt:** `integrity check failed` **über mehrere Boots trotz
  Re-Seal** ⇒ nicht nochmal versiegeln, sondern **vTPM-Persistenz** (host-seitig) als Ursache
  behandeln. Alternative (nicht gewählt): swtpm host-seitig persistent machen
  (`persistent_state='yes'` + State unter `/var/lib/libvirt/swtpm/<domain>/` erhalten).
- **Status (erledigt & verifiziert, 2026-06-29):** vTPM aus der libvirt-Domain entfernt — im Guest
  bestätigt durch `ls /dev/tpm*` → *No such file* und grd-Journal nach Reboot **nur noch**
  `Init TPM credentials failed … No TPM device found, using GKeyFile as fallback` + `RDP server
  started`, **kein `integrity check failed` mehr**. Credentials via
  `grdctl --system rdp set-credentials strausmann` neu gesetzt; sie liegen jetzt in
  `…/gnome-remote-desktop/credentials.ini` (Section `[RDP]`, Key `credentials=…`,
  Perms `-rw------- gnome-remote-desktop`) → überlebt Reboots. `grdctl --system status` sauber
  (Unit active, RDP enabled :3389, Username gesetzt). Stale Reste entfernt: `rdp-credentials.priv`
  und beide `*.broken-20260628`-Backups. Offen: reiner End-to-End-RDP-Login nach Reboot als
  Schlussprobe (grd-Init-Pfad ist diesen Boot bereits sauber durchgelaufen).

## 2026-06-28 — GNOME Remote Desktop: RDP-Passwort nach Reboot „nicht entschlüsselbar" (TPM)
- **Was passiert ist:** Der System-Mode-Daemon (`gnome-remote-desktop --system`) konnte die an den
  TPM versiegelten RDP-Credentials nicht laden. Zwei aufeinanderfolgende Symptome: zuerst
  `Init TPM credentials failed … tcti:IO failure, using GKeyFile as fallback`, später nach Reboot
  `[RDP] Couldn't retrieve RDP credentials: Esys_ContextLoad failed: tpm:parameter(1):integrity check failed`.
- **Root Cause:** Der Service-User `gnome-remote-desktop` war **nicht in der `tss`-Gruppe**, die
  Zugriff auf `/dev/tpmrm0` (`crw-rw---- tss tss`) gewährt → TPM-TCTI ließ sich nicht öffnen
  (`IO failure`) → grd schrieb die Credentials in den unverschlüsselten GKeyFile-Fallback. Der in
  einem kurzen Zugriffsfenster erzeugte TPM-Blob (`rdp-credentials.priv`) war zudem **verwaist** und
  validierte nach dem Reboot nicht mehr gegen den TPM-Zustand (KVM-VM mit emuliertem swtpm,
  `systemd-tpm2-setup-early` mangels `measured-uki` übersprungen → keine persistente SRK).
- **Impact:** RDP-Login scheiterte reproduzierbar nach Reboots; lange Fehlsuche Richtung
  „TPM-/Protokoll-Bug", obwohl es eine **Gruppen-Berechtigung** war.
- **Fix / Prävention:** `gnome-remote-desktop` der Gruppe `tss` hinzufügen
  (`usermod -aG tss gnome-remote-desktop`, danach Service neu starten); verwaisten Blob entfernen und
  Credentials neu versiegeln (`grdctl --system rdp set-credentials`). **Diagnose-Regel:** `tcti:IO
  failure` ⇒ Geräte-/Gruppen-Permission prüfen (`id <svc-user>`, `getent group tss`,
  `/proc/<pid>/status` Groups), **nicht** den TPM/Blob; `Esys_ContextLoad … integrity check failed`
  ⇒ Blob ist stale, neu versiegeln. Offen/zu beobachten: ob der swtpm seinen Owner-Seed über Reboots
  persistiert (sonst host-/libvirt-seitiger Fix). Verwandt: grd-Keyring-Eintrag (per-User) weiter
  unten — anderer Speicherpfad, gleiche Klasse „Credential-Storage statt Protokoll".

## 2026-06-28 — semantic-release scheiterte am eigenen husky/commitlint-Hook
- **Was passiert ist:** Der erste `release.yml`-Lauf auf `main` schlug fehl: semantic-release
  erstellt den Commit `chore(release): 1.0.0 …`, aber der im CI via `npm install` aktivierte
  **husky `commit-msg`-Hook** ließ commitlint darüber laufen → `body-max-line-length` (100) durch die
  Changelog-Zeile (Feature-Bullet mit langer Commit-URL) verletzt → Commit + Release abgebrochen.
- **Root Cause:** husky-Hooks im CI aktiv; sie linten auch den automatisch erzeugten Release-Commit.
- **Impact:** Kein Tag/Release/CHANGELOG erzeugt (Release-Pipeline rot).
- **Fix / Prävention:** `HUSKY: 0` als Job-`env` in `release.yml` (Hooks im CI aus). Standardpraxis;
  betrifft nur den Bot-Commit, nicht die commitlint-Prüfung von Contributor-Commits (eigener Workflow).
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
